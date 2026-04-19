from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import sqlite3
from datetime import datetime
import pandas as pd

from database import get_connection
from driver_signals import submit_driver_signal, apply_active_signals
from inference import DemandPredictor
from rerouting import check_recalls, find_reroutings

app = FastAPI(title="Istanbul Bus Rerouting API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def read_index():
    return FileResponse("static/index.html")

@app.get("/sw.js")
def read_sw():
    return FileResponse("static/sw.js", media_type="application/javascript")

class SignalRequest(BaseModel):
    driver_id: str
    route: str
    signal: str

@app.get("/api/state")
def get_state():
    now = datetime.now()
    hour = now.hour
    weekday = now.weekday()

    conn = get_connection()

    # First try exact hour + weekday match
    query_exact = """
        SELECT route, route_desc, busiest_station,
               base_avg_passengers, buses_on_route, signal_modifier
        FROM demand_state
        WHERE hour = ? AND weekday = ?
    """
    df_exact = pd.read_sql_query(query_exact, conn, params=(hour, weekday))

    # Get all routes so we can fill in missing ones
    query_all = """
        SELECT route, route_desc, busiest_station,
               AVG(base_avg_passengers) as base_avg_passengers,
               AVG(buses_on_route) as buses_on_route,
               AVG(signal_modifier) as signal_modifier
        FROM demand_state
        GROUP BY route
    """
    df_all = pd.read_sql_query(query_all, conn)
    conn.close()

    # Merge: exact match rows take priority; fill remaining routes from df_all
    if not df_exact.empty:
        exact_routes = set(df_exact["route"].tolist())
        df_fill = df_all[~df_all["route"].isin(exact_routes)]
        df = pd.concat([df_exact, df_fill], ignore_index=True)
    else:
        df = df_all

    if df.empty:
        return {"status": "success", "data": []}

    import numpy as np

    # effective_score = load factor (passengers relative to bus capacity)
    # base_avg_passengers is a normalized metric per bus-hour
    df["effective_score"] = (df["base_avg_passengers"] / df["buses_on_route"]) + df["signal_modifier"]
    df["effective_score"] = df["effective_score"].replace([np.inf, -np.inf], 0).fillna(0)
    df["effective_score"] = df["effective_score"].clip(lower=0)

    # Realistic passenger estimate: multiply by 50 (avg Istanbul bus ~50 pax/trip average)
    df["total_passengers"] = (df["base_avg_passengers"] * df["buses_on_route"] * 50).round(0).astype(int)

    # User-defined thresholds:
    # score > 1.0  → overcrowded (kırmızı)
    # score < 0.90 → undercrowded (yeşil)
    # otherwise    → normal (sarı)
    def get_status(score):
        if score > 1.0:  return "overcrowded"
        elif score < 0.90: return "undercrowded"
        return "normal"

    df["status"] = df["effective_score"].apply(get_status)
    df = df.sort_values("effective_score", ascending=False)

    import json
    return {"status": "success", "data": json.loads(df.to_json(orient="records"))}


@app.get("/api/reroutes")
def get_reroutes():
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM active_reroutes ORDER BY timestamp DESC LIMIT 5", conn)
    conn.close()
    import json
    return {"status": "success", "data": json.loads(df.to_json(orient="records"))}


@app.get("/api/routes_list")
def get_routes_list():
    conn = get_connection()
    query = "SELECT DISTINCT route, route_desc FROM demand_state ORDER BY route"
    df = pd.read_sql_query(query, conn)
    conn.close()
    import json
    return {"status": "success", "data": json.loads(df.to_json(orient="records"))}


@app.get("/api/map_routes")
def get_map_routes():
    import json
    import os
    import pandas as pd
    from datetime import datetime
    
    file_path = "data/route_map_data.json"
    if not os.path.exists(file_path):
        return {"status": "error", "message": "Map data not generated yet."}
        
    with open(file_path, "r", encoding="utf-8") as f:
        map_data = json.load(f)
        
    # Get current real-time data
    now = datetime.now()
    conn = get_connection()
    query = """
        SELECT route, base_avg_passengers, buses_on_route, signal_modifier
        FROM demand_state
        WHERE hour = ? AND weekday = ?
    """
    df = pd.read_sql_query(query, conn, params=(now.hour, now.weekday()))
    conn.close()
    
    if not df.empty:
        import numpy as np
        df["score"] = (df["base_avg_passengers"] / df["buses_on_route"]) + df["signal_modifier"]
        df["score"] = df["score"].replace([np.inf, -np.inf], 0).fillna(0)
        
        # Create a dictionary for fast lookup: route -> score
        score_dict = df.set_index("route")["score"].to_dict()
        
        # Update map_data with real-time scores
        for r in map_data.get("routes", []):
            route_code = r.get("route")
            if route_code in score_dict:
                r["demand_score"] = score_dict[route_code]
                
    return {"status": "success", "data": map_data}


@app.get("/api/analysis/{route}")
def get_route_analysis(route: str):
    now = datetime.now()
    weekday = now.weekday()
    
    conn = get_connection()
    query = """
        SELECT hour, base_avg_passengers, buses_on_route 
        FROM demand_state 
        WHERE route = ? AND weekday = ?
        ORDER BY hour ASC
    """
    df = pd.read_sql_query(query, conn, params=(route, weekday))
    conn.close()
    
    if df.empty:
        return {"status": "error", "message": "No data found for this route"}
        
    import json
    return {"status": "success", "data": json.loads(df.to_json(orient="records"))}


@app.get("/api/notifications")
def get_notifications():
    conn = get_connection()
    # Combine signals and reroutes into a single notifications list
    signals_df = pd.read_sql_query("SELECT timestamp, route, driver_id, signal_type as action, 'signal' as type FROM driver_signals ORDER BY timestamp DESC LIMIT 20", conn)
    reroutes_df = pd.read_sql_query("SELECT timestamp, original_route as route, 'Rerouted to ' || helping_route as action, 'reroute' as type FROM active_reroutes ORDER BY timestamp DESC LIMIT 20", conn)
    conn.close()
    
    combined = pd.concat([signals_df, reroutes_df], ignore_index=True)
    
    # Add dummy base notifications as requested by user
    import datetime as dt
    now_str = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    dummy_data = pd.DataFrame([
        {"timestamp": now_str, "route": "132G", "driver_id": "SISTEM", "action": "kaza", "type": "signal"},
        {"timestamp": now_str, "route": "500T", "driver_id": "SISTEM", "action": "yol_calismasi", "type": "signal"},
        {"timestamp": now_str, "route": "11US", "driver_id": "SISTEM", "action": "yogun_trafik", "type": "signal"}
    ])
    combined = pd.concat([combined, dummy_data], ignore_index=True)
    
    if not combined.empty:
        combined = combined.sort_values("timestamp", ascending=False).head(30)
    
    import json
    return {"status": "success", "data": json.loads(combined.to_json(orient="records"))}


@app.post("/api/signal")
def submit_signal(req: SignalRequest):
    valid_signals = ["full", "normal", "empty", "kaza", "yol_calismasi", "yogun_trafik"]
    if req.signal not in valid_signals:
        raise HTTPException(status_code=400, detail="Invalid signal")
        
    submit_driver_signal(req.driver_id, req.route, req.signal)
    
    # Apply immediately
    now = datetime.now()
    apply_active_signals(now.hour, now.weekday())
    
    return {"status": "success", "message": f"Durum bildirimi alındı."}

class ChatRequest(BaseModel):
    message: str

class DriverRerouteRequest(BaseModel):
    driver_id: str
    original_route: str
    helping_route: str

@app.post("/api/driver_reroute")
def accept_driver_reroute(req: DriverRerouteRequest):
    now = datetime.now()
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM active_reroutes WHERE driver_id = ?", (req.driver_id,))
    c.execute(
        "INSERT INTO active_reroutes (driver_id, original_route, helping_route, timestamp) VALUES (?, ?, ?, ?)",
        (req.driver_id, req.original_route, req.helping_route, datetime.now())
    )
    c.execute("""
        UPDATE demand_state 
        SET buses_on_route = buses_on_route - 1 
        WHERE route = ? AND hour = ? AND weekday = ? AND buses_on_route > 0
    """, (req.original_route, now.hour, now.weekday()))
    c.execute("""
        UPDATE demand_state 
        SET buses_on_route = buses_on_route + 1 
        WHERE route = ? AND hour = ? AND weekday = ?
    """, (req.helping_route, now.hour, now.weekday()))
    conn.commit()
    conn.close()
    return {"status": "success", "message": f"{req.original_route} hattından {req.helping_route} hattına başarıyla yönlendirildiniz."}

def _normalize_turkish(text: str) -> str:
    """Normalize Turkish special characters to ASCII equivalents for flexible matching."""
    replacements = {
        'ğ': 'g', 'Ğ': 'g',
        'ü': 'u', 'Ü': 'u',
        'ş': 's', 'Ş': 's',
        'ı': 'i', 'İ': 'i',
        'ö': 'o', 'Ö': 'o',
        'ç': 'c', 'Ç': 'c',
    }
    for tr_char, ascii_char in replacements.items():
        text = text.replace(tr_char, ascii_char)
    return text

@app.post("/api/chat")
def handle_chat(req: ChatRequest):
    msg_raw = req.message.lower().strip()
    # Normalize so "yogun" matches "yoğun", "kalabalik" matches "kalabalık", etc.
    msg = _normalize_turkish(msg_raw)

    now = datetime.now()
    hour = now.hour
    weekday = now.weekday()

    conn = get_connection()

    try:
        import numpy as np

        # --- Scenario 1: Crowded / busy routes ---
        crowded_keywords = [
            "yogun", "youn", "kalabalik", "sorunlu", "en cok", "dolu",
            "hangi hatlar yogun", "yogun hatlar", "en yogun", "problem"
        ]
        if any(kw in msg for kw in crowded_keywords):
            query = """
                SELECT route, base_avg_passengers, buses_on_route, signal_modifier, route_desc
                FROM demand_state
                WHERE hour = ? AND weekday = ?
            """
            df = pd.read_sql_query(query, conn, params=(hour, weekday))
            if not df.empty:
                df["score"] = (df["base_avg_passengers"] / df["buses_on_route"]) + df["signal_modifier"]
                df["score"] = df["score"].replace([np.inf, -np.inf], 0).fillna(0)
                df = df.sort_values("score", ascending=False).head(3)

                response_text = "🚨 <b>Şu anda en yoğun 3 hat:</b><br><br>"
                for _, row in df.iterrows():
                    response_text += f"🔴 <b>{row['route']}</b> — {row['route_desc']}<br>&nbsp;&nbsp;&nbsp;👥 ~{int(row['base_avg_passengers'])} yolcu | 🚌 {row['buses_on_route']} otobüs<br><br>"
                return {"status": "success", "response": response_text}

        # --- Scenario 2: Empty / idle routes ---
        empty_keywords = [
            "bos", "atil", "musait", "hic yolcu", "az yolcu",
            "hangi hatlar bos", "bos hatlar", "en bos", "idle"
        ]
        if any(kw in msg for kw in empty_keywords):
            query = """
                SELECT route, base_avg_passengers, buses_on_route, signal_modifier, route_desc
                FROM demand_state
                WHERE hour = ? AND weekday = ? AND buses_on_route > 0
            """
            df = pd.read_sql_query(query, conn, params=(hour, weekday))
            if not df.empty:
                df["score"] = (df["base_avg_passengers"] / df["buses_on_route"]) + df["signal_modifier"]
                df["score"] = df["score"].replace([np.inf, -np.inf], 0).fillna(0)
                df = df.sort_values("score", ascending=True).head(3)

                response_text = "✅ <b>Şu anda en boş 3 hat:</b><br><br>"
                for _, row in df.iterrows():
                    response_text += f"🟢 <b>{row['route']}</b> — {row['route_desc']}<br>&nbsp;&nbsp;&nbsp;👥 ~{int(row['base_avg_passengers'])} yolcu | 🚌 {row['buses_on_route']} otobüs<br><br>"
                return {"status": "success", "response": response_text}

        # --- Scenario 3: Rerouting activity ---
        reroute_keywords = [
            "rota", "yonlendirme", "transfer", "degisiklik", "son rotalama",
            "hangi hatlar yonlendirildi", "aktarma"
        ]
        if any(kw in msg for kw in reroute_keywords):
            df = pd.read_sql_query(
                "SELECT original_route, helping_route, timestamp FROM active_reroutes ORDER BY timestamp DESC LIMIT 5",
                conn
            )
            if not df.empty:
                response_text = "🔄 <b>Son yönlendirmeler:</b><br><br>"
                for _, row in df.iterrows():
                    response_text += f"🚌 <b>{row['original_route']}</b> → <b>{row['helping_route']}</b><br>&nbsp;&nbsp;&nbsp;🕐 {row['timestamp']}<br><br>"
                return {"status": "success", "response": response_text}
            else:
                return {"status": "success", "response": "Şu an aktif bir yönlendirme bulunmuyor."}

        # --- Scenario 4: Total stats / summary ---
        stats_keywords = [
            "kac hat", "toplam", "ozet", "durum", "genel", "sistem",
            "summary", "stats", "hatlarin durumu", "tum hatlar"
        ]
        if any(kw in msg for kw in stats_keywords):
            df = pd.read_sql_query(
                "SELECT route, base_avg_passengers, buses_on_route, signal_modifier FROM demand_state WHERE hour = ? AND weekday = ?",
                conn, params=(hour, weekday)
            )
            if not df.empty:
                df["score"] = (df["base_avg_passengers"] / df["buses_on_route"]) + df["signal_modifier"]
                df["score"] = df["score"].replace([np.inf, -np.inf], 0).fillna(0)
                overcrowded = len(df[df["score"] >= 2.0])
                normal = len(df[(df["score"] > 0.5) & (df["score"] < 2.0)])
                empty = len(df[df["score"] <= 0.5])
                return {
                    "status": "success",
                    "response": f"📊 <b>Sistem Özeti ({now.strftime('%H:%M')}):</b><br><br>"
                                f"🔴 Aşırı yoğun hat: <b>{overcrowded}</b><br>"
                                f"🟡 Normal hat: <b>{normal}</b><br>"
                                f"🟢 Boş hat: <b>{empty}</b><br>"
                                f"📍 Toplam izlenen hat: <b>{len(df)}</b>"
                }

        # --- Scenario 5: Ask about a specific route code ---
        words = msg_raw.upper().split()
        for word in words:
            word = ''.join(e for e in word if e.isalnum())
            if len(word) > 1 and any(char.isdigit() for char in word):
                query = """
                    SELECT route, base_avg_passengers, buses_on_route, signal_modifier, route_desc, busiest_station
                    FROM demand_state
                    WHERE route = ? AND hour = ? AND weekday = ?
                """
                df = pd.read_sql_query(query, conn, params=(word, hour, weekday))
                if not df.empty:
                    row = df.iloc[0]
                    score = (row['base_avg_passengers'] / row['buses_on_route']) + row['signal_modifier']
                    if score >= 2.0:
                        status_icon, status_text = "🔴", "Aşırı Yoğun"
                    elif score <= 0.5:
                        status_icon, status_text = "🟢", "Boş / Normal"
                    else:
                        status_icon, status_text = "🟡", "Normal"
                    return {
                        "status": "success",
                        "response": f"{status_icon} <b>{word}</b> — {row['route_desc']}<br><br>"
                                    f"Durum: <b>{status_text}</b><br>"
                                    f"👥 Yolcu: ~{int(row['base_avg_passengers'])}<br>"
                                    f"🚌 Aktif otobüs: {row['buses_on_route']}<br>"
                                    f"📍 En kalabalık durak: {row['busiest_station']}"
                    }

        # --- Default fallback ---
        return {
            "status": "success",
            "response": "🤖 Bunu anlayamadım. Şu sorulardan birini deneyebilirsiniz:<br><br>"
                        "• <b>Yogun hatlari nedir?</b><br>"
                        "• <b>Bos hatlar hangileri?</b><br>"
                        "• <b>Son yonlendirmeler neler?</b><br>"
                        "• <b>Sistem ozeti</b><br>"
                        "• <b>500T durumu nedir?</b>"
        }

    finally:
        conn.close()


def _run_rerouting_cycle():
    now = datetime.now()
    hour = now.hour
    weekday = now.weekday()
    
    print("[API] Running manual rerouting cycle...")
    
    apply_active_signals(hour, weekday)
    
    try:
        predictor = DemandPredictor()
        next_hour = now + pd.Timedelta(hours=1)
        predictions_df = predictor.predict_all_routes(next_hour)
    except Exception as e:
        print(f"[API] Predictor error: {e}")
        predictions_df = None
        
    check_recalls(hour, weekday)
    find_reroutings(hour, weekday, predictions_df)


@app.post("/api/trigger_cycle")
def trigger_cycle(background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_rerouting_cycle)
    return {"status": "success", "message": "Cycle triggered in background"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

"""
Step 4: Rerouting Logic (SQLite & Proactive)
Rules:
- Uses predicted demand for T+1 from DemandPredictor.
- Only redeploy buses from routes with low effective demand.
- Minimum Service Guarantee: Never reduce buses_on_route to 1 or below.
- Routes must be within MAX_DISTANCE_KM of each other.
- Transactional update of SQLite database for live buses count.
- Buses recalled when target route demand normalizes.
"""

import pandas as pd
import sqlite3
import math
from datetime import datetime, timedelta
from dataclasses import dataclass
from database import get_connection

# ── CONFIG ────────────────────────────────────────────────────────────────────
OVERCROWDED_THRESH  = 2.0
UNDERCROWDED_THRESH = 0.5
RECALL_THRESH       = 1.2
END_OF_DAY_HOUR     = 23
MAX_DISTANCE_KM     = 15.0
MIN_BUSES_LIMIT     = 2     # Minimum Service Guarantee
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class RerouteAction:
    from_route:        str
    to_route:          str
    distance_km:       float
    before_score_from: float
    before_score_to:   float
    after_score_from:  float
    after_score_to:    float


@dataclass
class RecallAction:
    driver_id:    str
    from_route:   str   
    to_route:     str   
    reason:       str   


def get_route_coordinates() -> dict:
    """Fetch precomputed coordinates from local SQLite."""
    conn = get_connection()
    df = pd.read_sql_query("SELECT route, lat, lon FROM routes", conn)
    conn.close()
    
    return {row["route"]: (row["lat"], row["lon"]) for _, row in df.iterrows()}


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def load_live_state(hour: int, weekday: int) -> pd.DataFrame:
    """Load current demand state combined with driver signals."""
    conn = get_connection()
    query = """
        SELECT route, base_avg_passengers, buses_on_route, signal_modifier
        FROM demand_state
        WHERE hour = ? AND weekday = ?
    """
    df = pd.read_sql_query(query, conn, params=(hour, weekday))
    conn.close()
    
    if df.empty:
        return df
        
    # Calculate effective demand score
    # score = (passengers / buses) + signal_modifier
    df["effective_score"] = (df["base_avg_passengers"] / df["buses_on_route"]) + df["signal_modifier"]
    # Ensure score doesn't go negative
    df["effective_score"] = df["effective_score"].clip(lower=0)
    
    return df


def register_reroute(conn: sqlite3.Connection, driver_id: str, original_route: str, helping_route: str):
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO active_reroutes (driver_id, original_route, helping_route)
        VALUES (?, ?, ?)
    ''', (driver_id, original_route, helping_route))


def unregister_reroute(conn: sqlite3.Connection, driver_id: str):
    cursor = conn.cursor()
    cursor.execute('DELETE FROM active_reroutes WHERE driver_id = ?', (driver_id,))


def update_bus_count(conn: sqlite3.Connection, route: str, hour: int, weekday: int, delta: int):
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE demand_state 
        SET buses_on_route = MAX(1, buses_on_route + ?)
        WHERE route = ? AND hour = ? AND weekday = ?
    ''', (delta, route, hour, weekday))


def check_recalls(hour: int, weekday: int) -> list[RecallAction]:
    """Check active reroutes and issue recalls if demand normalized or end of day."""
    conn = get_connection()
    df_reroutes = pd.read_sql_query("SELECT driver_id, original_route, helping_route FROM active_reroutes", conn)
    
    if df_reroutes.empty:
        conn.close()
        return []

    state_df = load_live_state(hour, weekday)
    recalls = []
    end_of_day = (hour >= END_OF_DAY_HOUR)

    for _, r in df_reroutes.iterrows():
        helping = r["helping_route"]
        score_row = state_df[state_df["route"] == helping]
        current_score = float(score_row["effective_score"].values[0]) if not score_row.empty else 0.0

        if end_of_day:
            reason = "end_of_day"
        elif current_score <= RECALL_THRESH:
            reason = "demand_resolved"
        else:
            continue

        recalls.append(RecallAction(
            driver_id  = r["driver_id"],
            from_route = helping,
            to_route   = r["original_route"],
            reason     = reason
        ))
        
        # Atomically restore buses
        unregister_reroute(conn, r["driver_id"])
        update_bus_count(conn, helping, hour, weekday, -1)             # remove from helped route
        update_bus_count(conn, r["original_route"], hour, weekday, +1) # return to original route

    conn.commit()
    conn.close()
    return recalls


def notify_recall(recall: RecallAction):
    reason_text = {
        "demand_resolved": "Demand on your assisted route has normalized",
        "end_of_day":      "End of service day"
    }.get(recall.reason, recall.reason)

    print(f"\n[RECALL] Driver {recall.driver_id}: {recall.from_route} → {recall.to_route} ({reason_text})")


def find_reroutings(hour: int, weekday: int, predictions_df: pd.DataFrame = None) -> list[RerouteAction]:
    """
    If predictions_df is provided (from T+1), use it to identify target overcrowded routes.
    Otherwise, fallback to current hour's state.
    """
    state_df = load_live_state(hour, weekday)
    if state_df.empty:
        print(f"No state data found for hour={hour}, weekday={weekday}")
        return []

    # If we have future predictions, use them to define targets. Otherwise use current state.
    if predictions_df is not None and not predictions_df.empty:
        # Merge predictions with current state to get current buses and calculate effective score 
        # based on PREDICTED passengers but CURRENT buses + signals
        merged = pd.merge(state_df, predictions_df, on="route", how="inner")
        merged["eval_score"] = (merged["pred_passengers"] / merged["buses_on_route"]) + merged["signal_modifier"]
        merged["eval_score"] = merged["eval_score"].clip(lower=0)
    else:
        merged = state_df.copy()
        merged["eval_score"] = merged["effective_score"]

    coords = get_route_coordinates()
    actions = []
    
    conn = get_connection()

    while True:
        overcrowded  = merged[merged["eval_score"] >= OVERCROWDED_THRESH].sort_values("eval_score", ascending=False)
        undercrowded = merged[
            (merged["eval_score"] <= UNDERCROWDED_THRESH) & 
            (merged["buses_on_route"] > MIN_BUSES_LIMIT)  # Minimum Service Guarantee
        ].sort_values("eval_score", ascending=True)

        if overcrowded.empty or undercrowded.empty:
            break

        target = overcrowded.iloc[0]
        target_coords = coords.get(target["route"])
        if not target_coords:
            merged.loc[merged["route"] == target["route"], "eval_score"] -= 0.01
            continue

        best_source, best_distance = None, float("inf")

        for _, source in undercrowded.iterrows():
            if source["route"] == target["route"]:
                continue
                
            source_coords = coords.get(source["route"])
            if not source_coords:
                continue

            dist = haversine_km(target_coords[0], target_coords[1], source_coords[0], source_coords[1])
            
            # Simple heuristic: Assuming 20km/h average speed in city, 15km takes ~45 mins. 
            # We enforce MAX_DISTANCE_KM.
            if dist <= MAX_DISTANCE_KM and dist < best_distance:
                best_source, best_distance = source, dist

        if best_source is None:
            # No suitable source found, slightly penalize target to evaluate others
            merged.loc[merged["route"] == target["route"], "eval_score"] -= 0.01
            continue

        # Valid reroute found. Perform atomic updates.
        before_from  = float(best_source["eval_score"])
        before_to    = float(target["eval_score"])

        # Update dataframes
        merged.loc[merged["route"] == best_source["route"], "buses_on_route"] -= 1
        merged.loc[merged["route"] == target["route"], "buses_on_route"] += 1
        
        # Re-evaluate scores
        for idx in [best_source.name, target.name]:
            row = merged.loc[idx]
            base_pass = row.get("pred_passengers", row["base_avg_passengers"])
            merged.loc[idx, "eval_score"] = max(0, (base_pass / merged.loc[idx, "buses_on_route"]) + row["signal_modifier"])

        after_from = float(merged.loc[merged["route"] == best_source["route"], "eval_score"].values[0])
        after_to   = float(merged.loc[merged["route"] == target["route"], "eval_score"].values[0])

        # Commit to DB
        driver_id = f"AUTO-{best_source['route']}-{datetime.now().strftime('%H%M%S')}"
        
        try:
            update_bus_count(conn, best_source["route"], hour, weekday, -1)
            update_bus_count(conn, target["route"], hour, weekday, +1)
            register_reroute(conn, driver_id, best_source["route"], target["route"])
            conn.commit()
            
            actions.append(RerouteAction(
                from_route        = best_source["route"],
                to_route          = target["route"],
                distance_km       = round(best_distance, 2),
                before_score_from = round(before_from, 3),
                before_score_to   = round(before_to,   3),
                after_score_from  = round(after_from,  3),
                after_score_to    = round(after_to,    3),
            ))
        except Exception as e:
            print(f"Error saving reroute transaction: {e}")
            conn.rollback()
            break

    conn.close()
    return actions


def print_report(actions: list[RerouteAction]):
    if not actions:
        print("\nNo rerouting actions needed or possible.")
        return

    print("\n" + "="*65)
    print(f"  REROUTING REPORT — {len(actions)} action(s) recommended")
    print("="*65)
    for i, a in enumerate(actions, 1):
        print(f"\n[{i}] FROM: {a.from_route}")
        print(f"     TO:   {a.to_route}")
        print(f"     Distance:  {a.distance_km} km")
        print(f"     Score change (source): {a.before_score_from} → {a.after_score_from}")
        print(f"     Score change (target): {a.before_score_to}   → {a.after_score_to}")
    print("="*65)

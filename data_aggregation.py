"""
Step 1: Data Aggregation & Database Initialization
Reads raw Istanbulkart hourly passenger data,
aggregates into (route, hour, weekday) → avg_passengers & buses_on_route,
and populates the SQLite database.
Also pre-fetches route coordinates from IETT API.
"""

import pandas as pd
import json
import sqlite3
from database import get_connection, init_db

try:
    from zeep import Client
    ZEEP_AVAILABLE = True
except ImportError:
    ZEEP_AVAILABLE = False

# ── CONFIG ────────────────────────────────────────────────────────────────────
RAW_PASSENGER_CSV = "data/hourly_passengers.csv"   # from data.ibb.gov.tr
IETT_BASE         = "https://api.ibb.gov.tr/iett"

COL_DATE       = "transition_date"
COL_HOUR       = "transition_hour"
COL_LINE_NAME  = "line_name"
COL_LINE_DESC  = "line"
COL_STATION    = "station_poi_desc_cd"
COL_PASSENGERS = "number_of_passenger"
# ─────────────────────────────────────────────────────────────────────────────


def load_passenger_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    df.columns = df.columns.str.strip().str.lower()

    df[COL_DATE] = pd.to_datetime(df[COL_DATE], dayfirst=True, errors="coerce")
    df["WEEKDAY"] = df[COL_DATE].dt.dayofweek
    df["HOUR"]    = pd.to_numeric(df[COL_HOUR], errors="coerce").astype("Int64")
    df[COL_PASSENGERS] = pd.to_numeric(df[COL_PASSENGERS], errors="coerce")
    df["number_of_passage"] = pd.to_numeric(df["number_of_passage"], errors="coerce")

    # If line_name is missing, fallback to line desc
    if COL_LINE_NAME in df.columns:
        df[COL_LINE_NAME] = df[COL_LINE_NAME].fillna(df[COL_LINE_DESC])
    else:
        df[COL_LINE_NAME] = df[COL_LINE_DESC]
        
    if COL_STATION not in df.columns:
        df[COL_STATION] = "Bilinmiyor"
    else:
        df[COL_STATION] = df[COL_STATION].fillna("Bilinmiyor")

    return df[[COL_LINE_NAME, COL_LINE_DESC, COL_STATION, "HOUR", "WEEKDAY", COL_PASSENGERS, "number_of_passage"]].dropna(subset=["HOUR", "WEEKDAY", COL_PASSENGERS, "number_of_passage"])


def aggregate_data(df: pd.DataFrame) -> pd.DataFrame:
    print("  Calculating average passengers and identifying route descriptions...")
    agg = (
        df.groupby([COL_LINE_NAME, "HOUR", "WEEKDAY"])
        .agg(
            avg_passengers=(COL_PASSENGERS, "mean"),
            buses_on_route=("number_of_passage", "mean"),
            route_desc=(COL_LINE_DESC, lambda x: x.mode()[0] if not x.mode().empty else "Bilinmiyor")
        )
        .reset_index()
        .rename(columns={COL_LINE_NAME: "route", "HOUR": "hour", "WEEKDAY": "weekday"})
    )
    agg["buses_on_route"] = agg["buses_on_route"].clip(lower=1).round().astype(int)
    
    print("  Identifying busiest stations per route and hour...")
    station_demand = df.groupby([COL_LINE_NAME, "HOUR", "WEEKDAY", COL_STATION])[COL_PASSENGERS].sum().reset_index()
    idx = station_demand.groupby([COL_LINE_NAME, "HOUR", "WEEKDAY"])[COL_PASSENGERS].idxmax()
    busiest_stations = station_demand.loc[idx, [COL_LINE_NAME, "HOUR", "WEEKDAY", COL_STATION]]
    busiest_stations = busiest_stations.rename(columns={COL_LINE_NAME: "route", "HOUR": "hour", "WEEKDAY": "weekday", COL_STATION: "busiest_station"})
    
    agg = pd.merge(agg, busiest_stations, on=["route", "hour", "weekday"], how="left")
    agg["busiest_station"] = agg["busiest_station"].fillna("Bilinmiyor")
    
    return agg


def fetch_route_coordinates(routes: list) -> list:
    """Fetch center coordinates for a list of routes from IETT API."""
    route_coords = []
    
    try:
        if not ZEEP_AVAILABLE:
            raise ImportError("Zeep not installed.")
            
        print(f"Fetching coordinates for {len(routes)} routes from IETT API. This may take a while...")
        client = Client(wsdl=f"{IETT_BASE}/UlasimAnaVeri/HatDurakGuzergah.asmx?wsdl")
        data = client.service.GetDurak_json(DurakKodu="")
        df = pd.DataFrame(json.loads(data))
        
        if "HATNO" in df.columns:
            for route in routes:
                route_stops = df[df["HATNO"] == route]
                if route_stops.empty:
                    continue
                coords = route_stops["KOORDINAT"].str.extract(r"POINT \(([0-9.]+) ([0-9.]+)\)")
                lons = pd.to_numeric(coords[0], errors="coerce")
                lats = pd.to_numeric(coords[1], errors="coerce")
                if not lats.isna().all() and not lons.isna().all():
                    route_coords.append((route, float(lats.mean()), float(lons.mean())))
                    
            if route_coords:
                return route_coords
                
    except Exception as e:
        print(f"[WARN] API coordinate fetch failed: {e}. Using fallback coordinates.")
    
    import random
    print("Generating fallback coordinates for Istanbul...")
    for route in routes:
        # Center of Istanbul with slight variation
        lat = 41.0082 + random.uniform(-0.1, 0.1)
        lon = 28.9784 + random.uniform(-0.1, 0.1)
        route_coords.append((route, lat, lon))
        
    return route_coords


def populate_database(agg: pd.DataFrame, coords: list):
    conn = get_connection()
    cursor = conn.cursor()

    # Populate demand_state
    print("Populating demand_state table...")
    # Clear existing
    cursor.execute("DELETE FROM demand_state")
    
    demand_records = [
        (row["route"], row["hour"], row["weekday"], row["route_desc"], row["busiest_station"], row["avg_passengers"], row["buses_on_route"])
        for _, row in agg.iterrows()
    ]
    cursor.executemany('''
        INSERT INTO demand_state (route, hour, weekday, route_desc, busiest_station, base_avg_passengers, buses_on_route)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', demand_records)

    # Populate routes
    if coords:
        print("Populating routes table...")
        cursor.execute("DELETE FROM routes")
        cursor.executemany('''
            INSERT INTO routes (route, lat, lon)
            VALUES (?, ?, ?)
        ''', coords)

    conn.commit()
    conn.close()
    print("Database population complete.")


def main():
    # Ensure tables exist
    init_db()

    print("Loading raw passenger data...")
    raw = load_passenger_data(RAW_PASSENGER_CSV)
    print(f"  Loaded {len(raw):,} rows")

    print("Aggregating to (route, hour, weekday)...")
    agg = aggregate_data(raw)
    print(f"  Aggregated to {len(agg):,} rows")

    unique_routes = agg["route"].unique().tolist()
    coords = fetch_route_coordinates(unique_routes)

    populate_database(agg, coords)


if __name__ == "__main__":
    main()

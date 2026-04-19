import sqlite3
import os

DB_PATH = "data/system.db"

def get_connection():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # Table for static route information (coordinates)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS routes (
            route TEXT PRIMARY KEY,
            lat REAL,
            lon REAL
        )
    ''')

    # Table for live demand state
    cursor.execute('DROP TABLE IF EXISTS demand_state')
    cursor.execute('''
        CREATE TABLE demand_state (
            route TEXT,
            hour INTEGER,
            weekday INTEGER,
            route_desc TEXT,
            busiest_station TEXT,
            base_avg_passengers REAL,
            buses_on_route INTEGER,
            signal_modifier REAL DEFAULT 0.0,
            PRIMARY KEY (route, hour, weekday)
        )
    ''')

    # Table for tracking active reroutes
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS active_reroutes (
            driver_id TEXT PRIMARY KEY,
            original_route TEXT,
            helping_route TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Table for driver signals
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS driver_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_id TEXT,
            route TEXT,
            signal_type TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")

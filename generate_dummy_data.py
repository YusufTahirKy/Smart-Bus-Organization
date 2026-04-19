import sqlite3
from datetime import datetime
from database import get_connection, init_db

def generate():
    # Ensure tables exist
    init_db()
    
    conn = get_connection()
    cursor = conn.cursor()
    
    now = datetime.now()
    hour = now.hour
    weekday = now.weekday()
    
    print(f"Generating dummy data for Hour: {hour}, Weekday: {weekday}")
    
    # Dummy routes
    routes = [
        ("34AS", 41.0, 28.9),
        ("500T", 41.05, 29.0),
        ("15F", 41.02, 29.02),
        ("KM23", 40.9, 29.2),
        ("11ÜS", 41.03, 29.01)
    ]
    
    # Insert routes
    cursor.execute("DELETE FROM routes")
    cursor.executemany("INSERT INTO routes (route, lat, lon) VALUES (?, ?, ?)", routes)
    
    # Insert demand state
    cursor.execute("DELETE FROM demand_state")
    
    states = [
        # route, hour, weekday, route_desc, busiest_station, base_avg, buses, modifier
        ("34AS", hour, weekday, "AVCILAR-SOGUTLUCESME", "MECIDIYEKOY", 120.0, 40, 0.0),
        ("500T", hour, weekday, "TUZLA-CEVIZLI BAG", "4.LEVENT", 85.0, 30, 0.0),
        ("15F", hour, weekday, "BEYKOZ-KADIKOY", "USKUDAR", 15.0, 10, 0.0),
        ("KM23", hour, weekday, "KARTAL METRO-KAVAKPINAR", "PENDIK", 4.0, 10, 0.0),
        ("11ÜS", hour, weekday, "SULTANBEYLI-USKUDAR", "UMRANIYE", 2.0, 8, 0.0)
    ]
    
    cursor.executemany('''
        INSERT INTO demand_state (route, hour, weekday, route_desc, busiest_station, base_avg_passengers, buses_on_route, signal_modifier)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', states)
    
    conn.commit()
    conn.close()
    print("Dummy data successfully inserted.")

if __name__ == "__main__":
    generate()

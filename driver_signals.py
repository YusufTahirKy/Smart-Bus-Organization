"""
Step 5: Driver Signal System
Collects driver signals (full/normal/empty) per route and stores them in SQLite.
- Signals are valid for a rolling window of 60 minutes.
- 2+ drivers must report "full" to confirm (+0.5 to score).
- 1+ driver reporting "empty" applies a penalty (-0.3 to score).
- Updates the signal_modifier in the demand_state table dynamically.
"""

import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from database import get_connection

# ── CONFIG ────────────────────────────────────────────────────────────────────
MIN_DRIVERS_CONFIRM = 2      
FULL_SCORE_BOOST    = 0.5    
EMPTY_SCORE_PENALTY = 0.3    
VALID_SIGNALS       = {"full", "normal", "empty", "kaza", "yol_calismasi", "yogun_trafik"}
WINDOW_MINUTES      = 60
# ─────────────────────────────────────────────────────────────────────────────


def submit_driver_signal(driver_id: str, route: str, signal: str = "normal"):
    """Insert a new driver signal into the database."""
    signal = signal.strip().lower()
    if signal not in VALID_SIGNALS:
        print(f"[ERROR] Invalid signal '{signal}'. Must be one of {VALID_SIGNALS}")
        return

    now = datetime.now().isoformat()
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO driver_signals (driver_id, route, signal_type, timestamp)
        VALUES (?, ?, ?, ?)
    ''', (driver_id, route, signal, now))
    conn.commit()
    conn.close()
    
    print(f"[SIGNAL] Driver {driver_id} on route '{route}' reported: {signal.upper()}")


def apply_active_signals(hour: int, weekday: int):
    """
    Calculate signal modifiers for the last WINDOW_MINUTES
    and update the demand_state table.
    """
    cutoff_time = (datetime.now() - timedelta(minutes=WINDOW_MINUTES)).isoformat()
    
    conn = get_connection()
    
    # Read valid signals
    query = """
        SELECT route, signal_type 
        FROM driver_signals 
        WHERE timestamp >= ?
    """
    df_signals = pd.read_sql_query(query, conn, params=(cutoff_time,))
    
    # Reset all modifiers to 0 first for this hour/weekday
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE demand_state 
        SET signal_modifier = 0.0
        WHERE hour = ? AND weekday = ?
    ''', (hour, weekday))
    
    if df_signals.empty:
        conn.commit()
        conn.close()
        return

    # Group by route and calculate modifiers
    updates = []
    for route, group in df_signals.groupby("route"):
        full_count = sum(group["signal_type"] == "full")
        empty_count = sum(group["signal_type"] == "empty")
        
        modifier = 0.0
        if full_count >= MIN_DRIVERS_CONFIRM:
            modifier += FULL_SCORE_BOOST
            print(f"[SIGNAL APPLIED] {route}: +{FULL_SCORE_BOOST} (confirmed full)")
            
        if empty_count >= 1:
            modifier -= EMPTY_SCORE_PENALTY
            print(f"[SIGNAL APPLIED] {route}: -{EMPTY_SCORE_PENALTY} (empty reported)")
            
        if modifier != 0.0:
            updates.append((modifier, route, hour, weekday))
            
    if updates:
        cursor.executemany('''
            UPDATE demand_state 
            SET signal_modifier = ?
            WHERE route = ? AND hour = ? AND weekday = ?
        ''', updates)
        
    conn.commit()
    conn.close()
    print("Signal modifiers updated in the database.")


def run_interactive():
    now     = datetime.now()
    hour    = now.hour
    weekday = now.weekday()

    print("\n── DRIVER SIGNAL INPUT ──────────────────────────────────")
    print("Enter driver signals. Press Enter with no route to finish.")
    print("Signal options: full | normal (default) | empty\n")

    while True:
        driver_id = input("Driver ID (or press Enter to finish): ").strip()
        if not driver_id:
            break
        route  = input("Route code: ").strip().upper()
        signal = input("Signal [full/normal/empty] (default=normal): ").strip().lower()
        if signal == "":
            signal = "normal"
        submit_driver_signal(driver_id, route, signal)

    print("\n── APPLYING SIGNALS ───────────────────")
    apply_active_signals(hour, weekday)


if __name__ == "__main__":
    run_interactive()

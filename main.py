"""
main.py — Single entry point for the Istanbul Bus Rerouting System.
Runs a polling loop every POLL_INTERVAL_MINUTES that:
  1. Applies active driver signals to the current demand state.
  2. Runs ML Regressor to predict demand for T+1 (next hour).
  3. Checks for recalls (demand resolved or end of day).
  4. Runs rerouting engine based on proactive predictions.
  5. Prints report.
"""

import time
import os
import sqlite3
from datetime import datetime, timedelta

from database import init_db
from driver_signals import apply_active_signals
from inference import DemandPredictor
from rerouting import check_recalls, find_reroutings, notify_recall, print_report

# ── CONFIG ────────────────────────────────────────────────────────────────────
POLL_INTERVAL_MINUTES = 15
END_OF_DAY_HOUR       = 23
# ─────────────────────────────────────────────────────────────────────────────

def run_cycle(predictor: DemandPredictor):
    now     = datetime.now()
    hour    = now.hour
    weekday = now.weekday()
    
    # Predict for T+1
    next_hour_dt = now + timedelta(hours=1)

    print(f"\n{'='*65}")
    print(f"  CYCLE — {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*65}")

    # Step 1 — Apply Driver Signals
    print("\n[1/4] Applying active driver signals...")
    apply_active_signals(hour, weekday)

    # Step 2 — Run predictor for T+1
    print("\n[2/4] Predicting future demand for T+1...")
    try:
        predictions_df = predictor.predict_all_routes(next_hour_dt)
        print(f"  Predicted demand for {len(predictions_df)} routes.")
    except Exception as e:
        print(f"  [ERROR] Prediction failed (model might not be trained): {e}")
        predictions_df = None

    # Step 3 — Check recalls
    print("\n[3/4] Checking for recalls...")
    recalls = check_recalls(hour=hour, weekday=weekday)
    if recalls:
        for recall in recalls:
            notify_recall(recall)
    else:
        print("  No recalls needed.")

    # Step 4 — Run rerouting engine
    print("\n[4/4] Running proactive rerouting engine...")
    actions = find_reroutings(hour=hour, weekday=weekday, predictions_df=predictions_df)
    print_report(actions)


def main():
    print("Istanbul Bus Rerouting System — Starting...")
    print("Initializing Database...")
    init_db()
    
    print("Loading ML Model...")
    try:
        predictor = DemandPredictor()
    except Exception as e:
        print(f"[WARN] Failed to load ML model: {e}")
        print("[WARN] System will run on current demand state without T+1 predictions.")
        print("[WARN] Please run train_model.py first to enable proactive routing.")
        predictor = None

    print(f"\nPolling every {POLL_INTERVAL_MINUTES} minutes. Press Ctrl+C to stop.\n")

    while True:
        try:
            if predictor:
                run_cycle(predictor)
            else:
                # Fallback if predictor fails (e.g. models not generated yet)
                # create a dummy predictor instance that will fail gracefully
                class DummyPredictor:
                    def predict_all_routes(self, dt):
                        raise RuntimeError("Model not available.")
                run_cycle(DummyPredictor())
                
        except Exception as e:
            print(f"[ERROR] Cycle failed: {e}")

        next_run = POLL_INTERVAL_MINUTES * 60
        print(f"\nNext cycle in {POLL_INTERVAL_MINUTES} minutes...")
        time.sleep(next_run)


if __name__ == "__main__":
    main()

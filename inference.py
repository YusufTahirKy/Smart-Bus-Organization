"""
Step 3: Real-Time Inference
Predicts future passenger demand for the next hour (T+1) using the trained regressor.
These predictions feed the rerouting engine to proactively move buses.
"""

import pandas as pd
import joblib
import os
from datetime import datetime, timedelta
from database import get_connection

# ── CONFIG ────────────────────────────────────────────────────────────────────
MODEL_PATH    = "models/route_regressor.pkl"
ENCODER_PATH  = "models/route_encoder.pkl"
# ─────────────────────────────────────────────────────────────────────────────


class DemandPredictor:
    def __init__(self):
        self.model   = joblib.load(MODEL_PATH)
        self.encoder = joblib.load(ENCODER_PATH)

    def _get_current_buses(self, route: str, hour: int, weekday: int) -> int:
        """Fetch current scheduled buses for the route/time from DB to use as feature."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT buses_on_route FROM demand_state 
            WHERE route=? AND hour=? AND weekday=?
        ''', (route, hour, weekday))
        row = cursor.fetchone()
        conn.close()
        
        return row["buses_on_route"] if row else 1

    def predict(self, route: str, target_dt: datetime) -> dict:
        """
        Predict avg_passengers for a specific route at a future target datetime.
        """
        hour    = target_dt.hour
        weekday = target_dt.weekday()

        try:
            route_encoded = self.encoder.transform([route])[0]
        except ValueError:
            raise ValueError(f"Route '{route}' was not seen during training.")

        buses = self._get_current_buses(route, hour, weekday)

        features = pd.DataFrame([{
            "route_encoded":  route_encoded,
            "hour":           hour,
            "weekday":        weekday,
            "buses_on_route": buses
        }])

        pred_passengers = float(self.model.predict(features)[0])
        pred_score = pred_passengers / buses if buses > 0 else 0

        return {
            "route":             route,
            "target_datetime":   target_dt.isoformat(),
            "pred_passengers":   round(pred_passengers, 1),
            "current_buses":     buses,
            "pred_demand_score": round(pred_score, 3)
        }

    def predict_all_routes(self, target_dt: datetime) -> pd.DataFrame:
        """
        Predict demand for all known routes for the target datetime.
        Returns a DataFrame with predictions.
        """
        conn = get_connection()
        routes_df = pd.read_sql_query("SELECT DISTINCT route FROM routes", conn)
        conn.close()
        
        results = []
        for route in routes_df["route"]:
            try:
                result = self.predict(route, target_dt)
                results.append(result)
            except Exception:
                continue

        return pd.DataFrame(results)


if __name__ == "__main__":
    try:
        predictor = DemandPredictor()
        now = datetime.now()
        next_hour = now + timedelta(hours=1)
        print(f"Predicting demand for next hour: {next_hour.strftime('%Y-%m-%d %H:%M')}")
        # Note: Need an actual route string that was in training data. 
        # result = predictor.predict("SOME_ROUTE", next_hour)
        # print(result)
    except Exception as e:
        print(f"Failed to load model: {e}")

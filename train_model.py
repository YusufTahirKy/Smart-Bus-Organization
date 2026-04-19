"""
Step 2: Model Training
Trains a Random Forest Regressor on the demand_state SQLite table
to predict avg_passengers based on route, hour, weekday, and buses.
"""

import pandas as pd
import sqlite3
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
import joblib
import os
from database import get_connection

# ── CONFIG ────────────────────────────────────────────────────────────────────
MODEL_PATH   = "models/route_regressor.pkl"
ENCODER_PATH = "models/route_encoder.pkl"

FEATURES = ["route_encoded", "hour", "weekday", "buses_on_route"]
TARGET   = "base_avg_passengers"
# ─────────────────────────────────────────────────────────────────────────────


def load_and_prepare():
    conn = get_connection()
    df = pd.read_sql_query("SELECT route, hour, weekday, buses_on_route, base_avg_passengers FROM demand_state", conn)
    conn.close()

    if df.empty:
        raise ValueError("demand_state table is empty. Please run data_aggregation.py first.")

    # Encode route ID (string → integer)
    le = LabelEncoder()
    df["route_encoded"] = le.fit_transform(df["route"].astype(str))

    X = df[FEATURES]
    y = df[TARGET]
    return X, y, le, df


def train(X, y):
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    model = RandomForestRegressor(
        n_estimators=100,
        max_depth=15,
        random_state=42,
        n_jobs=-1
    )

    print("Training Random Forest Regressor...")
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    
    print("\nRegression Metrics:")
    print(f"MSE: {mean_squared_error(y_test, y_pred):.2f}")
    print(f"MAE: {mean_absolute_error(y_test, y_pred):.2f}")
    print(f"R2 Score: {r2_score(y_test, y_pred):.2f}")

    # Feature importances
    importances = pd.Series(model.feature_importances_, index=FEATURES)
    print("\nFeature Importances:")
    print(importances.sort_values(ascending=False))

    return model


def save(model, encoder):
    os.makedirs("models", exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    joblib.dump(encoder, ENCODER_PATH)
    print(f"\nModel saved to: {MODEL_PATH}")
    print(f"Encoder saved to: {ENCODER_PATH}")


def main():
    X, y, le, df = load_and_prepare()
    model = train(X, y)
    save(model, le)


if __name__ == "__main__":
    main()

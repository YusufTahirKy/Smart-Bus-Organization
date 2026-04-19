"""
Step 2: Model Training
Trains a Random Forest classifier on the aggregated demand table
to predict route status: undercrowded / normal / overcrowded.
"""

import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import classification_report, confusion_matrix
import joblib
import os

# ── CONFIG ────────────────────────────────────────────────────────────────────
INPUT_PATH  = "data/aggregated_demand.csv"
MODEL_PATH  = "models/route_classifier.pkl"
ENCODER_PATH = "models/route_encoder.pkl"

FEATURES = ["route_encoded", "hour", "weekday", "avg_passengers",
            "buses_on_route", "demand_score"]
TARGET   = "label"
# ─────────────────────────────────────────────────────────────────────────────


def load_and_prepare(path: str):
    df = pd.read_csv(path)

    # Encode route ID (string → integer)
    le = LabelEncoder()
    df["route_encoded"] = le.fit_transform(df["route"].astype(str))

    X = df[FEATURES]
    y = df[TARGET]
    return X, y, le, df


def train(X, y):
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=10,
        class_weight="balanced",   # handles imbalanced label distribution
        random_state=42,
        n_jobs=-1
    )

    print("Training Random Forest...")
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    print("\nClassification Report:")
    print(classification_report(y_test, y_pred,
          target_names=["undercrowded", "normal", "overcrowded"]))

    print("Confusion Matrix:")
    print(confusion_matrix(y_test, y_pred))

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
    X, y, le, df = load_and_prepare(INPUT_PATH)
    model = train(X, y)
    save(model, le)


if __name__ == "__main__":
    main()

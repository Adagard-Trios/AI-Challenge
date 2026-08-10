"""
models/weather-prediction/src/components/predictor.py
Weather Prediction Inference Component
Generates next-day predictions for all 25 districts
"""
import os
import sys
import logging
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
import numpy as np
import pandas as pd
import joblib

sys.path.insert(0, str(Path(__file__).parent.parent))

from entity.config_entity import (
    PredictionConfig,
    SRI_LANKA_DISTRICTS,
    DISTRICT_TO_STATION,
    WEATHER_STATIONS
)

# TensorFlow for LSTM models
try:
    from tensorflow.keras.models import load_model
    TF_AVAILABLE = True
except ImportError:
    TF_AVAILABLE = False

logger = logging.getLogger("weather_prediction.predictor")


class WeatherPredictor:
    """
    Generates next-day weather predictions for all 25 Sri Lankan districts.
    
    Uses trained LSTM models for each weather station and maps to districts.
    Also integrates RiverNet data for flood predictions.
    """

    SEVERITY_LEVELS = ["normal", "advisory", "warning", "critical"]

    def __init__(self, config: Optional[PredictionConfig] = None):
        self.config = config or PredictionConfig()
        os.makedirs(self.config.predictions_dir, exist_ok=True)

        self.models_dir = str(
            Path(__file__).parent.parent.parent / "artifacts" / "models"
        )

        # Cache loaded models
        self._models = {}
        self._scalers = {}

    def _load_model(self, station_name: str):
        """Load model and scaler for a station."""
        if station_name in self._models:
            return self._models[station_name], self._scalers[station_name]

        model_path = os.path.join(self.models_dir, f"lstm_{station_name.lower()}.h5")
        scaler_path = os.path.join(self.models_dir, f"scalers_{station_name.lower()}.joblib")

        if not os.path.exists(model_path):
            logger.warning(f"[PREDICTOR] No model for {station_name}")
            return None, None

        # Load with compile=False to avoid Keras 2->3 mse serialization issues
        # Then recompile with standard metrics
        self._models[station_name] = load_model(model_path, compile=False)
        self._models[station_name].compile(optimizer='adam', loss='mse', metrics=['mae'])
        self._scalers[station_name] = joblib.load(scaler_path)

        return self._models[station_name], self._scalers[station_name]

    def classify_severity(
        self,
        temp_max: float,
        rainfall: float,
        flood_risk: float = 0.0
    ) -> str:
        """
        Classify weather severity based on predictions.
        
        Args:
            temp_max: Predicted maximum temperature
            rainfall: Predicted rainfall in mm
            flood_risk: Flood risk score (0-1)
            
        Returns:
            Severity level: normal/advisory/warning/critical
        """
        if flood_risk > 0.8 or rainfall > self.config.critical_rain_mm:
            return "critical"
        elif flood_risk > 0.5 or rainfall > self.config.warning_rain_mm:
            return "warning"
        elif rainfall > self.config.advisory_rain_mm or temp_max > self.config.advisory_temp_c:
            return "advisory"
        return "normal"

    def predict_station(
        self,
        station_name: str,
        recent_data: np.ndarray
    ) -> Dict[str, Any]:
        """
        Generate prediction for a single station.
        
        Args:
            station_name: Weather station name
            recent_data: Recent weather data (30 days x features)
            
        Returns:
            Prediction dictionary
        """
        model, scalers = self._load_model(station_name)

        if model is None:
            return {
                "status": "no_model",
                "station": station_name,
                "prediction": None
            }

        try:
            # Prepare input
            X = scalers["feature_scaler"].transform(recent_data)
            X = X.reshape(1, 30, -1)  # (batch, sequence, features)

            # Predict
            y_scaled = model.predict(X, verbose=0)
            y = scalers["target_scaler"].inverse_transform(y_scaled)

            temp_max = float(y[0, 0])
            temp_min = float(y[0, 1])
            rainfall = max(0, float(y[0, 2]))

            return {
                "status": "success",
                "station": station_name,
                "prediction": {
                    "temp_max_c": round(temp_max, 1),
                    "temp_min_c": round(temp_min, 1),
                    "rainfall_mm": round(rainfall, 1),
                    "rain_probability": min(1.0, rainfall / 10) if rainfall > 0.5 else 0.1,
                    "humidity_pct": 75,  # Default, can be enhanced
                }
            }
        except Exception as e:
            logger.error(f"[PREDICTOR] Prediction failed for {station_name}: {e}")
            return {
                "status": "error",
                "station": station_name,
                "error": str(e)
            }

    def predict_all_districts(
        self,
        weather_data: pd.DataFrame = None,
        rivernet_data: Dict = None
    ) -> Dict[str, Any]:
        """
        Generate predictions for all 25 districts.
        
        Args:
            weather_data: Recent weather data (for inference)
            rivernet_data: RiverNet flood data (optional)
            
        Returns:
            District predictions dictionary
        """
        prediction_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        predictions = {
            "prediction_date": prediction_date,
            "generated_at": datetime.now().isoformat(),
            "model_version": "lstm_v1",
            "districts": {}
        }

        # Group by station for efficiency
        station_predictions = {}

        for district in self.config.districts:
            station = self.config.district_to_station.get(district, "COLOMBO")

            if station not in station_predictions:
                # Get station prediction (use fallback data if no recent data)
                if weather_data is not None and station in weather_data.get("station_name", "").values:
                    station_df = weather_data[weather_data["station_name"] == station]
                    recent_data = self._prepare_recent_data(station_df)
                    station_predictions[station] = self.predict_station(station, recent_data)
                else:
                    # Use default/synthetic data for demo
                    station_predictions[station] = self._get_fallback_prediction(station, district)

            station_pred = station_predictions[station]

            # Calculate flood risk for this district
            flood_risk = 0.0
            if rivernet_data:
                flood_risk = self._calculate_flood_risk(district, rivernet_data)

            # Build district prediction
            if station_pred.get("status") == "success":
                pred = station_pred["prediction"]
                severity = self.classify_severity(
                    pred["temp_max_c"],
                    pred["rainfall_mm"],
                    flood_risk
                )

                predictions["districts"][district] = {
                    "temperature": {
                        "high_c": pred["temp_max_c"],
                        "low_c": pred["temp_min_c"]
                    },
                    "rainfall": {
                        "amount_mm": pred["rainfall_mm"],
                        "probability": pred["rain_probability"]
                    },
                    "flood_risk": round(flood_risk, 2),
                    "humidity_pct": pred.get("humidity_pct", 75),
                    "severity": severity,
                    "station_used": station
                }
            else:
                # Fallback prediction
                predictions["districts"][district] = self._get_fallback_prediction(station, district)

        return predictions

    def _prepare_recent_data(self, df: pd.DataFrame) -> np.ndarray:
        """Prepare recent data for LSTM input."""
        # Get last 30 days
        df = df.sort_values("date").tail(30)

        feature_cols = [
            "temp_mean", "temp_max", "temp_min",
            "humidity", "rainfall", "pressure",
            "wind_speed", "visibility"
        ]

        features = []
        for col in feature_cols:
            if col in df.columns:
                features.append(df[col].fillna(df[col].mean()).values)
            else:
                features.append(np.zeros(len(df)))

        # Add temporal features
        features.append(np.linspace(0, 1, len(df)))  # day_of_year proxy
        features.append(np.zeros(len(df)))  # month_sin
        features.append(np.ones(len(df)))  # month_cos

        return np.column_stack(features)

    def _get_fallback_prediction(self, station: str, district: str) -> Dict:
        """Generate climate-based fallback prediction."""
        # Climate normals for Sri Lanka (approximate)
        now = datetime.now()
        month = now.month

        # Monsoon seasons
        if month in [5, 6, 7, 8, 9]:  # Southwest monsoon
            is_wet = district in ["Colombo", "Gampaha", "Kalutara", "Galle", "Matara", "Ratnapura"]
        elif month in [10, 11, 12, 1, 2]:  # Northeast monsoon
            is_wet = district in ["Batticaloa", "Ampara", "Trincomalee", "Jaffna"]
        else:
            is_wet = False

        # Base temperatures
        if district in ["Nuwara Eliya", "Badulla"]:
            base_temp = 18  # Hill country
        elif district in ["Hambantota", "Batticaloa"]:
            base_temp = 32  # Dry zone
        else:
            base_temp = 28  # Coastal/wet zone

        rainfall = np.random.uniform(20, 80) if is_wet else np.random.uniform(0, 15)

        return {
            "temperature": {
                "high_c": round(base_temp + np.random.uniform(2, 5), 1),
                "low_c": round(base_temp - np.random.uniform(5, 8), 1)
            },
            "rainfall": {
                "amount_mm": round(rainfall, 1),
                "probability": min(0.9, rainfall / 50)
            },
            "flood_risk": 0.0,
            "humidity_pct": 75 if is_wet else 65,
            "severity": "normal",
            "station_used": station,
            "is_fallback": True
        }

    def _calculate_flood_risk(self, district: str, rivernet_data: Dict) -> float:
        """Calculate flood risk from RiverNet data."""
        # Map districts to rivers
        district_rivers = {
            "Colombo": ["kelaniya"],
            "Gampaha": ["kelaniya", "gampaha"],
            "Ratnapura": ["ratnapura"],
            "Hambantota": [],
            "Batticaloa": ["maduru_oya", "mundeni_aru"],
            "Galle": ["nilwala"],
            "Kurunegala": ["deduruoya"],
            # Add more mappings
        }

        rivers = district_rivers.get(district, [])
        if not rivers or not rivernet_data.get("rivers"):
            return 0.0

        max_risk = 0.0
        for river in rivernet_data["rivers"]:
            if river.get("location_key") in rivers:
                status = river.get("status", "unknown")
                if status == "danger":
                    max_risk = max(max_risk, 0.9)
                elif status == "warning":
                    max_risk = max(max_risk, 0.6)
                elif status == "rising":
                    max_risk = max(max_risk, 0.3)

        return max_risk

    def save_predictions(self, predictions: Dict) -> str:
        """Save predictions to JSON file."""
        date_str = predictions["prediction_date"].replace("-", "")
        output_path = os.path.join(
            self.config.predictions_dir,
            f"predictions_{date_str}.json"
        )

        with open(output_path, "w") as f:
            json.dump(predictions, f, indent=2)

        logger.info(f"[PREDICTOR] [OK] Saved predictions to {output_path}")
        return output_path

    def get_latest_predictions(self) -> Optional[Dict]:
        """Load the latest prediction file."""
        pred_dir = Path(self.config.predictions_dir)
        json_files = list(pred_dir.glob("predictions_*.json"))

        if not json_files:
            return None

        latest = max(json_files, key=lambda p: p.stat().st_mtime)

        with open(latest) as f:
            return json.load(f)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Test predictor with fallback
    predictor = WeatherPredictor()

    print("Generating predictions for all districts...")
    predictions = predictor.predict_all_districts()

    print(f"\nPredictions for {predictions['prediction_date']}:")
    for district, pred in list(predictions["districts"].items())[:5]:
        print(f"\n{district}:")
        print(f"  Temp: {pred['temperature']['low_c']}° - {pred['temperature']['high_c']}°C")
        print(f"  Rain: {pred['rainfall']['amount_mm']}mm ({pred['rainfall']['probability']*100:.0f}%)")
        print(f"  Severity: {pred['severity']}")

    # Save
    output_path = predictor.save_predictions(predictions)
    print(f"\n[OK] Saved to: {output_path}")

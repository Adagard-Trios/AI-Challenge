"""
models/currency-volatility-prediction/src/components/predictor.py
Currency Prediction Inference Component
Generates next-day USD/LKR predictions
"""
import os
import sys
import logging
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Any
import numpy as np
import pandas as pd
import joblib

sys.path.insert(0, str(Path(__file__).parent.parent))

from entity.config_entity import PredictionConfig

# TensorFlow for model loading
try:
    from tensorflow.keras.models import load_model
    TF_AVAILABLE = True
except ImportError:
    TF_AVAILABLE = False

logger = logging.getLogger("currency_prediction.predictor")


class CurrencyPredictor:
    """
    Generates next-day USD/LKR predictions.
    
    Uses trained GRU model to predict:
    - Next day closing rate
    - Expected change percentage
    - Trend direction
    - Volatility classification
    """

    def __init__(self, config: Optional[PredictionConfig] = None):
        self.config = config or PredictionConfig()
        os.makedirs(self.config.predictions_dir, exist_ok=True)

        self.models_dir = str(
            Path(__file__).parent.parent.parent / "artifacts" / "models"
        )

        self._model = None
        self._scalers = None
        self._feature_names = None

    def _load_model(self):
        """Load trained GRU model and scalers."""
        if self._model is not None:
            return

        model_path = os.path.join(self.models_dir, "gru_usd_lkr.h5")
        scaler_path = os.path.join(self.models_dir, "scalers_usd_lkr.joblib")

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"No trained model found at {model_path}")

        # Load with compile=False to avoid Keras 2->3 mse serialization issues
        # Then recompile with standard metrics
        self._model = load_model(model_path, compile=False)
        self._model.compile(optimizer='adam', loss='mse', metrics=['mae'])
        
        scalers = joblib.load(scaler_path)

        self._scalers = {
            "feature": scalers["feature_scaler"],
            "target": scalers["target_scaler"]
        }
        self._feature_names = scalers["feature_names"]

        logger.info(f"[PREDICTOR] Model loaded: {len(self._feature_names)} features")

    def classify_volatility(self, change_pct: float) -> str:
        """
        Classify volatility level based on predicted change.
        
        Args:
            change_pct: Expected percentage change
            
        Returns:
            Volatility level: low/medium/high
        """
        abs_change = abs(change_pct)

        if abs_change > self.config.high_volatility_pct:
            return "high"
        elif abs_change > self.config.medium_volatility_pct:
            return "medium"
        return "low"

    def predict(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Generate next-day USD/LKR prediction.
        
        Args:
            df: DataFrame with recent currency data (must have last 30+ days)
            
        Returns:
            Prediction dictionary
        """
        self._load_model()

        # Get required sequence length
        config_path = os.path.join(self.models_dir, "training_config.json")
        with open(config_path) as f:
            train_config = json.load(f)

        sequence_length = train_config["sequence_length"]

        # Extract features
        available_features = [f for f in self._feature_names if f in df.columns]

        if len(available_features) < len(self._feature_names):
            missing = set(self._feature_names) - set(available_features)
            logger.warning(f"[PREDICTOR] Missing features: {missing}")

        # Get last N days
        recent = df[available_features].tail(sequence_length).values

        if len(recent) < sequence_length:
            raise ValueError(f"Need {sequence_length} days of data, got {len(recent)}")

        # Scale and predict
        X = self._scalers["feature"].transform(recent)
        X = X.reshape(1, sequence_length, -1)

        y_scaled = self._model.predict(X, verbose=0)
        y = self._scalers["target"].inverse_transform(y_scaled)

        # Calculate prediction details
        current_rate = df["close"].iloc[-1]
        predicted_rate = float(y[0, 0])
        change = predicted_rate - current_rate
        change_pct = (change / current_rate) * 100

        # Get recent volatility for context
        recent_volatility = df["volatility_20"].iloc[-1] if "volatility_20" in df.columns else 0

        prediction = {
            "prediction_date": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"),
            "generated_at": datetime.now().isoformat(),
            "model_version": "gru_v1",

            # Rate predictions
            "current_rate": round(current_rate, 2),
            "predicted_rate": round(predicted_rate, 2),
            "expected_change": round(change, 2),
            "expected_change_pct": round(change_pct, 3),

            # Direction and confidence
            "direction": "strengthening" if change < 0 else "weakening",
            "direction_emoji": "📈" if change < 0 else "📉",

            # Volatility
            "volatility_class": self.classify_volatility(change_pct),
            "recent_volatility_20d": round(recent_volatility * 100, 2) if recent_volatility else None,

            # Historical context
            "rate_7d_ago": round(df["close"].iloc[-7], 2) if len(df) >= 7 else None,
            "rate_30d_ago": round(df["close"].iloc[-30], 2) if len(df) >= 30 else None,
            "weekly_trend": round((current_rate - df["close"].iloc[-7]) / df["close"].iloc[-7] * 100, 2) if len(df) >= 7 else None,
            "monthly_trend": round((current_rate - df["close"].iloc[-30]) / df["close"].iloc[-30] * 100, 2) if len(df) >= 30 else None
        }

        return prediction

    def generate_fallback_prediction(self, current_rate: float = 298.0) -> Dict[str, Any]:
        """
        Generate fallback prediction when model not available.
        Uses simple trend-based estimation.
        """
        # Simple random walk with slight depreciation bias (historical trend)
        change_pct = np.random.normal(0.05, 0.3)  # Slight LKR weakening bias
        predicted_rate = current_rate * (1 + change_pct / 100)

        return {
            "prediction_date": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"),
            "generated_at": datetime.now().isoformat(),
            "model_version": "fallback",
            "is_fallback": True,

            "current_rate": round(current_rate, 2),
            "predicted_rate": round(predicted_rate, 2),
            "expected_change": round(predicted_rate - current_rate, 2),
            "expected_change_pct": round(change_pct, 3),

            "direction": "strengthening" if change_pct < 0 else "weakening",
            "direction_emoji": "📈" if change_pct < 0 else "📉",
            "volatility_class": "low",

            "note": "Using fallback model - train GRU for accurate predictions"
        }

    def save_prediction(self, prediction: Dict) -> str:
        """Save prediction to JSON file."""
        date_str = prediction["prediction_date"].replace("-", "")
        output_path = os.path.join(
            self.config.predictions_dir,
            f"currency_prediction_{date_str}.json"
        )

        with open(output_path, "w") as f:
            json.dump(prediction, f, indent=2)

        logger.info(f"[PREDICTOR] ✓ Saved prediction to {output_path}")
        return output_path

    def get_latest_prediction(self) -> Optional[Dict]:
        """Load the latest prediction file or generate new one using model."""
        # First try to generate real prediction with trained model
        try:
            prediction = self.generate_real_prediction()
            if prediction:
                self.save_prediction(prediction)
                return prediction
        except Exception as e:
            logger.warning(f"[PREDICTOR] Could not generate real prediction: {e}")

        # Fall back to saved predictions
        pred_dir = Path(self.config.predictions_dir)
        json_files = list(pred_dir.glob("currency_prediction_*.json"))

        if json_files:
            latest = max(json_files, key=lambda p: p.stat().st_mtime)
            with open(latest) as f:
                return json.load(f)

        return None

    def generate_real_prediction(self) -> Optional[Dict]:
        """Generate prediction using trained model and latest data."""
        if not TF_AVAILABLE:
            logger.warning("[PREDICTOR] TensorFlow not available")
            return None

        # Find latest data file
        data_dir = Path(__file__).parent.parent.parent / "artifacts" / "data"
        csv_files = list(data_dir.glob("currency_data_*.csv"))

        if not csv_files:
            logger.warning("[PREDICTOR] No currency data files found")
            return None

        latest_data = max(csv_files, key=lambda p: p.stat().st_mtime)
        logger.info(f"[PREDICTOR] Loading data from {latest_data}")

        # Load the data
        df = pd.read_csv(latest_data)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date")

        if len(df) < 30:
            logger.warning(f"[PREDICTOR] Not enough data: {len(df)} rows")
            return None

        # Use the predict method with the data
        try:
            prediction = self.predict(df)
            prediction["is_fallback"] = False
            return prediction
        except Exception as e:
            logger.error(f"[PREDICTOR] Model prediction failed: {e}")
            return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    predictor = CurrencyPredictor()

    # Test with fallback
    print("Testing fallback prediction...")
    prediction = predictor.generate_fallback_prediction(current_rate=298.50)

    print(f"\nPrediction for {prediction['prediction_date']}:")
    print(f"  Current rate: {prediction['current_rate']} LKR/USD")
    print(f"  Predicted: {prediction['predicted_rate']} LKR/USD")
    print(f"  Change: {prediction['expected_change_pct']:+.2f}%")
    print(f"  Direction: {prediction['direction_emoji']} {prediction['direction']}")

    output_path = predictor.save_prediction(prediction)
    print(f"\n✓ Saved to: {output_path}")

"""
models/weather-prediction/src/components/model_trainer.py
LSTM-based Weather Prediction Model Trainer
"""
import os
import sys

# Fix Windows console encoding issue with MLflow emoji output
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import logging
import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
import json
import joblib

# Load environment variables from root .env
try:
    from dotenv import load_dotenv
    # Navigate to project root: models/weather-prediction/src/components -> root
    root_env = Path(__file__).parent.parent.parent.parent.parent / ".env"
    if root_env.exists():
        load_dotenv(root_env)
        print(f"[MLflow] Loaded environment from {root_env}")
except ImportError:
    pass

# TensorFlow/Keras for LSTM
try:
    import tensorflow as tf
    from tensorflow.keras.models import Sequential, load_model
    from tensorflow.keras.layers import LSTM, Dense, Dropout, BatchNormalization
    from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint, ReduceLROnPlateau
    from tensorflow.keras.optimizers import Adam
    from sklearn.preprocessing import MinMaxScaler
    TF_AVAILABLE = True
except ImportError:
    TF_AVAILABLE = False
    print("[WARNING] TensorFlow not available. Install with: pip install tensorflow")

# MLflow for tracking
try:
    import mlflow
    import mlflow.keras
    MLFLOW_AVAILABLE = True
except ImportError:
    MLFLOW_AVAILABLE = False


def setup_mlflow():
    """Configure MLflow with DagsHub credentials from environment."""
    if not MLFLOW_AVAILABLE:
        return False

    tracking_uri = os.getenv("MLFLOW_TRACKING_URI")
    username = os.getenv("MLFLOW_TRACKING_USERNAME")
    password = os.getenv("MLFLOW_TRACKING_PASSWORD")

    if not tracking_uri:
        print("[MLflow] No MLFLOW_TRACKING_URI set, using local tracking")
        return False

    # Set authentication for DagsHub
    if username and password:
        os.environ["MLFLOW_TRACKING_USERNAME"] = username
        os.environ["MLFLOW_TRACKING_PASSWORD"] = password
        print(f"[MLflow] [OK] Configured with DagsHub credentials for {username}")

    mlflow.set_tracking_uri(tracking_uri)
    print(f"[MLflow] [OK] Tracking URI: {tracking_uri}")
    return True


logger = logging.getLogger("weather_prediction.model_trainer")



class WeatherLSTMTrainer:
    """
    LSTM-based model trainer for weather prediction.
    
    Predicts:
    - Temperature (high/low)
    - Rainfall (probability + amount)
    - Severity classification
    """

    FEATURE_COLUMNS = [
        "temp_mean", "temp_max", "temp_min",
        "humidity", "rainfall", "pressure",
        "wind_speed", "visibility"
    ]

    TARGET_COLUMNS = [
        "temp_max", "temp_min", "rainfall"
    ]

    def __init__(
        self,
        sequence_length: int = 30,
        lstm_units: List[int] = None,
        dropout_rate: float = 0.2,
        models_dir: str = None
    ):
        if not TF_AVAILABLE:
            raise RuntimeError("TensorFlow is required for LSTM training")

        self.sequence_length = sequence_length
        self.lstm_units = lstm_units or [64, 32]
        self.dropout_rate = dropout_rate
        self.models_dir = models_dir or str(
            Path(__file__).parent.parent.parent / "artifacts" / "models"
        )

        os.makedirs(self.models_dir, exist_ok=True)

        # Scalers for normalization
        self.feature_scaler = MinMaxScaler()
        self.target_scaler = MinMaxScaler()

        # Models
        self.model = None
        self.rain_classifier = None

    def prepare_data(
        self,
        df: pd.DataFrame,
        station_name: str
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Prepare data for LSTM training.
        
        Args:
            df: DataFrame with weather data
            station_name: Station to filter for
            
        Returns:
            X_train, X_test, y_train, y_test
        """
        # Filter for station
        station_df = df[df["station_name"] == station_name].copy()

        if len(station_df) < self.sequence_length + 10:
            raise ValueError(f"Not enough data for {station_name}: {len(station_df)} records")

        # Sort by date
        station_df = station_df.sort_values("date").reset_index(drop=True)

        # Fill missing values with interpolation
        for col in self.FEATURE_COLUMNS:
            if col in station_df.columns:
                station_df[col] = station_df[col].interpolate(method="linear")
                station_df[col] = station_df[col].fillna(station_df[col].mean())

        # Add temporal features
        station_df["day_of_year"] = pd.to_datetime(station_df["date"]).dt.dayofyear / 365.0
        station_df["month_sin"] = np.sin(2 * np.pi * station_df["month"] / 12)
        station_df["month_cos"] = np.cos(2 * np.pi * station_df["month"] / 12)

        # Prepare feature matrix
        features = []
        for col in self.FEATURE_COLUMNS:
            if col in station_df.columns:
                features.append(station_df[col].values)
            else:
                features.append(np.zeros(len(station_df)))

        # Add temporal features
        features.append(station_df["day_of_year"].values)
        features.append(station_df["month_sin"].values)
        features.append(station_df["month_cos"].values)

        X = np.column_stack(features)

        # Prepare targets (next day prediction)
        targets = []
        for col in self.TARGET_COLUMNS:
            if col in station_df.columns:
                targets.append(station_df[col].values)
            else:
                targets.append(np.zeros(len(station_df)))

        y = np.column_stack(targets)

        # Normalize
        X_scaled = self.feature_scaler.fit_transform(X)
        y_scaled = self.target_scaler.fit_transform(y)

        # Create sequences for LSTM
        X_seq, y_seq = [], []

        for i in range(len(X_scaled) - self.sequence_length - 1):
            X_seq.append(X_scaled[i:i + self.sequence_length])
            y_seq.append(y_scaled[i + self.sequence_length])  # Next day target

        X_seq = np.array(X_seq)
        y_seq = np.array(y_seq)

        # Train/test split (80/20)
        split_idx = int(len(X_seq) * 0.8)

        X_train, X_test = X_seq[:split_idx], X_seq[split_idx:]
        y_train, y_test = y_seq[:split_idx], y_seq[split_idx:]

        logger.info(f"[LSTM] Data prepared for {station_name}:")
        logger.info(f"  X_train: {X_train.shape}, y_train: {y_train.shape}")
        logger.info(f"  X_test: {X_test.shape}, y_test: {y_test.shape}")

        return X_train, X_test, y_train, y_test

    def build_model(self, input_shape: Tuple[int, int]) -> Sequential:
        """
        Build the LSTM model architecture.
        
        Args:
            input_shape: (sequence_length, num_features)
            
        Returns:
            Compiled Keras model
        """
        model = Sequential([
            # First LSTM layer
            LSTM(
                self.lstm_units[0],
                return_sequences=True,
                input_shape=input_shape
            ),
            BatchNormalization(),
            Dropout(self.dropout_rate),

            # Second LSTM layer
            LSTM(self.lstm_units[1], return_sequences=False),
            BatchNormalization(),
            Dropout(self.dropout_rate),

            # Dense layers
            Dense(32, activation="relu"),
            Dense(16, activation="relu"),

            # Output layer (temp_max, temp_min, rainfall)
            Dense(len(self.TARGET_COLUMNS), activation="linear")
        ])

        model.compile(
            optimizer=Adam(learning_rate=0.001),
            loss="mse",
            metrics=["mae"]
        )

        logger.info(f"[LSTM] Model built: {model.count_params()} parameters")
        return model

    def train(
        self,
        df: pd.DataFrame,
        station_name: str,
        epochs: int = 100,
        batch_size: int = 32,
        use_mlflow: bool = True
    ) -> Dict[str, Any]:
        """
        Train the LSTM model for a specific station.
        
        Args:
            df: DataFrame with weather data
            station_name: Station to train for
            epochs: Training epochs
            batch_size: Batch size
            use_mlflow: Whether to log to MLflow
            
        Returns:
            Training results and metrics
        """
        logger.info(f"[LSTM] Training model for {station_name}...")

        # Prepare data
        X_train, X_test, y_train, y_test = self.prepare_data(df, station_name)

        # Build model
        input_shape = (X_train.shape[1], X_train.shape[2])
        self.model = self.build_model(input_shape)

        # Callbacks
        callbacks = [
            EarlyStopping(
                monitor="val_loss",
                patience=15,
                restore_best_weights=True
            ),
            ReduceLROnPlateau(
                monitor="val_loss",
                factor=0.5,
                patience=5,
                min_lr=1e-6
            )
        ]

        # MLflow tracking
        if use_mlflow and MLFLOW_AVAILABLE:
            # Setup MLflow with DagsHub credentials from .env
            setup_mlflow()
            mlflow.set_experiment("weather_prediction_lstm")

            with mlflow.start_run(run_name=f"lstm_{station_name}"):
                # Log parameters
                mlflow.log_params({
                    "station": station_name,
                    "sequence_length": self.sequence_length,
                    "lstm_units": str(self.lstm_units),
                    "dropout_rate": self.dropout_rate,
                    "epochs": epochs,
                    "batch_size": batch_size
                })

                # Train
                history = self.model.fit(
                    X_train, y_train,
                    validation_data=(X_test, y_test),
                    epochs=epochs,
                    batch_size=batch_size,
                    callbacks=callbacks,
                    verbose=1
                )

                # Evaluate
                test_loss, test_mae = self.model.evaluate(X_test, y_test, verbose=0)

                # Log metrics
                mlflow.log_metrics({
                    "test_loss": test_loss,
                    "test_mae": test_mae,
                    "best_val_loss": min(history.history["val_loss"])
                })

                # Log model
                mlflow.keras.log_model(self.model, "model")
        else:
            # Train without MLflow
            history = self.model.fit(
                X_train, y_train,
                validation_data=(X_test, y_test),
                epochs=epochs,
                batch_size=batch_size,
                callbacks=callbacks,
                verbose=1
            )
            test_loss, test_mae = self.model.evaluate(X_test, y_test, verbose=0)

        # Save model locally
        model_path = os.path.join(self.models_dir, f"lstm_{station_name.lower()}.h5")
        self.model.save(model_path)

        # Save scalers
        scaler_path = os.path.join(self.models_dir, f"scalers_{station_name.lower()}.joblib")
        joblib.dump({
            "feature_scaler": self.feature_scaler,
            "target_scaler": self.target_scaler
        }, scaler_path)

        logger.info(f"[LSTM] [OK] Model saved to {model_path}")

        return {
            "station": station_name,
            "test_loss": float(test_loss),
            "test_mae": float(test_mae),
            "model_path": model_path,
            "scaler_path": scaler_path,
            "epochs_trained": len(history.history["loss"])
        }

    def predict(
        self,
        recent_data: np.ndarray,
        station_name: str
    ) -> Dict[str, float]:
        """
        Make predictions for the next day.
        
        Args:
            recent_data: Array of shape (sequence_length, num_features)
            station_name: Station for loading correct model/scalers
            
        Returns:
            Predicted weather values
        """
        # Load model and scalers if not in memory
        model_path = os.path.join(self.models_dir, f"lstm_{station_name.lower()}.h5")
        scaler_path = os.path.join(self.models_dir, f"scalers_{station_name.lower()}.joblib")

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"No trained model for {station_name}")

        model = load_model(model_path)
        scalers = joblib.load(scaler_path)

        # Prepare input
        X = scalers["feature_scaler"].transform(recent_data)
        X = X.reshape(1, self.sequence_length, -1)

        # Predict
        y_scaled = model.predict(X, verbose=0)
        y = scalers["target_scaler"].inverse_transform(y_scaled)

        return {
            "temp_max": float(y[0, 0]),
            "temp_min": float(y[0, 1]),
            "rainfall": max(0, float(y[0, 2])),
            "rain_probability": 1.0 if y[0, 2] > 0.5 else 0.0
        }


if __name__ == "__main__":
    # Test model trainer
    logging.basicConfig(level=logging.INFO)

    print("WeatherLSTMTrainer initialized successfully")
    print(f"TensorFlow available: {TF_AVAILABLE}")
    print(f"MLflow available: {MLFLOW_AVAILABLE}")

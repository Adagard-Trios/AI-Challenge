"""
models/currency-volatility-prediction/src/components/model_trainer.py
GRU-based Currency Prediction Model Trainer
Optimized for 8GB RAM laptops without GPU
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
    root_env = Path(__file__).parent.parent.parent.parent.parent / ".env"
    if root_env.exists():
        load_dotenv(root_env)
        print(f"[MLflow] Loaded environment from {root_env}")
except ImportError:
    pass

# TensorFlow/Keras for GRU
try:
    import tensorflow as tf
    from tensorflow.keras.models import Sequential, load_model
    from tensorflow.keras.layers import GRU, Dense, Dropout, BatchNormalization, Input
    from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau, ModelCheckpoint
    from tensorflow.keras.optimizers import Adam
    from sklearn.preprocessing import MinMaxScaler, StandardScaler

    # Memory optimization for 8GB RAM
    gpus = tf.config.list_physical_devices('GPU')
    if gpus:
        for gpu in gpus:
            tf.config.experimental.set_memory_growth(gpu, True)

    # Limit TensorFlow memory usage
    tf.config.set_soft_device_placement(True)

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

sys.path.insert(0, str(Path(__file__).parent.parent))

from entity.config_entity import ModelTrainerConfig

logger = logging.getLogger("currency_prediction.model_trainer")


def setup_mlflow():
    """Configure MLflow with DagsHub credentials from environment."""
    if not MLFLOW_AVAILABLE:
        return False

    tracking_uri = os.getenv("MLFLOW_TRACKING_URI")
    username = os.getenv("MLFLOW_TRACKING_USERNAME")
    password = os.getenv("MLFLOW_TRACKING_PASSWORD")

    if not tracking_uri:
        logger.info("[MLflow] No MLFLOW_TRACKING_URI set, using local tracking")
        return False

    if username and password:
        os.environ["MLFLOW_TRACKING_USERNAME"] = username
        os.environ["MLFLOW_TRACKING_PASSWORD"] = password
        logger.info(f"[MLflow] ✓ Configured with DagsHub credentials for {username}")

    mlflow.set_tracking_uri(tracking_uri)
    logger.info(f"[MLflow] ✓ Tracking URI: {tracking_uri}")
    return True


class CurrencyGRUTrainer:
    """
    GRU-based model trainer for USD/LKR currency prediction.
    
    Architecture optimized for:
    - 8GB RAM laptops
    - No GPU required
    - Fast training (5-10 minutes)
    
    Predicts:
    - Next day closing rate
    - Daily return direction
    """

    # Features to use for training (must match data_ingestion output)
    FEATURE_COLUMNS = [
        # Price features
        "close", "daily_return", "daily_range",
        # Moving averages
        "sma_5", "sma_10", "sma_20", "ema_5", "ema_10",
        # Volatility
        "volatility_5", "volatility_20",
        # Momentum
        "momentum_5", "momentum_10", "rsi_14",
        # MACD
        "macd", "macd_signal",
        # Bollinger
        "bb_position",
        # Temporal
        "day_sin", "day_cos", "month_sin", "month_cos"
    ]

    # Economic indicators (added if available)
    INDICATOR_FEATURES = [
        "cse_index_close", "gold_close", "oil_close",
        "usd_index_close", "india_inr_close"
    ]

    def __init__(self, config: Optional[ModelTrainerConfig] = None):
        if not TF_AVAILABLE:
            raise RuntimeError("TensorFlow is required for GRU training")

        self.config = config or ModelTrainerConfig()
        os.makedirs(self.config.models_dir, exist_ok=True)

        self.sequence_length = self.config.sequence_length
        self.gru_units = self.config.gru_units

        # Scalers
        self.feature_scaler = StandardScaler()
        self.target_scaler = MinMaxScaler()

        self.model = None

    def prepare_data(
        self,
        df: pd.DataFrame
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Prepare data for GRU training.
        
        Args:
            df: DataFrame with currency data
            
        Returns:
            X_train, X_test, y_train, y_test
        """
        # Identify available features
        available_features = []

        for col in self.FEATURE_COLUMNS:
            if col in df.columns:
                available_features.append(col)

        for col in self.INDICATOR_FEATURES:
            if col in df.columns:
                available_features.append(col)

        logger.info(f"[GRU] Using {len(available_features)} features")

        # Extract features and target
        feature_data = df[available_features].values
        target_data = df[["close"]].values

        # Scale features
        feature_scaled = self.feature_scaler.fit_transform(feature_data)
        target_scaled = self.target_scaler.fit_transform(target_data)

        # Create sequences
        X, y = [], []

        for i in range(len(feature_scaled) - self.sequence_length):
            X.append(feature_scaled[i:i + self.sequence_length])
            y.append(target_scaled[i + self.sequence_length])

        X = np.array(X)
        y = np.array(y)

        # Train/test split (80/20, chronological)
        split_idx = int(len(X) * 0.8)

        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]

        logger.info("[GRU] Data prepared:")
        logger.info(f"  X_train: {X_train.shape}, y_train: {y_train.shape}")
        logger.info(f"  X_test: {X_test.shape}, y_test: {y_test.shape}")

        # Store feature names for later
        self.feature_names = available_features

        return X_train, X_test, y_train, y_test

    def build_model(self, input_shape: Tuple[int, int]) -> Sequential:
        """
        Build the GRU model architecture.
        
        GRU advantages over LSTM:
        - Fewer parameters (faster training)
        - Often performs equally well
        - Better for smaller datasets
        
        Args:
            input_shape: (sequence_length, num_features)
            
        Returns:
            Compiled Keras model
        """
        model = Sequential([
            Input(shape=input_shape),

            # First GRU layer
            GRU(
                self.gru_units[0],
                return_sequences=True,
                recurrent_dropout=0.1  # Regularization
            ),
            BatchNormalization(),
            Dropout(self.config.dropout_rate),

            # Second GRU layer
            GRU(
                self.gru_units[1],
                return_sequences=False
            ),
            BatchNormalization(),
            Dropout(self.config.dropout_rate),

            # Dense layers
            Dense(16, activation="relu"),
            Dense(8, activation="relu"),

            # Output: next day closing rate
            Dense(1, activation="linear")
        ])

        model.compile(
            optimizer=Adam(learning_rate=self.config.initial_lr),
            loss="mse",
            metrics=["mae", "mape"]
        )

        logger.info(f"[GRU] Model built: {model.count_params()} parameters")
        model.summary(print_fn=logger.info)

        return model

    def train(
        self,
        df: pd.DataFrame,
        use_mlflow: bool = True
    ) -> Dict[str, Any]:
        """
        Train the GRU model for currency prediction.
        
        Args:
            df: DataFrame with prepared currency data
            use_mlflow: Whether to log to MLflow
            
        Returns:
            Training results and metrics
        """
        logger.info("[GRU] Starting training...")

        # Prepare data
        X_train, X_test, y_train, y_test = self.prepare_data(df)

        # Build model
        input_shape = (X_train.shape[1], X_train.shape[2])
        self.model = self.build_model(input_shape)

        # Callbacks
        callbacks = [
            EarlyStopping(
                monitor="val_loss",
                patience=self.config.early_stopping_patience,
                restore_best_weights=True,
                verbose=1
            ),
            ReduceLROnPlateau(
                monitor="val_loss",
                factor=self.config.lr_decay_factor,
                patience=self.config.lr_patience,
                min_lr=1e-6,
                verbose=1
            )
        ]

        # MLflow tracking
        mlflow_active = False
        if use_mlflow and MLFLOW_AVAILABLE:
            mlflow_active = setup_mlflow()
            if mlflow_active:
                mlflow.set_experiment(self.config.experiment_name)

        run_context = mlflow.start_run(run_name=f"gru_usd_lkr_{datetime.now().strftime('%Y%m%d')}") if mlflow_active else None

        try:
            if mlflow_active:
                run_context.__enter__()

                # Log parameters
                mlflow.log_params({
                    "sequence_length": self.sequence_length,
                    "gru_units": str(self.gru_units),
                    "dropout_rate": self.config.dropout_rate,
                    "epochs": self.config.epochs,
                    "batch_size": self.config.batch_size,
                    "num_features": len(self.feature_names),
                    "train_samples": len(X_train),
                    "test_samples": len(X_test)
                })

            # Train
            history = self.model.fit(
                X_train, y_train,
                validation_data=(X_test, y_test),
                epochs=self.config.epochs,
                batch_size=self.config.batch_size,
                callbacks=callbacks,
                verbose=1
            )

            # Evaluate
            test_loss, test_mae, test_mape = self.model.evaluate(X_test, y_test, verbose=0)

            # Make predictions for analysis
            y_pred_scaled = self.model.predict(X_test, verbose=0)
            y_pred = self.target_scaler.inverse_transform(y_pred_scaled)
            y_actual = self.target_scaler.inverse_transform(y_test)

            # Calculate additional metrics
            rmse = np.sqrt(np.mean((y_pred - y_actual) ** 2))

            # Direction accuracy (predicting up/down correctly)
            actual_direction = np.sign(np.diff(y_actual.flatten()))
            pred_direction = np.sign(y_pred[1:].flatten() - y_actual[:-1].flatten())
            direction_accuracy = np.mean(actual_direction == pred_direction)

            results = {
                "test_loss": float(test_loss),
                "test_mae": float(test_mae),
                "test_mape": float(test_mape),
                "rmse": float(rmse),
                "direction_accuracy": float(direction_accuracy),
                "epochs_trained": len(history.history["loss"]),
                "final_lr": float(self.model.optimizer.learning_rate.numpy())
            }

            if mlflow_active:
                mlflow.log_metrics(results)
                mlflow.keras.log_model(self.model, "model")

            logger.info("[GRU] Training complete!")
            logger.info(f"  MAE: {test_mae:.4f} LKR")
            logger.info(f"  RMSE: {rmse:.4f} LKR")
            logger.info(f"  Direction Accuracy: {direction_accuracy*100:.1f}%")

        finally:
            if mlflow_active and run_context:
                run_context.__exit__(None, None, None)

        # Save model locally
        model_path = os.path.join(self.config.models_dir, "gru_usd_lkr.h5")
        self.model.save(model_path)

        # Save scalers
        scaler_path = os.path.join(self.config.models_dir, "scalers_usd_lkr.joblib")
        joblib.dump({
            "feature_scaler": self.feature_scaler,
            "target_scaler": self.target_scaler,
            "feature_names": self.feature_names
        }, scaler_path)

        # Save training config
        config_path = os.path.join(self.config.models_dir, "training_config.json")
        with open(config_path, "w") as f:
            json.dump({
                "sequence_length": self.sequence_length,
                "gru_units": self.gru_units,
                "feature_names": self.feature_names,
                "trained_at": datetime.now().isoformat()
            }, f)

        logger.info(f"[GRU] ✓ Model saved to {model_path}")

        results["model_path"] = model_path
        results["scaler_path"] = scaler_path

        return results

    def predict(self, recent_data: np.ndarray) -> Dict[str, float]:
        """
        Predict next day's USD/LKR rate.
        
        Args:
            recent_data: Last 30 days of data (30 x num_features)
            
        Returns:
            Prediction dictionary
        """
        if self.model is None:
            model_path = os.path.join(self.config.models_dir, "gru_usd_lkr.h5")
            scaler_path = os.path.join(self.config.models_dir, "scalers_usd_lkr.joblib")

            self.model = load_model(model_path)
            scalers = joblib.load(scaler_path)
            self.feature_scaler = scalers["feature_scaler"]
            self.target_scaler = scalers["target_scaler"]
            self.feature_names = scalers["feature_names"]

        # Scale input
        X = self.feature_scaler.transform(recent_data)
        X = X.reshape(1, self.sequence_length, -1)

        # Predict
        y_scaled = self.model.predict(X, verbose=0)
        y = self.target_scaler.inverse_transform(y_scaled)

        predicted_rate = float(y[0, 0])
        current_rate = recent_data[-1, 0]  # Last close price
        change_pct = (predicted_rate - current_rate) / current_rate * 100

        return {
            "predicted_rate": round(predicted_rate, 2),
            "current_rate": round(current_rate, 2),
            "change_pct": round(change_pct, 3),
            "direction": "up" if change_pct > 0 else "down",
            "prediction_date": (datetime.now()).strftime("%Y-%m-%d")
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("CurrencyGRUTrainer initialized successfully")
    print(f"TensorFlow available: {TF_AVAILABLE}")
    print(f"MLflow available: {MLFLOW_AVAILABLE}")

    if TF_AVAILABLE:
        print(f"TensorFlow version: {tf.__version__}")
        print(f"GPU available: {len(tf.config.list_physical_devices('GPU')) > 0}")

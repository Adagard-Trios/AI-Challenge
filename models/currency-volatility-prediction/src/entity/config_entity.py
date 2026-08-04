"""
models/currency-volatility-prediction/src/entity/config_entity.py
Configuration entities for LKR/USD Currency Prediction Pipeline
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional
import os


# Currency pairs to track
CURRENCY_PAIRS = {
    "LKR_USD": {
        "yahoo_symbol": "LKRUSD=X",  # Sri Lankan Rupee to USD
        "inverse_symbol": "USDLKR=X",  # USD to LKR (for visualization)
        "name": "USD/LKR Exchange Rate"
    }
}

# Economic indicators to include as features
ECONOMIC_INDICATORS = {
    "cse_index": {
        "yahoo_symbol": "^CSE",  # Colombo Stock Exchange
        "description": "CSE All Share Price Index"
    },
    "gold": {
        "yahoo_symbol": "GC=F",  # Gold futures
        "description": "Gold price (USD)"
    },
    "oil": {
        "yahoo_symbol": "CL=F",  # Crude oil futures
        "description": "Crude oil price"
    },
    "usd_index": {
        "yahoo_symbol": "DX-Y.NYB",  # US Dollar Index
        "description": "US Dollar strength index"
    },
    "india_inr": {
        "yahoo_symbol": "INRUSD=X",  # Indian Rupee (regional comparison)
        "description": "INR/USD (regional currency)"
    }
}


@dataclass
class DataIngestionConfig:
    """Configuration for currency data ingestion"""

    # Data source
    primary_pair: str = "USDLKR=X"  # USD to LKR for visualization

    # Historical data period
    history_period: str = "2y"  # 2 years of data
    history_interval: str = "1d"  # Daily data

    # Output paths
    raw_data_dir: str = field(default_factory=lambda: str(
        Path(__file__).parent.parent.parent / "artifacts" / "data"
    ))

    # Additional indicators
    include_indicators: bool = True
    indicators: Dict = field(default_factory=lambda: ECONOMIC_INDICATORS)


@dataclass
class ModelTrainerConfig:
    """Configuration for GRU model training"""

    # Model architecture (GRU - lighter than LSTM, faster than Transformer)
    sequence_length: int = 30  # 30 days lookback
    gru_units: List[int] = field(default_factory=lambda: [64, 32])
    dropout_rate: float = 0.2

    # Training parameters (optimized for 8GB RAM)
    epochs: int = 100
    batch_size: int = 16  # Small batch for memory efficiency
    validation_split: float = 0.2
    early_stopping_patience: int = 15

    # Learning rate scheduling
    initial_lr: float = 0.001
    lr_decay_factor: float = 0.5
    lr_patience: int = 5

    # MLflow config
    mlflow_tracking_uri: str = field(default_factory=lambda: os.getenv(
        "MLFLOW_TRACKING_URI", "https://dagshub.com/sliitguy/sri-lanka-ai-challenge-2026.mlflow"
    ))
    experiment_name: str = "currency_prediction_gru"

    # Output
    models_dir: str = field(default_factory=lambda: str(
        Path(__file__).parent.parent.parent / "artifacts" / "models"
    ))


@dataclass
class PredictionConfig:
    """Configuration for currency predictions"""

    # Output
    predictions_dir: str = field(default_factory=lambda: str(
        Path(__file__).parent.parent.parent / "output" / "predictions"
    ))

    # Prediction targets
    predict_next_day: bool = True

    # Volatility thresholds
    high_volatility_pct: float = 2.0  # >2% daily change
    medium_volatility_pct: float = 1.0  # 1-2% daily change


@dataclass
class PipelineConfig:
    """Master configuration for currency prediction pipeline"""
    data_ingestion: DataIngestionConfig = field(default_factory=DataIngestionConfig)
    model_trainer: ModelTrainerConfig = field(default_factory=ModelTrainerConfig)
    prediction: PredictionConfig = field(default_factory=PredictionConfig)

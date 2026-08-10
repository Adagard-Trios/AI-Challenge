"""
models/weather-prediction/src/entity/config_entity.py
Configuration entities for Weather Prediction Pipeline
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional
import os


# Station codes for Tutiempo.net
WEATHER_STATIONS = {
    "ANURADHAPURA": {"code": "434210", "districts": ["Anuradhapura"]},
    "BADULLA": {"code": "434790", "districts": ["Badulla", "Monaragala"]},
    "BATTICALOA": {"code": "434360", "districts": ["Batticaloa", "Ampara"]},
    "COLOMBO": {"code": "434660", "districts": ["Colombo", "Gampaha", "Kalutara"]},
    "DIYATALAWA": {"code": "434760", "districts": ["Nuwara Eliya"]},
    "HAMBANTOTA": {"code": "434970", "districts": ["Hambantota"]},
    "JAFFNA": {"code": "434040", "districts": ["Jaffna"]},
    "KANDY": {"code": "434440", "districts": ["Kandy", "Matale"]},
    "KANKASANTURAI": {"code": "434000", "districts": ["Kilinochchi", "Mullaitivu"]},
    "KATUNAYAKE": {"code": "434500", "districts": ["Gampaha"]},
    "KURUNEGALA": {"code": "434410", "districts": ["Kurunegala"]},
    "MAHA_ILLUPPALLAMA": {"code": "434220", "districts": ["Polonnaruwa"]},
    "MANNAR": {"code": "434130", "districts": ["Mannar"]},
    "MULLAITTIVU": {"code": "434100", "districts": ["Mullaitivu"]},
    "NUWARA_ELIYA": {"code": "434730", "districts": ["Nuwara Eliya"]},
    "PUTTALAM": {"code": "434240", "districts": ["Puttalam"]},
    "RATMALANA": {"code": "434670", "districts": ["Colombo"]},
    "RATNAPURA": {"code": "434860", "districts": ["Ratnapura", "Kegalle"]},
    "TRINCOMALEE": {"code": "434180", "districts": ["Trincomalee"]},
    "VAVUNIYA": {"code": "434150", "districts": ["Vavuniya"]},
}

# All 25 districts of Sri Lanka
SRI_LANKA_DISTRICTS = [
    "Ampara", "Anuradhapura", "Badulla", "Batticaloa", "Colombo",
    "Galle", "Gampaha", "Hambantota", "Jaffna", "Kalutara",
    "Kandy", "Kegalle", "Kilinochchi", "Kurunegala", "Mannar",
    "Matale", "Matara", "Monaragala", "Mullaitivu", "Nuwara Eliya",
    "Polonnaruwa", "Puttalam", "Ratnapura", "Trincomalee", "Vavuniya"
]

# District to nearest weather station mapping
DISTRICT_TO_STATION = {
    "Ampara": "BATTICALOA",
    "Anuradhapura": "ANURADHAPURA",
    "Badulla": "BADULLA",
    "Batticaloa": "BATTICALOA",
    "Colombo": "COLOMBO",
    "Galle": "HAMBANTOTA",
    "Gampaha": "KATUNAYAKE",
    "Hambantota": "HAMBANTOTA",
    "Jaffna": "JAFFNA",
    "Kalutara": "COLOMBO",
    "Kandy": "KANDY",
    "Kegalle": "RATNAPURA",
    "Kilinochchi": "KANKASANTURAI",
    "Kurunegala": "KURUNEGALA",
    "Mannar": "MANNAR",
    "Matale": "KANDY",
    "Matara": "HAMBANTOTA",
    "Monaragala": "BADULLA",
    "Mullaitivu": "MULLAITTIVU",
    "Nuwara Eliya": "NUWARA_ELIYA",
    "Polonnaruwa": "MAHA_ILLUPPALLAMA",
    "Puttalam": "PUTTALAM",
    "Ratnapura": "RATNAPURA",
    "Trincomalee": "TRINCOMALEE",
    "Vavuniya": "VAVUNIYA",
}


@dataclass
class DataIngestionConfig:
    """Configuration for weather data ingestion"""
    tutiempo_base_url: str = "https://en.tutiempo.net/climate"

    # Number of months of historical data to fetch
    months_to_fetch: int = int(os.getenv("WEATHER_MONTHS_HISTORY", "12"))

    # Output paths
    raw_data_dir: str = field(default_factory=lambda: str(
        Path(__file__).parent.parent.parent / "artifacts" / "data"
    ))

    # Stations to fetch
    stations: Dict = field(default_factory=lambda: WEATHER_STATIONS)


@dataclass
class ModelTrainerConfig:
    """Configuration for LSTM model training"""
    # Model architecture
    sequence_length: int = 30  # Days of history to use
    lstm_units: List[int] = field(default_factory=lambda: [64, 32])
    dropout_rate: float = 0.2

    # Training parameters
    epochs: int = 100
    batch_size: int = 32
    validation_split: float = 0.2
    early_stopping_patience: int = 10

    # MLflow config
    mlflow_tracking_uri: str = field(default_factory=lambda: os.getenv(
        "MLFLOW_TRACKING_URI", "https://dagshub.com/sliitguy/sri-lanka-ai-challenge-2026.mlflow"
    ))
    experiment_name: str = "weather_prediction_lstm"

    # Output
    models_dir: str = field(default_factory=lambda: str(
        Path(__file__).parent.parent.parent / "artifacts" / "models"
    ))


@dataclass
class PredictionConfig:
    """Configuration for weather predictions"""
    # Output
    predictions_dir: str = field(default_factory=lambda: str(
        Path(__file__).parent.parent.parent / "output" / "predictions"
    ))

    # Districts
    districts: List[str] = field(default_factory=lambda: SRI_LANKA_DISTRICTS)
    district_to_station: Dict = field(default_factory=lambda: DISTRICT_TO_STATION)

    # Severity thresholds
    critical_rain_mm: float = 100.0
    warning_rain_mm: float = 50.0
    advisory_rain_mm: float = 20.0
    critical_temp_c: float = 38.0
    advisory_temp_c: float = 35.0


@dataclass
class PipelineConfig:
    """Master configuration for the entire weather prediction pipeline"""
    data_ingestion: DataIngestionConfig = field(default_factory=DataIngestionConfig)
    model_trainer: ModelTrainerConfig = field(default_factory=ModelTrainerConfig)
    prediction: PredictionConfig = field(default_factory=PredictionConfig)

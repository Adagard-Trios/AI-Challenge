"""
models/anomaly-detection/src/entity/config_entity.py
Configuration entities for the anomaly detection pipeline
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import os


@dataclass
class DataIngestionConfig:
    """Configuration for data ingestion component"""
    sqlite_db_path: str = field(default_factory=lambda: os.getenv(
        "SQLITE_DB_PATH",
        str(Path(__file__).parent.parent.parent.parent.parent / "backend" / "data" / "feeds" / "feed_cache.db")
    ))
    csv_directory: str = field(default_factory=lambda: str(
        Path(__file__).parent.parent.parent.parent.parent / "backend" / "datasets" / "political_feeds"
    ))
    output_directory: str = field(default_factory=lambda: str(
        Path(__file__).parent.parent.parent / "artifacts" / "data_ingestion"
    ))
    batch_size: int = 1000
    min_text_length: int = 10


@dataclass
class DataValidationConfig:
    """Configuration for data validation component"""
    schema_file: str = field(default_factory=lambda: str(
        Path(__file__).parent.parent.parent / "data_schema" / "schema.yaml"
    ))
    required_columns: List[str] = field(default_factory=lambda: [
        "post_id", "timestamp", "platform", "category", "text", "content_hash"
    ])
    output_directory: str = field(default_factory=lambda: str(
        Path(__file__).parent.parent.parent / "artifacts" / "data_validation"
    ))


@dataclass
class DataTransformationConfig:
    """Configuration for data transformation/vectorization component"""
    # Huggingface models - will be downloaded locally
    models_cache_dir: str = field(default_factory=lambda: str(
        Path(__file__).parent.parent.parent / "models_cache"
    ))

    # Language-specific BERT models
    english_model: str = "distilbert-base-uncased"
    sinhala_model: str = "keshan/SinhalaBERTo"
    tamil_model: str = "l3cube-pune/tamil-bert"

    # Language detection
    fasttext_model_path: str = field(default_factory=lambda: str(
        Path(__file__).parent.parent.parent / "models_cache" / "lid.176.bin"  # FastText language ID model
    ))

    # Vector dimensions
    vector_dim: int = 768  # Standard BERT dimension

    # Output
    output_directory: str = field(default_factory=lambda: str(
        Path(__file__).parent.parent.parent / "artifacts" / "data_transformation"
    ))


@dataclass
class ModelTrainerConfig:
    """Configuration for model training component"""
    # MLflow configuration
    mlflow_tracking_uri: str = field(default_factory=lambda: os.getenv(
        "MLFLOW_TRACKING_URI", "https://dagshub.com/sliitguy/sri-lanka-ai-challenge-2026.mlflow"
    ))
    mlflow_username: str = field(default_factory=lambda: os.getenv(
        "MLFLOW_TRACKING_USERNAME", ""
    ))
    mlflow_password: str = field(default_factory=lambda: os.getenv(
        "MLFLOW_TRACKING_PASSWORD", ""
    ))
    experiment_name: str = "anomaly_detection_feeds"

    # Model configurations
    models_to_train: List[str] = field(default_factory=lambda: [
        "dbscan", "kmeans", "hdbscan", "isolation_forest", "lof"
    ])

    # Optuna hyperparameter tuning
    n_optuna_trials: int = 50
    optuna_timeout_seconds: int = 3600  # 1 hour

    # Model output
    output_directory: str = field(default_factory=lambda: str(
        Path(__file__).parent.parent.parent / "artifacts" / "model_trainer"
    ))


@dataclass
class PipelineConfig:
    """Master configuration for the entire pipeline"""
    data_ingestion: DataIngestionConfig = field(default_factory=DataIngestionConfig)
    data_validation: DataValidationConfig = field(default_factory=DataValidationConfig)
    data_transformation: DataTransformationConfig = field(default_factory=DataTransformationConfig)
    model_trainer: ModelTrainerConfig = field(default_factory=ModelTrainerConfig)

    # Pipeline settings
    batch_threshold: int = 1000  # Trigger training after this many new records
    run_interval_hours: int = 24  # Fallback daily run

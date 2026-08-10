"""
Anomaly Detection Training Pipeline Constants
"""
import os

# Pipeline configuration
PIPELINE_NAME: str = "AnomalyDetection"
ARTIFACT_DIR: str = "artifacts"

# Data sources
SQLITE_DB_PATH = os.getenv(
    "SQLITE_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "backend", "data", "feeds", "feed_cache.db")
)
CSV_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "backend", "datasets", "political_feeds")

# Data Ingestion
DATA_INGESTION_DIR_NAME: str = "data_ingestion"
DATA_INGESTION_FEATURE_STORE_DIR: str = "feature_store"
DATA_INGESTION_INGESTED_DIR: str = "ingested"
FILE_NAME: str = "ingested_data.parquet"
MIN_TEXT_LENGTH: int = 10
BATCH_SIZE: int = 1000

# Data Validation
DATA_VALIDATION_DIR_NAME: str = "data_validation"
DATA_VALIDATION_VALID_DIR: str = "validated"
DATA_VALIDATION_INVALID_DIR: str = "invalid"
SCHEMA_FILE_PATH = os.path.join("data_schema", "schema.yaml")
REQUIRED_COLUMNS = ["post_id", "timestamp", "platform", "category", "text", "content_hash"]

# Data Transformation
DATA_TRANSFORMATION_DIR_NAME: str = "data_transformation"
DATA_TRANSFORMATION_TRANSFORMED_DATA_DIR: str = "transformed"
FEATURE_STORE_FILE_NAME: str = "features.npy"

# Language Models (Multilingual BERT)
ENGLISH_MODEL: str = "distilbert-base-uncased"
SINHALA_MODEL: str = "keshan/SinhalaBERTo"
TAMIL_MODEL: str = "l3cube-pune/tamil-bert"
VECTOR_DIM: int = 768

# Model Training
MODEL_TRAINER_DIR_NAME: str = "model_trainer"
MODEL_TRAINER_TRAINED_MODEL_DIR: str = "trained_model"
MODEL_FILE_NAME: str = "model.joblib"
SAVED_MODEL_DIR = os.path.join("saved_models")

# Models to train
MODELS_TO_TRAIN = ["dbscan", "kmeans", "hdbscan", "isolation_forest", "lof"]

# Optuna hyperparameter tuning
N_OPTUNA_TRIALS: int = 50
OPTUNA_TIMEOUT_SECONDS: int = 3600  # 1 hour

# MLflow configuration
MLFLOW_TRACKING_URI = os.getenv(
    "MLFLOW_TRACKING_URI",
    "https://dagshub.com/sliitguy/sri-lanka-ai-challenge-2026.mlflow"
)
MLFLOW_EXPERIMENT_NAME: str = "anomaly_detection_feeds"

# Model thresholds
MODEL_TRAINER_EXPECTED_SCORE: float = 0.3  # Silhouette score threshold
MODEL_TRAINER_OVERFITTING_THRESHOLD: float = 0.1

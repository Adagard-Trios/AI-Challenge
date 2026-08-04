"""
models/anomaly-detection/src/entity/artifact_entity.py
Artifact entities for pipeline outputs
"""
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from pathlib import Path


@dataclass
class DataIngestionArtifact:
    """Artifact from data ingestion step"""
    raw_data_path: str
    total_records: int
    records_from_sqlite: int
    records_from_csv: int
    ingestion_timestamp: str
    is_data_available: bool


@dataclass
class DataValidationArtifact:
    """Artifact from data validation step"""
    validated_data_path: str
    validation_report_path: str
    total_records: int
    valid_records: int
    invalid_records: int
    validation_status: bool
    validation_errors: List[Dict[str, Any]]


@dataclass
class DataTransformationArtifact:
    """Artifact from data transformation step"""
    transformed_data_path: str
    vector_embeddings_path: str
    feature_store_path: str
    total_records: int
    language_distribution: Dict[str, int]
    transformation_report: Dict[str, Any]


@dataclass
class ModelTrainerArtifact:
    """Artifact from model training step"""
    # Best model info
    best_model_name: str
    best_model_path: str
    best_model_metrics: Dict[str, float]

    # All trained models
    trained_models: List[Dict[str, Any]]

    # MLflow tracking
    mlflow_run_id: str
    mlflow_experiment_id: str

    # Cluster/anomaly results
    n_clusters: Optional[int]
    n_anomalies: Optional[int]
    anomaly_indices: Optional[List[int]]

    # Training info
    training_duration_seconds: float
    optuna_study_name: Optional[str]


@dataclass
class PipelineArtifact:
    """Complete pipeline artifact"""
    data_ingestion: DataIngestionArtifact
    data_validation: DataValidationArtifact
    data_transformation: DataTransformationArtifact
    model_trainer: ModelTrainerArtifact
    pipeline_run_id: str
    pipeline_start_time: str
    pipeline_end_time: str
    pipeline_status: str

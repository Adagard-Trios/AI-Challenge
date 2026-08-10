"""
Anomaly Detection Training Pipeline
Trains clustering and anomaly detection models on feed data
"""
import sys
import os
from pathlib import Path
from datetime import datetime

# Load environment variables from root .env BEFORE other imports
from dotenv import load_dotenv
ROOT_DIR = Path(__file__).parent.parent.parent  # Go to Sri Lanka AI Challenge 2026
load_dotenv(ROOT_DIR / ".env")  # Load root .env with MLflow credentials

from src.components.data_ingestion import DataIngestion
from src.components.data_validation import DataValidation
from src.components.data_transformation import DataTransformation
from src.components.model_trainer import ModelTrainer
from src.exception.exception import AnomalyDetectionException
from src.logging.logger import logging
from src.entity.config_entity import (
    DataIngestionConfig, DataValidationConfig,
    DataTransformationConfig, ModelTrainerConfig, PipelineConfig
)
from src.constants.training_pipeline import MODELS_TO_TRAIN, MLFLOW_EXPERIMENT_NAME



def train_pipeline(pipeline_config: PipelineConfig = None) -> dict:
    """
    Train the anomaly detection pipeline.
    
    Args:
        pipeline_config: Pipeline configuration (optional)
        
    Returns:
        dict with training results
    """
    result = {"status": "failed"}
    
    if pipeline_config is None:
        pipeline_config = PipelineConfig()

    try:
        logging.info("\n" + "=" * 60)
        logging.info("ANOMALY DETECTION TRAINING PIPELINE")
        logging.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logging.info(f"Models to train: {MODELS_TO_TRAIN}")
        logging.info(f"MLflow experiment: {MLFLOW_EXPERIMENT_NAME}")
        logging.info("=" * 60 + "\n")

        # Data Ingestion
        data_ingestion_config = pipeline_config.data_ingestion
        data_ingestion = DataIngestion(data_ingestion_config)
        logging.info("Starting data ingestion...")
        data_ingestion_artifact = data_ingestion.initiate_data_ingestion()
        logging.info("✓ Data ingestion completed")

        # Data Validation
        data_validation_config = pipeline_config.data_validation
        data_validation = DataValidation(data_validation_config)
        logging.info("Starting data validation...")
        data_validation_artifact = data_validation.initiate_data_validation(
            data_ingestion_artifact.raw_data_path
        )
        logging.info("✓ Data validation completed")

        # Data Transformation
        data_transformation_config = pipeline_config.data_transformation
        data_transformation = DataTransformation(data_transformation_config)
        logging.info("Starting data transformation...")
        data_transformation_artifact = data_transformation.initiate_data_transformation(
            data_validation_artifact.validated_data_path
        )
        logging.info("✓ Data transformation completed")

        # Model Training
        model_trainer_config = pipeline_config.model_trainer
        model_trainer = ModelTrainer(model_trainer_config)
        logging.info("Starting model training...")
        model_trainer_artifact = model_trainer.initiate_model_trainer(
            data_transformation_artifact.feature_store_path
        )
        logging.info("✓ Model training completed")

        result = {
            "status": "success",
            "best_model": model_trainer_artifact.best_model_name,
            "best_model_path": model_trainer_artifact.best_model_path,
            "best_metrics": model_trainer_artifact.best_model_metrics,
            "n_anomalies": model_trainer_artifact.n_anomalies,
            "mlflow_run_id": model_trainer_artifact.mlflow_run_id,
            "data_ingestion": {
                "total_records": data_ingestion_artifact.total_records,
                "from_sqlite": data_ingestion_artifact.records_from_sqlite,
                "from_csv": data_ingestion_artifact.records_from_csv
            },
            "data_validation": {
                "valid_records": data_validation_artifact.valid_records,
                "validation_status": data_validation_artifact.validation_status
            },
            "data_transformation": {
                "language_distribution": data_transformation_artifact.language_distribution
            }
        }

        logging.info("\n" + "=" * 60)
        logging.info("PIPELINE RESULTS")
        logging.info("=" * 60)
        logging.info(f"Status: {result['status']}")
        logging.info(f"Best model: {result['best_model']}")
        logging.info(f"Anomalies detected: {result['n_anomalies']}")
        logging.info(f"MLflow run: {result.get('mlflow_run_id', 'N/A')}")
        logging.info("=" * 60 + "\n")

        logging.info("✓ Pipeline completed successfully!")

    except Exception as e:
        logging.error(f"✗ Pipeline failed: {str(e)}")
        result = {
            "status": "failed",
            "error": str(e)
        }

    return result


if __name__ == '__main__':
    try:
        results = train_pipeline()
        
        if results["status"] == "failed":
            logging.error("Pipeline failed - check logs for details")
            sys.exit(1)
            
    except Exception as e:
        logging.error(f"Pipeline crashed: {e}")
        raise AnomalyDetectionException(e, sys)

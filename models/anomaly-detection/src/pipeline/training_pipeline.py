"""
models/anomaly-detection/src/pipeline/training_pipeline.py
End-to-end training pipeline orchestrator
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..entity import (
    PipelineConfig,
    PipelineArtifact,
    DataIngestionArtifact,
    DataValidationArtifact,
    DataTransformationArtifact,
    ModelTrainerArtifact
)
from ..components import (
    DataIngestion,
    DataValidation,
    DataTransformation,
    ModelTrainer
)

logger = logging.getLogger("training_pipeline")


class TrainingPipeline:
    """
    End-to-end training pipeline that orchestrates:
    1. Data Ingestion (SQLite + CSV)
    2. Data Validation (schema checking)
    3. Data Transformation (language detection + vectorization)
    4. Model Training (clustering + anomaly detection)
    """

    def __init__(self, config: Optional[PipelineConfig] = None):
        """
        Initialize training pipeline.
        
        Args:
            config: Optional pipeline configuration
        """
        self.config = config or PipelineConfig()
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        logger.info(f"[TrainingPipeline] Initialized (run_id: {self.run_id})")

    def run_data_ingestion(self) -> DataIngestionArtifact:
        """Execute data ingestion step"""
        logger.info("=" * 50)
        logger.info("[TrainingPipeline] STEP 1: Data Ingestion")
        logger.info("=" * 50)

        ingestion = DataIngestion(self.config.data_ingestion)
        artifact = ingestion.initiate_data_ingestion()

        if not artifact.is_data_available:
            raise ValueError("No data available for training")

        return artifact

    def run_data_validation(self, ingestion_artifact: DataIngestionArtifact) -> DataValidationArtifact:
        """Execute data validation step"""
        logger.info("=" * 50)
        logger.info("[TrainingPipeline] STEP 2: Data Validation")
        logger.info("=" * 50)

        validation = DataValidation(self.config.data_validation)
        artifact = validation.initiate_data_validation(ingestion_artifact.raw_data_path)

        return artifact

    def run_data_transformation(self, validation_artifact: DataValidationArtifact) -> DataTransformationArtifact:
        """Execute data transformation step"""
        logger.info("=" * 50)
        logger.info("[TrainingPipeline] STEP 3: Data Transformation")
        logger.info("=" * 50)

        transformation = DataTransformation(self.config.data_transformation)
        artifact = transformation.initiate_data_transformation(validation_artifact.validated_data_path)

        return artifact

    def run_model_training(self, transformation_artifact: DataTransformationArtifact) -> ModelTrainerArtifact:
        """Execute model training step"""
        logger.info("=" * 50)
        logger.info("[TrainingPipeline] STEP 4: Model Training")
        logger.info("=" * 50)

        trainer = ModelTrainer(self.config.model_trainer)
        artifact = trainer.initiate_model_trainer(transformation_artifact.feature_store_path)

        return artifact

    def run(self) -> PipelineArtifact:
        """
        Execute the complete training pipeline.
        
        Returns:
            PipelineArtifact with all step results
        """
        start_time = datetime.now()
        logger.info("=" * 60)
        logger.info("[TrainingPipeline] STARTING TRAINING PIPELINE")
        logger.info("=" * 60)

        try:
            # Step 1: Data Ingestion
            ingestion_artifact = self.run_data_ingestion()

            # Step 2: Data Validation
            validation_artifact = self.run_data_validation(ingestion_artifact)

            # Step 3: Data Transformation
            transformation_artifact = self.run_data_transformation(validation_artifact)

            # Step 4: Model Training
            training_artifact = self.run_model_training(transformation_artifact)

            pipeline_status = "SUCCESS"

        except Exception as e:
            logger.error(f"[TrainingPipeline] Pipeline failed: {e}")
            pipeline_status = f"FAILED: {str(e)}"
            raise

        finally:
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            logger.info("=" * 60)
            logger.info(f"[TrainingPipeline] PIPELINE {pipeline_status}")
            logger.info(f"[TrainingPipeline] Duration: {duration:.1f}s")
            logger.info("=" * 60)

        # Build final artifact
        artifact = PipelineArtifact(
            data_ingestion=ingestion_artifact,
            data_validation=validation_artifact,
            data_transformation=transformation_artifact,
            model_trainer=training_artifact,
            pipeline_run_id=self.run_id,
            pipeline_start_time=start_time.isoformat(),
            pipeline_end_time=end_time.isoformat(),
            pipeline_status=pipeline_status
        )

        return artifact


def run_training_pipeline(config: Optional[PipelineConfig] = None) -> PipelineArtifact:
    """
    Convenience function to run the training pipeline.
    
    Args:
        config: Optional pipeline configuration
        
    Returns:
        PipelineArtifact with results
    """
    pipeline = TrainingPipeline(config)
    return pipeline.run()

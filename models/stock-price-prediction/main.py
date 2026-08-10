"""
Stock Price Prediction Pipeline - Multi-Stock Training
Trains separate LSTM models for each stock in STOCKS_TO_TRAIN
"""
from src.components.data_ingestion import DataIngestion
from src.components.data_validation import DataValidation
from src.components.data_transformation import DataTransformation
from src.components.model_trainer import ModelTrainer
from src.exception.exception import StockPriceException
from src.logging.logger import logging
from src.entity.config_entity import (
    DataIngestionConfig, DataValidationConfig,
    DataTransformationConfig, ModelTrainerConfig, TrainingPipelineConfig
)
from src.constants.training_pipeline import STOCKS_TO_TRAIN

import sys
import os
from datetime import datetime


def train_single_stock(stock_code: str, training_pipeline_config: TrainingPipelineConfig) -> dict:
    """
    Train a model for a single stock.
    
    Args:
        stock_code: Stock ticker symbol (e.g., 'AAPL', 'GOOGL')
        training_pipeline_config: Pipeline configuration
        
    Returns:
        dict with training results or error info
    """
    result = {"stock": stock_code, "status": "failed"}

    try:
        logging.info(f"\n{'='*60}")
        logging.info(f"Training model for: {stock_code}")
        logging.info(f"{'='*60}")

        # Data Ingestion
        data_ingestion_config = DataIngestionConfig(training_pipeline_config)
        data_ingestion = DataIngestion(data_ingestion_config, stock_code=stock_code)
        logging.info(f"[{stock_code}] Starting data ingestion...")
        data_ingestion_artifact = data_ingestion.initiate_data_ingestion()
        logging.info(f"[{stock_code}] ✓ Data ingestion completed")

        # Data Validation
        data_validation_config = DataValidationConfig(training_pipeline_config)
        data_validation = DataValidation(data_ingestion_artifact, data_validation_config)
        logging.info(f"[{stock_code}] Starting data validation...")
        data_validation_artifact = data_validation.initiate_data_validation()
        logging.info(f"[{stock_code}] ✓ Data validation completed")

        # Data Transformation
        data_transformation_config = DataTransformationConfig(training_pipeline_config)
        data_transformation = DataTransformation(data_validation_artifact, data_transformation_config)
        logging.info(f"[{stock_code}] Starting data transformation...")
        data_transformation_artifact = data_transformation.initiate_data_transformation()
        logging.info(f"[{stock_code}] ✓ Data transformation completed")

        # Model Training
        model_trainer_config = ModelTrainerConfig(training_pipeline_config)
        model_trainer = ModelTrainer(
            model_trainer_config=model_trainer_config,
            data_transformation_artifact=data_transformation_artifact
        )
        logging.info(f"[{stock_code}] Starting model training...")
        model_trainer_artifact = model_trainer.initiate_model_trainer()
        logging.info(f"[{stock_code}] ✓ Model training completed")

        result = {
            "stock": stock_code,
            "status": "success",
            "model_path": model_trainer_artifact.trained_model_file_path,
            "test_metric": str(model_trainer_artifact.test_metric_artifact)
        }

        logging.info(f"[{stock_code}] ✓ Pipeline completed successfully!")

    except Exception as e:
        logging.error(f"[{stock_code}] ✗ Pipeline failed: {str(e)}")
        result = {
            "stock": stock_code,
            "status": "failed",
            "error": str(e)
        }

    return result


def train_all_stocks():
    """
    Train models for all stocks in STOCKS_TO_TRAIN.
    Each stock gets its own model saved separately.
    """
    logging.info("\n" + "="*70)
    logging.info("STOCK PRICE PREDICTION - MULTI-STOCK TRAINING PIPELINE")
    logging.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info(f"Stocks to train: {list(STOCKS_TO_TRAIN.keys())}")
    logging.info("="*70 + "\n")

    results = []
    successful = 0
    failed = 0

    for stock_code in STOCKS_TO_TRAIN.keys():
        # Create a new pipeline config for each stock (separate artifact directories)
        training_pipeline_config = TrainingPipelineConfig()

        result = train_single_stock(stock_code, training_pipeline_config)
        results.append(result)

        if result["status"] == "success":
            successful += 1
        else:
            failed += 1

    # Print summary
    logging.info("\n" + "="*70)
    logging.info("TRAINING SUMMARY")
    logging.info("="*70)
    logging.info(f"Total stocks: {len(STOCKS_TO_TRAIN)}")
    logging.info(f"Successful: {successful}")
    logging.info(f"Failed: {failed}")
    logging.info("-"*70)

    for result in results:
        if result["status"] == "success":
            logging.info(f"  ✓ {result['stock']}: {result['model_path']}")
        else:
            logging.info(f"  ✗ {result['stock']}: {result.get('error', 'Unknown error')[:50]}")

    logging.info("="*70)
    logging.info(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info("="*70 + "\n")

    return results


if __name__ == '__main__':
    try:
        # Train all stocks
        results = train_all_stocks()

        # Exit with error code if any failures
        failed_count = sum(1 for r in results if r["status"] == "failed")
        if failed_count > 0:
            logging.warning(f"{failed_count} stocks failed to train")
            sys.exit(1)

    except Exception as e:
        logging.error(f"Pipeline crashed: {e}")
        raise StockPriceException(e, sys)

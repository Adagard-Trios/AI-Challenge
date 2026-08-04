"""
Currency Volatility Prediction Pipeline - USD/LKR Training
Follows stock-price-prediction pattern with structured artifact flow
"""
from src.components.data_ingestion import CurrencyDataIngestion
from src.components.model_trainer import CurrencyGRUTrainer
from src.components.predictor import CurrencyPredictor
from src.exception.exception import CurrencyPredictionException
from src.logging.logger import logging
from src.entity.config_entity import DataIngestionConfig, ModelTrainerConfig

import sys
import os
import argparse
from datetime import datetime


def train_currency(period: str = "2y", epochs: int = 100) -> dict:
    """
    Train the currency prediction model.
    
    Follows stock-price-prediction pattern with structured results.
    
    Args:
        period: Data period for yfinance (1y, 2y, 5y)
        epochs: Number of training epochs
        
    Returns:
        dict with training results or error info
    """
    result = {"currency": "USD_LKR", "status": "failed"}

    try:
        logging.info(f"\n{'='*60}")
        logging.info("CURRENCY PREDICTION PIPELINE - TRAINING")
        logging.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logging.info(f"{'='*60}")

        # Step 1: Data Ingestion
        logging.info("[USD_LKR] Starting data ingestion...")
        config = DataIngestionConfig(history_period=period)
        ingestion = CurrencyDataIngestion(config)
        data_path = ingestion.ingest_all()
        df = ingestion.load_existing(data_path)
        logging.info(f"[USD_LKR] ✓ Data ingestion completed: {len(df)} records")

        # Step 2: Model Training
        logging.info("[USD_LKR] Starting model training...")
        trainer_config = ModelTrainerConfig(epochs=epochs)
        trainer = CurrencyGRUTrainer(trainer_config)
        train_results = trainer.train(df=df, use_mlflow=True)
        logging.info("[USD_LKR] ✓ Model training completed")

        result = {
            "currency": "USD_LKR",
            "status": "success",
            "model_path": train_results["model_path"],
            "test_mae": train_results["test_mae"],
            "rmse": train_results["rmse"],
            "direction_accuracy": train_results["direction_accuracy"],
            "epochs_trained": train_results["epochs_trained"]
        }

        logging.info(f"[USD_LKR] ✓ Pipeline completed successfully!")

    except Exception as e:
        logging.error(f"[USD_LKR] ✗ Pipeline failed: {str(e)}")
        result = {
            "currency": "USD_LKR",
            "status": "failed",
            "error": str(e)
        }

    return result


def run_prediction() -> dict:
    """
    Run prediction for next day.
    
    Returns:
        Prediction dictionary
    """
    logging.info("Generating prediction...")

    predictor = CurrencyPredictor()

    try:
        ingestion = CurrencyDataIngestion()
        df = ingestion.load_existing()
        prediction = predictor.predict(df)
        logging.info("[USD_LKR] ✓ Prediction generated using trained model")
    except FileNotFoundError:
        logging.warning("[USD_LKR] Model not trained, using fallback")
        prediction = predictor.generate_fallback_prediction()
    except Exception as e:
        logging.error(f"[USD_LKR] Error: {e}")
        prediction = predictor.generate_fallback_prediction()

    output_path = predictor.save_prediction(prediction)

    # Display
    logging.info(f"\n{'='*50}")
    logging.info(f"USD/LKR PREDICTION FOR {prediction['prediction_date']}")
    logging.info(f"{'='*50}")
    logging.info(f"Current Rate:   {prediction['current_rate']:.2f} LKR/USD")
    logging.info(f"Predicted Rate: {prediction['predicted_rate']:.2f} LKR/USD")
    logging.info(f"Expected Change: {prediction['expected_change_pct']:+.3f}%")
    logging.info(f"Direction: {prediction['direction_emoji']} LKR {prediction['direction']}")
    logging.info(f"Volatility: {prediction['volatility_class']}")

    if prediction.get('weekly_trend'):
        logging.info(f"Weekly Trend: {prediction['weekly_trend']:+.2f}%")
    if prediction.get('monthly_trend'):
        logging.info(f"Monthly Trend: {prediction['monthly_trend']:+.2f}%")

    logging.info(f"{'='*50}")
    logging.info(f"Saved to: {output_path}")

    return prediction


def run_full_pipeline():
    """
    Run the complete pipeline: train → predict.
    Following stock-price-prediction pattern.
    """
    logging.info("\n" + "="*70)
    logging.info("CURRENCY PREDICTION PIPELINE - FULL RUN")
    logging.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info("="*70 + "\n")

    # Step 1: Training
    result = train_currency(period="2y", epochs=100)

    # Step 2: Prediction
    prediction = run_prediction()

    # Print summary
    logging.info("\n" + "="*70)
    logging.info("TRAINING SUMMARY")
    logging.info("="*70)
    
    if result["status"] == "success":
        logging.info(f"  ✓ USD_LKR: {result['model_path']}")
        logging.info(f"       MAE: {result['test_mae']:.4f} LKR")
        logging.info(f"       RMSE: {result['rmse']:.4f} LKR")
        logging.info(f"       Direction Accuracy: {result['direction_accuracy']*100:.1f}%")
    else:
        logging.info(f"  ✗ USD_LKR: {result.get('error', 'Unknown error')[:50]}")

    logging.info("="*70)
    logging.info(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info("="*70 + "\n")

    return result, prediction


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Currency Prediction Pipeline")
    parser.add_argument(
        "--mode",
        choices=["train", "predict", "full"],
        default="predict",
        help="Pipeline mode to run"
    )
    parser.add_argument(
        "--period",
        type=str,
        default="2y",
        help="Data period (1y, 2y, 5y)"
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=100,
        help="Training epochs"
    )

    args = parser.parse_args()

    try:
        if args.mode == "train":
            result = train_currency(period=args.period, epochs=args.epochs)
            if result["status"] == "failed":
                sys.exit(1)
        elif args.mode == "predict":
            run_prediction()
        elif args.mode == "full":
            result, prediction = run_full_pipeline()
            if result["status"] == "failed":
                sys.exit(1)
    except Exception as e:
        logging.error(f"Pipeline crashed: {e}")
        raise CurrencyPredictionException(e, sys)

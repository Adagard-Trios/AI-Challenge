"""
Weather Prediction Pipeline - Multi-Station Training
Follows stock-price-prediction pattern with structured artifact flow
"""
from src.components.data_ingestion import DataIngestion
from src.components.model_trainer import WeatherLSTMTrainer
from src.components.predictor import WeatherPredictor
from src.exception.exception import WeatherPredictionException
from src.logging.logger import logging
from src.entity.config_entity import DataIngestionConfig, WEATHER_STATIONS

import sys
import os
import argparse
from pathlib import Path
from datetime import datetime

PIPELINE_ROOT = Path(__file__).parent


def train_single_station(station_name: str, epochs: int = 100) -> dict:
    """
    Train a model for a single weather station.
    
    Follows stock-price-prediction pattern with structured results.
    
    Args:
        station_name: Weather station name (e.g., 'COLOMBO', 'KANDY')
        epochs: Number of training epochs
        
    Returns:
        dict with training results or error info
    """
    result = {"station": station_name, "status": "failed"}

    try:
        logging.info(f"\n{'='*60}")
        logging.info(f"Training model for: {station_name}")
        logging.info(f"{'='*60}")

        # Data Ingestion
        logging.info(f"[{station_name}] Loading data...")
        ingestion = DataIngestion()
        df = ingestion.load_existing()
        logging.info(f"[{station_name}] ✓ Data loaded")

        # Model Training
        logging.info(f"[{station_name}] Starting model training...")
        trainer = WeatherLSTMTrainer(
            sequence_length=30,
            lstm_units=[64, 32]
        )
        
        train_results = trainer.train(
            df=df,
            station_name=station_name,
            epochs=epochs,
            use_mlflow=False  # Disabled due to Windows Unicode encoding issues
        )
        logging.info(f"[{station_name}] ✓ Model training completed")

        result = {
            "station": station_name,
            "status": "success",
            "model_path": train_results.get("model_path", ""),
            "test_mae": train_results.get("test_mae", 0),
            "test_mse": train_results.get("test_mse", 0),
            "epochs_trained": epochs
        }

        logging.info(f"[{station_name}] ✓ Pipeline completed successfully!")

    except Exception as e:
        logging.error(f"[{station_name}] ✗ Pipeline failed: {str(e)}")
        result = {
            "station": station_name,
            "status": "failed",
            "error": str(e)
        }

    return result


def train_all_stations(stations: list = None, epochs: int = 100) -> list:
    """
    Train models for all weather stations.
    Each station gets its own model saved separately.
    
    Follows stock-price-prediction pattern.
    """
    stations_to_train = stations or list(WEATHER_STATIONS.keys())

    logging.info("\n" + "="*70)
    logging.info("WEATHER PREDICTION - MULTI-STATION TRAINING PIPELINE")
    logging.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info(f"Stations to train: {stations_to_train}")
    logging.info("="*70 + "\n")

    results = []
    successful = 0
    failed = 0

    for station_name in stations_to_train:
        result = train_single_station(station_name, epochs)
        results.append(result)

        if result["status"] == "success":
            successful += 1
        else:
            failed += 1

    # Print summary
    logging.info("\n" + "="*70)
    logging.info("TRAINING SUMMARY")
    logging.info("="*70)
    logging.info(f"Total stations: {len(stations_to_train)}")
    logging.info(f"Successful: {successful}")
    logging.info(f"Failed: {failed}")
    logging.info("-"*70)

    for result in results:
        if result["status"] == "success":
            logging.info(f"  ✓ {result['station']}: MAE={result['test_mae']:.3f}")
        else:
            logging.info(f"  ✗ {result['station']}: {result.get('error', 'Unknown error')[:50]}")

    logging.info("="*70)
    logging.info(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info("="*70 + "\n")

    return results


def run_data_ingestion(months: int = 12):
    """Run data ingestion for all stations."""
    logging.info(f"Starting data ingestion ({months} months)...")

    config = DataIngestionConfig(months_to_fetch=months)
    ingestion = DataIngestion(config)

    data_path = ingestion.ingest_all()

    df = ingestion.load_existing(data_path)
    stats = ingestion.get_data_stats(df)

    logging.info("✓ Data Ingestion Complete!")
    logging.info(f"Total records: {stats['total_records']}")
    logging.info(f"Stations: {stats['stations']}")
    logging.info(f"Date range: {stats['date_range']}")

    return data_path


def check_and_train_missing_models(priority_only: bool = True, epochs: int = 25):
    """
    Check for missing LSTM models and train them automatically.
    
    Args:
        priority_only: If True, only train priority stations (COLOMBO, KANDY, etc.)
                      If False, train all configured stations
        epochs: Number of epochs for training
        
    Returns:
        List of trained station names
    """
    models_dir = PIPELINE_ROOT / "artifacts" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    # Priority stations for minimal prediction coverage
    priority_stations = ["COLOMBO", "KANDY", "JAFFNA", "BATTICALOA", "RATNAPURA"]

    stations_to_check = priority_stations if priority_only else list(WEATHER_STATIONS.keys())
    missing_stations = []

    # Check which models are missing
    for station in stations_to_check:
        model_file = models_dir / f"lstm_{station.lower()}.h5"
        if not model_file.exists():
            missing_stations.append(station)

    if not missing_stations:
        logging.info("[AUTO-TRAIN] All required models exist.")
        return []

    logging.info(f"[AUTO-TRAIN] Missing models for: {', '.join(missing_stations)}")
    logging.info("[AUTO-TRAIN] Starting automatic training...")

    # Ensure we have data first
    data_path = PIPELINE_ROOT / "artifacts" / "data"
    existing_data = list(data_path.glob("weather_history_*.csv")) if data_path.exists() else []

    if not existing_data:
        logging.info("[AUTO-TRAIN] No training data found, ingesting...")
        try:
            run_data_ingestion(months=3)
        except Exception as e:
            logging.error(f"[AUTO-TRAIN] Data ingestion failed: {e}")
            logging.info("[AUTO-TRAIN] Cannot train without data. Please run: python main.py --mode ingest")
            return []

    # Train missing models using structured function
    results = train_all_stations(stations=missing_stations, epochs=epochs)
    
    trained = [r["station"] for r in results if r["status"] == "success"]
    logging.info(f"[AUTO-TRAIN] Auto-training complete. Trained {len(trained)} models.")
    return trained


def run_prediction():
    """Run prediction for all districts."""
    logging.info("Generating predictions...")

    predictor = WeatherPredictor()

    # Try to get RiverNet data
    rivernet_data = None
    try:
        sys.path.insert(0, str(PIPELINE_ROOT.parent.parent / "backend" / "src"))
        from utils.utils import tool_rivernet_status
        rivernet_data = tool_rivernet_status()
        logging.info(f"✓ RiverNet data available: {len(rivernet_data.get('rivers', []))} rivers")
    except Exception as e:
        logging.warning(f"RiverNet data unavailable: {e}")

    predictions = predictor.predict_all_districts(rivernet_data=rivernet_data)
    output_path = predictor.save_predictions(predictions)

    # Summary
    districts = predictions.get("districts", {})
    severity_counts = {"normal": 0, "advisory": 0, "warning": 0, "critical": 0}

    for d, p in districts.items():
        sev = p.get("severity", "normal")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    logging.info(f"\n{'='*50}")
    logging.info(f"PREDICTIONS FOR {predictions['prediction_date']}")
    logging.info(f"{'='*50}")
    logging.info(f"Districts: {len(districts)}")
    logging.info(f"Normal: {severity_counts['normal']}")
    logging.info(f"Advisory: {severity_counts['advisory']}")
    logging.info(f"Warning: {severity_counts['warning']}")
    logging.info(f"Critical: {severity_counts['critical']}")
    logging.info(f"Output: {output_path}")

    return predictions


def run_full_pipeline():
    """
    Run the full pipeline: ingest → train → predict.
    Following stock-price-prediction pattern.
    """
    logging.info("\n" + "="*70)
    logging.info("WEATHER PREDICTION PIPELINE - FULL RUN")
    logging.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info("="*70 + "\n")

    # Step 1: Data Ingestion
    try:
        run_data_ingestion(months=3)
    except Exception as e:
        logging.error(f"Data ingestion failed: {e}")
        logging.info("Attempting to use existing data...")

    # Step 2: Training (priority stations only)
    priority_stations = ["COLOMBO", "KANDY", "JAFFNA", "BATTICALOA", "RATNAPURA"]
    results = train_all_stations(stations=priority_stations, epochs=50)

    # Step 3: Prediction
    predictions = run_prediction()

    logging.info("\n" + "="*70)
    logging.info("PIPELINE COMPLETE!")
    logging.info(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info("="*70 + "\n")

    return results, predictions


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Weather Prediction Pipeline")
    parser.add_argument(
        "--mode",
        choices=["ingest", "train", "predict", "full", "auto-train"],
        default="predict",
        help="Pipeline mode to run (auto-train checks and trains missing models)"
    )
    parser.add_argument(
        "--months",
        type=int,
        default=12,
        help="Months of historical data to ingest"
    )
    parser.add_argument(
        "--station",
        type=str,
        default=None,
        help="Specific station to train (e.g., COLOMBO)"
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=100,
        help="Training epochs"
    )
    parser.add_argument(
        "--skip-auto-train",
        action="store_true",
        help="Skip automatic training of missing models during predict"
    )

    args = parser.parse_args()

    try:
        if args.mode == "ingest":
            run_data_ingestion(months=args.months)
        elif args.mode == "train":
            if args.station:
                result = train_single_station(args.station, args.epochs)
                if result["status"] == "failed":
                    sys.exit(1)
            else:
                results = train_all_stations(epochs=args.epochs)
                failed = sum(1 for r in results if r["status"] == "failed")
                if failed > 0:
                    logging.warning(f"{failed} stations failed to train")
                    sys.exit(1)
        elif args.mode == "auto-train":
            # Explicitly auto-train missing models
            check_and_train_missing_models(priority_only=True, epochs=25)
        elif args.mode == "predict":
            # Auto-train missing models before prediction (unless skipped)
            if not args.skip_auto_train:
                check_and_train_missing_models(priority_only=True, epochs=25)
            run_prediction()
        elif args.mode == "full":
            results, predictions = run_full_pipeline()
            failed = sum(1 for r in results if r["status"] == "failed")
            if failed > 0:
                logging.warning(f"{failed} stations failed to train")
                sys.exit(1)
    except Exception as e:
        logging.error(f"Pipeline crashed: {e}")
        raise WeatherPredictionException(e, sys)

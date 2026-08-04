"""
Weather Prediction Training Script
Convenience wrapper for: python models/weather-prediction/main.py --mode train

Usage:
    python models/weather-prediction/src/pipeline/train.py [--station COLOMBO] [--epochs 100]
"""
import sys
import argparse
from pathlib import Path

# CRITICAL: Import standard library logging BEFORE adding src/ to path
# (src/logging/ directory would otherwise shadow the standard module)
import logging

# Add parent directories to path
PIPELINE_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PIPELINE_ROOT))
sys.path.insert(0, str(PIPELINE_ROOT / "src"))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Weather Prediction Training")
    parser.add_argument("--station", type=str, default=None, help="Station to train (e.g., COLOMBO)")
    parser.add_argument("--epochs", type=int, default=100, help="Training epochs")
    parser.add_argument("--full", action="store_true", help="Run full pipeline (ingest + train + predict)")

    args = parser.parse_args()

    # Import from main.py (after path setup)
    from main import run_training, run_full_pipeline, run_data_ingestion

    print("=" * 60)
    print("WEATHER PREDICTION - TRAINING PIPELINE")
    print("=" * 60)

    if args.full:
        run_full_pipeline()
    else:
        # Run data ingestion first if no data exists
        try:
            from components.data_ingestion import DataIngestion
            ingestion = DataIngestion()
            df = ingestion.load_existing()
            print(f"✓ Found existing data: {len(df)} records")
        except FileNotFoundError:
            print("No existing data, running ingestion first...")
            run_data_ingestion(months=3)

        # Run training
        run_training(station=args.station, epochs=args.epochs)

    print("=" * 60)
    print("TRAINING COMPLETE!")
    print("=" * 60)


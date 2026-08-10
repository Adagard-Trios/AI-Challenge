"""
Currency Volatility Prediction Training Script
Convenience wrapper for: python models/currency-volatility-prediction/main.py --mode train

Usage:
    python models/currency-volatility-prediction/src/pipeline/train.py [--epochs 100] [--period 2y]
"""
import sys
import argparse
import logging  # CRITICAL: Import BEFORE path manipulation
from pathlib import Path

# Configure logging BEFORE adding src/ to path
# (src/logging/ directory would otherwise shadow the standard module)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Add parent directories to path - AFTER logging is configured
PIPELINE_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PIPELINE_ROOT))
sys.path.insert(0, str(PIPELINE_ROOT / "src"))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Currency Prediction Training")
    parser.add_argument("--epochs", type=int, default=100, help="Training epochs")
    parser.add_argument("--period", type=str, default="2y", help="Data period (1y, 2y, 5y)")
    parser.add_argument("--full", action="store_true", help="Run full pipeline (ingest + train + predict)")

    args = parser.parse_args()

    # Import from main.py (after path setup)
    from main import run_training, run_full_pipeline, run_data_ingestion

    print("=" * 60)
    print("CURRENCY (USD/LKR) PREDICTION - TRAINING PIPELINE")
    print("=" * 60)

    if args.full:
        run_full_pipeline()
    else:
        # Run data ingestion first if no data exists
        try:
            from components.data_ingestion import CurrencyDataIngestion
            ingestion = CurrencyDataIngestion()
            df = ingestion.load_existing()
            print(f"✓ Found existing data: {len(df)} records")
        except FileNotFoundError:
            print("No existing data, running ingestion first...")
            run_data_ingestion(period=args.period)

        # Run training
        run_training(epochs=args.epochs)

    print("=" * 60)
    print("TRAINING COMPLETE!")
    print("=" * 60)

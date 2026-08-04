"""
Anomaly Detection Training Script
Convenience wrapper for: python models/anomaly-detection/main.py

Usage:
    python models/anomaly-detection/src/pipeline/train.py
"""
import sys
import argparse
import logging  # Import BEFORE path manipulation
from pathlib import Path

# Configure logging BEFORE adding src/ to path
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Add parent directories to path - AFTER logging is configured
PIPELINE_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PIPELINE_ROOT))
sys.path.insert(0, str(PIPELINE_ROOT / "src"))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Anomaly Detection Training")
    parser.add_argument("--help-only", action="store_true", help="Show help and exit")

    # Parse known args to allow --help to work without loading heavy modules
    args, _ = parser.parse_known_args()

    print("=" * 60)
    print("ANOMALY DETECTION - TRAINING PIPELINE")
    print("=" * 60)

    # Import and run from main.py
    from main import main

    result = main()

    if result:
        print("=" * 60)
        print("TRAINING COMPLETE!")
        print(f"Best model: {result.model_trainer.best_model_name}")
        print("=" * 60)

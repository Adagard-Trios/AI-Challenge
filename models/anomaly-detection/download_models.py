"""
models/anomaly-detection/download_models.py
Script to pre-download all required models for the pipeline.
"""
import os
import sys
import requests
import logging
from pathlib import Path
from tqdm import tqdm

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("downloader")

# Constants
CACHE_DIR = Path(__file__).parent / "models_cache"
FASTTEXT_URL = "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin"
FASTTEXT_PATH = CACHE_DIR / "lid.176.bin"

def download_file(url, destination):
    """Download file with progress bar"""
    response = requests.get(url, stream=True)
    total_size = int(response.headers.get('content-length', 0))

    with open(destination, 'wb') as file, tqdm(
        desc=destination.name,
        total=total_size,
        unit='iB',
        unit_scale=True,
        unit_divisor=1024,
    ) as bar:
        for data in response.iter_content(chunk_size=1024):
            size = file.write(data)
            bar.update(size)

def main():
    logger.info("=" * 50)
    logger.info("⬇️  MODEL DOWNLOADER")
    logger.info("=" * 50)

    # Ensure cache directory exists
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"📂 Cache Directory: {CACHE_DIR}")

    # 1. Download FastText Model
    logger.info("\n[1/2] Checking FastText Model (Language Detection)...")
    if not FASTTEXT_PATH.exists():
        logger.info("   Downloading lid.176.bin...")
        try:
            download_file(FASTTEXT_URL, FASTTEXT_PATH)
            logger.info("   ✅ Download complete")
        except Exception as e:
            logger.error(f"   ❌ Failed to download FastText: {e}")
    else:
        logger.info("   ✅ FastText model already exists")

    # 2. Download HuggingFace Models
    logger.info("\n[2/2] Checking HuggingFace BERT Models (Vectorization)...")
    try:
        from src.utils.vectorizer import get_vectorizer

        # Initialize vectorizer which handles HF downloads
        logger.info("   Initializing vectorizer to trigger downloads...")
        vectorizer = get_vectorizer(models_cache_dir=str(CACHE_DIR))

        # Trigger downloads for all languages
        vectorizer.download_all_models()

        logger.info("   ✅ All BERT models ready")

    except ImportError:
        logger.error("   ❌ Could not import vectorizer. Install requirements first:")
        logger.error("      pip install -r requirements.txt")
    except Exception as e:
        logger.error(f"   ❌ Error downloading BERT models: {e}")

    logger.info("\n" + "=" * 50)
    logger.info("✨ SETUP COMPLETE")
    logger.info("=" * 50)

if __name__ == "__main__":
    main()

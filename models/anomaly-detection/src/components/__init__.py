"""
models/anomaly-detection/src/components/__init__.py

Sets up paths for integration with main project before importing components.
"""
import sys
from pathlib import Path

# Add main project root to path for vectorization agent graph access
# Path: models/anomaly-detection/src/components/__init__.py -> go up 4 levels to Sri Lanka AI Challenge 2026
# Note: This is secondary to anomaly-detection path. Direct graph import won't work
# due to 'src' namespace collision. Use VectorizationAPI HTTP calls instead.
_main_project_root = Path(__file__).parent.parent.parent.parent.parent
_main_path = str(_main_project_root)
if _main_path not in sys.path:
    sys.path.append(_main_path)  # Append, don't insert at 0

from .data_ingestion import DataIngestion
from .data_validation import DataValidation
from .data_transformation import DataTransformation
from .model_trainer import ModelTrainer

__all__ = [
    "DataIngestion",
    "DataValidation",
    "DataTransformation",
    "ModelTrainer"
]


import os
import numpy as np

"""
Defining common constant variable for training pipeline
"""

# Top 10 Sri Lankan Stocks by market cap (CSE - Colombo Stock Exchange)
# NOTE: Yahoo Finance does NOT support CSE tickers directly.
# These stocks will use fallback predictions with simulated market data.
# For real CSE data, integrate with CSE API or data providers like Bloomberg.
STOCKS_TO_TRAIN = {
    "COMB": {
        "yahoo_symbol": "COMB.N0000",  # Commercial Bank of Ceylon
        "name": "Commercial Bank of Ceylon PLC",
        "sector": "Banking",
        "exchange": "CSE"
    },
    "JKH": {
        "yahoo_symbol": "JKH.N0000",  # John Keells Holdings
        "name": "John Keells Holdings PLC",
        "sector": "Diversified Holdings",
        "exchange": "CSE"
    },
    "SAMP": {
        "yahoo_symbol": "SAMP.N0000",  # Sampath Bank
        "name": "Sampath Bank PLC",
        "sector": "Banking",
        "exchange": "CSE"
    },
    "HNB": {
        "yahoo_symbol": "HNB.N0000",  # Hatton National Bank
        "name": "Hatton National Bank PLC",
        "sector": "Banking",
        "exchange": "CSE"
    },
    "DIAL": {
        "yahoo_symbol": "DIAL.N0000",  # Dialog Axiata
        "name": "Dialog Axiata PLC",
        "sector": "Telecommunications",
        "exchange": "CSE"
    },
    "CTC": {
        "yahoo_symbol": "CTC.N0000",  # Ceylon Tobacco
        "name": "Ceylon Tobacco Company PLC",
        "sector": "Consumer Goods",
        "exchange": "CSE"
    },
    "NEST": {
        "yahoo_symbol": "NEST.N0000",  # Nestle Lanka
        "name": "Nestle Lanka PLC",
        "sector": "Consumer Goods",
        "exchange": "CSE"
    },
    "CARG": {
        "yahoo_symbol": "CARG.N0000",  # Cargills Ceylon
        "name": "Cargills Ceylon PLC",
        "sector": "Retail",
        "exchange": "CSE"
    },
    "HNBA": {
        "yahoo_symbol": "HNBA.N0000",  # HNB Assurance
        "name": "HNB Assurance PLC",
        "sector": "Insurance",
        "exchange": "CSE"
    },
    "CARS": {
        "yahoo_symbol": "CARS.N0000",  # Carson Cumberbatch
        "name": "Carson Cumberbatch PLC",
        "sector": "Diversified Holdings",
        "exchange": "CSE"
    }
}

# Default stock for single-stock training mode
DEFAULT_STOCK = "COMB"

# Legacy alias for backward compatibility
SRI_LANKA_STOCKS = STOCKS_TO_TRAIN
AVAILABLE_TEST_STOCKS = STOCKS_TO_TRAIN

TARGET_COLUMN="Close"
PIPELINE_NAME:str = "StockPricePrediction"
ARTIFACT_DIR:str = "Artifacts"

TRAIN_FILE_NAME:str = "train.csv"
TEST_FILE_NAME: str = "test.csv"


SCHEMA_FILE_PATH=os.path.join("data_schema", "schema.yaml")

SAVED_MODEL_DIR=os.path.join("saved_models")
MODEL_FILE_NAME= "model.pkl"

"""
Data Ingestion related constant start with DATA_INGESTION VAR NAME
"""

DATA_INGESTION_COLLECTION_NAME: str ="NetworkData"
DATA_INGESTION_DATABASE_NAME: str ="NIVAAI"
DATA_INGESTION_DIR_NAME: str = "data_ingestion"
DATA_INGESTION_FEATURE_STORE_DIR: str = "feature_store"
FILE_NAME: str = "stock_data.csv"  # Single stock file name
DATA_INGESTION_INGESTED_DIR: str = "ingested"
DATA_INGESTION_TRAIN_TEST_SPLIT_RATION: float = 0.2

"""
Data Validation related constant start with DATA_VALIDATION VAR NAME
"""
DATA_VALIDATION_DIR_NAME:str = "data_validation"
DATA_VALIDATION_VALID_DIR: str = "validated"
DATA_VALIDATION_INVALID_DIR: str = "invalid"
DATA_VALIDATION_DRIFT_REPORT_DIR: str = "drift_report"
DATA_VALIDATION_DRIFT_REPORT_FILE_NAME:str = "report.yaml"
PREPROCESSING_OBJECT_FILE_NAME:str="preprocessing.pkl"
"""
Data Transformation related constant start with DATA_TRANSFORMATION VAR NAME
"""

DATA_TRANSFORMATION_DIR_NAME: str = "data_transformation"
DATA_TRANSFORMATION_TRANSFORMED_DATA_DIR: str="transformed"
DATA_TRANSFORMATION_TRANSFORMED_OBJECT_DIR: str="transformed_object"

## Knn imputer class to replace nan values
DATA_TRANSFORMATION_IMPUTER_PARAMS: dict={
    "missing_values": np.nan,
    "n_neighbors": 3,
    "weights": "uniform"
}


DATA_TRANSFORMATION_TRAIN_FILE_PATH:str = "train.npy"
DATA_TRANSFORMATION_TEST_FILE_PATH:str = "test.npy"

"""
Model Trainer related content startt with MODEL_TRAINER VAR NAME
"""

MODEL_TRAINER_DIR_NAME:str = "model_trainer"
MODEL_TRAINER_TRAINED_MODEL_DIR:str="trained_model"
MODEL_TRAINER_TRAINED_MODEL_NAME: str="model.pkl"
MODEL_TRAINER_EXPECTED_SCORE: float=0.6
MODEL_TRAINER_OVERFITTING_UNDERFITTING_THRESHOLD: float=0.05


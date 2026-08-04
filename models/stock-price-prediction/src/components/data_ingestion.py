from src.exception.exception import StockPriceException
from src.logging.logger import logging

from src.entity.config_entity import DataIngestionConfig
from src.entity.artifact_entity import DataIngestionArtifact
from src.constants.training_pipeline import SRI_LANKA_STOCKS, DEFAULT_STOCK, AVAILABLE_TEST_STOCKS
import os
import sys
import numpy as np
import pandas as pd
import pymongo
from typing import List, Optional, Dict
from sklearn.model_selection import train_test_split
from dotenv import load_dotenv
load_dotenv()

import yfinance as yf
import datetime as dt

class DataIngestion:
    def __init__(self, data_ingestion_config: DataIngestionConfig, stock_code: str = None):
        """
        Initialize DataIngestion with optional stock_code parameter.
        
        Args:
            data_ingestion_config: Pipeline configuration
            stock_code: Stock code (e.g., 'AAPL', 'COMB', 'JKH'). If None, uses DEFAULT_STOCK.
        """
        try:
            self.data_ingestion_config = data_ingestion_config
            self.stock_code = stock_code or DEFAULT_STOCK

            # Get stock info - check test stocks first (globally available), then CSE stocks
            if self.stock_code in AVAILABLE_TEST_STOCKS:
                self.stock_info = AVAILABLE_TEST_STOCKS[self.stock_code]
                self.yahoo_symbol = self.stock_info["yahoo_symbol"]
            elif self.stock_code in SRI_LANKA_STOCKS:
                self.stock_info = SRI_LANKA_STOCKS[self.stock_code]
                self.yahoo_symbol = self.stock_info["yahoo_symbol"]
            else:
                # Fallback - use stock_code directly as Yahoo symbol
                self.yahoo_symbol = self.stock_code
                self.stock_info = {"name": self.stock_code, "sector": "Unknown"}

            logging.info(f"DataIngestion initialized for stock: {self.stock_code} ({self.yahoo_symbol})")
        except Exception as e:
            raise StockPriceException(e, sys)

    def export_collection_as_dataframe(self) -> pd.DataFrame:
        """
        Download stock data from Yahoo Finance for the configured stock.
        
        Returns:
            DataFrame with OHLCV data
        """
        try:
            start = dt.datetime(2000, 1, 1)
            end = dt.datetime.now()

            logging.info(f"Downloading {self.stock_code} ({self.yahoo_symbol}) from {start.date()} to {end.date()}")
            df = yf.download(self.yahoo_symbol, start=start, end=end, auto_adjust=True)

            # Handle multi-level columns (yfinance returns MultiIndex when downloading single stock)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
                logging.info("Flattened multi-level columns from yfinance")

            # Validate data is not empty
            if df.empty:
                raise Exception(f"No data returned from yfinance for {self.stock_code} ({self.yahoo_symbol}). Check ticker symbol.")

            # Reset index to make Date a column
            df = df.reset_index()

            # Ensure Date column is properly formatted
            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')

            # Remove any rows with non-numeric Close values
            df = df[pd.to_numeric(df['Close'], errors='coerce').notna()]

            # Add stock metadata columns
            df['StockCode'] = self.stock_code
            df['StockName'] = self.stock_info.get("name", self.stock_code)

            logging.info(f"✓ Downloaded {len(df)} rows for {self.stock_code}")

            df.replace({"na": np.nan}, inplace=True)
            return df
        except Exception as e:
            raise StockPriceException(e, sys)

    def export_data_into_feature_store(self,dataframe: pd.DataFrame):
        try:
            feature_store_file_path=self.data_ingestion_config.feature_store_file_path
            #creating folder
            dir_path = os.path.dirname(feature_store_file_path)
            os.makedirs(dir_path,exist_ok=True)
            dataframe.to_csv(feature_store_file_path, index=False, header=True)  # Date is now a column
            return dataframe

        except Exception as e:
            raise StockPriceException(e,sys)

    def split_data_as_train_test(self,dataframe: pd.DataFrame):
        try:
            train_set, test_set = train_test_split(
                dataframe, test_size=self.data_ingestion_config.train_test_split_ratio,
                shuffle=False  # CRITICAL: Don't shuffle for time series data!
            )
            logging.info("Performed train test split on the dataframe")

            logging.info(
                "Exited split_data_as_train_test method of Data_Ingestion class"
            )

            dir_path = os.path.dirname(self.data_ingestion_config.training_file_path)

            os.makedirs(dir_path, exist_ok=True)

            logging.info("Exporting train and test file path.")

            train_set.to_csv(
                self.data_ingestion_config.training_file_path, index=False, header=True  # Date is now a column
            )

            test_set.to_csv(
                self.data_ingestion_config.testing_file_path, index=False, header=True  # Date is now a column
            )
            logging.info("Exported train and test file path.")


        except Exception as e:
            raise StockPriceException(e,sys)


    def initiate_data_ingestion(self):
        try:
            dataframe=self.export_collection_as_dataframe()
            dataframe=self.export_data_into_feature_store(dataframe)
            self.split_data_as_train_test(dataframe)
            dataingestionartifact=DataIngestionArtifact(trained_file_path=self.data_ingestion_config.training_file_path,
                                                        test_file_path=self.data_ingestion_config.testing_file_path)
            return dataingestionartifact

        except Exception as e:
            raise StockPriceException(e, sys)

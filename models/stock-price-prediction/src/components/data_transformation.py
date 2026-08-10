
import sys
import os
import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler
from src.exception import StockPriceException
from src.logging.logger import logging
from src.entity.artifact_entity import (
    DataTransformationArtifact,
    DataValidationArtifact,
)
from src.entity.config_entity import DataTransformationConfig
from src.utils.main_utils.utils import save_object, save_numpy_array_data

class DataTransformation:
    def __init__(
        self,
        data_validation_artifact: DataValidationArtifact,
        data_transformation_config: DataTransformationConfig,
    ):
        try:
            self.data_validation_artifact = data_validation_artifact
            self.data_transformation_config = data_transformation_config
        except Exception as e:
            raise StockPriceException(e, sys)

    @staticmethod
    def read_data(file_path) -> pd.DataFrame:
        try:
            # Read CSV normally - Date is now a column, not the index
            df = pd.read_csv(file_path)
            return df
        except Exception as e:
            raise StockPriceException(e, sys)

    def create_dataset(self, dataset, time_step=1):
        try:
            dataX, dataY = [], []
            for i in range(len(dataset) - time_step - 1):
                a = dataset[i : (i + time_step), 0]
                dataX.append(a)
                dataY.append(dataset[i + time_step, 0])
            return np.array(dataX), np.array(dataY)
        except Exception as e:
            raise StockPriceException(e, sys)

    def initiate_data_transformation(self) -> DataTransformationArtifact:
        try:
            logging.info("Entered initiate_data_transformation method of DataTransformation class")

            train_file_path = self.data_validation_artifact.valid_train_file_path
            test_file_path = self.data_validation_artifact.valid_test_file_path

            train_df = DataTransformation.read_data(train_file_path)
            test_df = DataTransformation.read_data(test_file_path)

            logging.info(f"Read train and test data completed. Train shape: {train_df.shape}, Test shape: {test_df.shape}")

            # Focus on 'Close' price for prediction as per requirement
            target_column_name = "Close"

            if target_column_name not in train_df.columns:
                 raise Exception(f"Target column '{target_column_name}' not found in training data columns: {train_df.columns}")

            # Ensure target column is numeric, coercing errors (like Ticker strings) to NaN and dropping them
            train_df[target_column_name] = pd.to_numeric(train_df[target_column_name], errors='coerce')
            test_df[target_column_name] = pd.to_numeric(test_df[target_column_name], errors='coerce')

            train_df.dropna(subset=[target_column_name], inplace=True)
            test_df.dropna(subset=[target_column_name], inplace=True)

            # CRITICAL FIX: Combine train and test data BEFORE creating sequences
            # This ensures test sequences have proper historical context from training data
            combined_df = pd.concat([train_df, test_df], ignore_index=False)  # Keep original index

            # CRITICAL FIX #2: Sort by Date to restore temporal order
            # data_ingestion may shuffle data randomly, breaking time series order
            # Check if index is datetime-like or if there's a Date column
            if combined_df.index.name == 'Date' or 'Date' in str(combined_df.index.dtype):
                combined_df = combined_df.sort_index()
                logging.info("Sorted combined data by Date index")
            elif 'Date' in combined_df.columns:
                combined_df = combined_df.sort_values('Date')
                logging.info("Sorted combined data by Date column")
            else:
                # Try to parse index as datetime
                try:
                    combined_df.index = pd.to_datetime(combined_df.index)
                    combined_df = combined_df.sort_index()
                    logging.info("Converted index to datetime and sorted")
                except Exception:
                    logging.warning("Could not find Date column or parse index as date. Data may not be in temporal order!")

            combined_df = combined_df.reset_index(drop=True)  # Reset to numeric index after sorting

            # For proper train/test split, use 80/20 ratio on sorted data
            train_len = int(len(combined_df) * 0.8)
            logging.info(f"Combined data shape: {combined_df.shape}, Train portion: {train_len} rows (80%)")

            combined_data = combined_df[[target_column_name]].values

            logging.info("Applying MinMaxScaler on combined data")
            scaler = MinMaxScaler(feature_range=(0, 1))

            # Fit scaler on combined data for consistency
            combined_scaled = scaler.fit_transform(combined_data)

            # Create sliding window sequences on COMBINED data
            time_step = 60  # Reduced from 100 for better learning with available data
            logging.info(f"Creating sequences with time_step={time_step}")

            X_all, y_all = self.create_dataset(combined_scaled, time_step)

            if len(X_all) == 0:
                 raise Exception("Not enough data to create sequences. Increase data size or decrease time_step.")

            # Reshape input to be [samples, time steps, features] which is required for LSTM
            X_all = X_all.reshape(X_all.shape[0], X_all.shape[1], 1)

            # Split sequences chronologically based on original train/test ratio
            # Calculate split point: sequences from train portion vs test portion
            # Account for sequence creation: first valid sequence starts at index time_step
            train_sequence_end = train_len - time_step - 1

            if train_sequence_end <= 0:
                raise Exception(f"Not enough training data for time_step={time_step}")

            X_train = X_all[:train_sequence_end]
            y_train = y_all[:train_sequence_end]
            X_test = X_all[train_sequence_end:]
            y_test = y_all[train_sequence_end:]

            logging.info(f"Train sequences shape: {X_train.shape}, Train labels shape: {y_train.shape}")
            logging.info(f"Test sequences shape: {X_test.shape}, Test labels shape: {y_test.shape}")

            if len(X_test) == 0:
                raise Exception("Not enough test data after splitting. Reduce time_step or increase data.")

            # Save scaler
            save_object(
                self.data_transformation_config.transformed_object_file_path, scaler
            )

            # Save as tuple (X, y) using save_object (pickle)
            save_object(
                self.data_transformation_config.transformed_train_file_path,
                (X_train, y_train)
            )
            save_object(
                self.data_transformation_config.transformed_test_file_path,
                (X_test, y_test)
            )

            data_transformation_artifact = DataTransformationArtifact(
                transformed_object_file_path=self.data_transformation_config.transformed_object_file_path,
                transformed_train_file_path=self.data_transformation_config.transformed_train_file_path,
                transformed_test_file_path=self.data_transformation_config.transformed_test_file_path,
            )

            logging.info(f"Data transformation artifact: {data_transformation_artifact}")
            return data_transformation_artifact
        except Exception as e:
            raise StockPriceException(e, sys)

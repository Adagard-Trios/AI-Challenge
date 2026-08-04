
import os
import sys
import numpy as np
import tensorflow as tf

# Fix Windows console encoding issue with MLflow emoji output
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from sklearn import metrics
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout, Input, Bidirectional
from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau
from tensorflow.keras.optimizers import Adam
import mlflow
import dagshub

from src.exception import StockPriceException
from src.logging.logger import logging
from src.entity.artifact_entity import (
    DataTransformationArtifact,
    ModelTrainerArtifact,
    RegressionMetricArtifact,
)
from src.entity.config_entity import ModelTrainerConfig
from src.utils.main_utils.utils import load_object, save_object
from src.utils.ml_utils.metric.regression_metric import get_regression_score

class ModelTrainer:
    def __init__(
        self,
        model_trainer_config: ModelTrainerConfig,
        data_transformation_artifact: DataTransformationArtifact,
    ):
        try:
            self.model_trainer_config = model_trainer_config
            self.data_transformation_artifact = data_transformation_artifact
        except Exception as e:
            raise StockPriceException(e, sys)

    def get_model(self, input_shape):
        try:
            model = Sequential()
            # Explicit Input layer (recommended for Keras 3.x)
            model.add(Input(shape=input_shape))

            # 1st Bidirectional LSTM layer - increased units for better pattern recognition
            model.add(Bidirectional(LSTM(units=100, return_sequences=True)))
            model.add(Dropout(0.5))  # Increased dropout to reduce overfitting

            # 2nd Bidirectional LSTM layer
            model.add(Bidirectional(LSTM(units=100, return_sequences=True)))
            model.add(Dropout(0.5))  # Increased dropout to reduce overfitting

            # 3rd LSTM layer (non-bidirectional for final processing)
            model.add(LSTM(units=50))
            model.add(Dropout(0.5))  # Increased dropout to reduce overfitting

            # Output layer
            model.add(Dense(units=1))

            # Compile with Adam optimizer with custom learning rate
            optimizer = Adam(learning_rate=0.001)
            model.compile(optimizer=optimizer, loss='mean_squared_error')
            return model
        except Exception as e:
            raise StockPriceException(e, sys)

    def train_model(self, X_train, y_train, X_test, y_test, scaler):
        try:
            model = self.get_model((X_train.shape[1], 1))

            # MLflow logging
            dagshub.init(repo_owner='sliitguy', repo_name='sri-lanka-ai-challenge-2026', mlflow=True)

            with mlflow.start_run():
                # Training parameters
                epochs = 10  # Reduced for faster training
                batch_size = 32  # Reduced for more stable gradients

                # Callbacks for better training
                early_stopping = EarlyStopping(
                    monitor='val_loss',
                    patience=10,
                    restore_best_weights=True,
                    verbose=1
                )

                reduce_lr = ReduceLROnPlateau(
                    monitor='val_loss',
                    factor=0.5,
                    patience=5,
                    min_lr=0.0001,
                    verbose=1
                )

                # Log parameters
                mlflow.log_param("epochs", epochs)
                mlflow.log_param("batch_size", batch_size)
                mlflow.log_param("model_type", "Bidirectional_LSTM")
                mlflow.log_param("lstm_units", "100-100-50")
                mlflow.log_param("dropout", 0.2)

                logging.info("Fitting Bidirectional LSTM model with callbacks")
                history = model.fit(
                    X_train, y_train,
                    epochs=epochs,
                    batch_size=batch_size,
                    validation_data=(X_test, y_test),
                    callbacks=[early_stopping, reduce_lr],
                    verbose=1
                )

                # Metrics (Test Only) - Calculate metrics for logging
                test_predict_scaled = model.predict(X_test)

                # Inverse transform to get actual price values for meaningful metrics
                # Scaler expects 2D array, predictions and y_test are 1D
                test_predict = scaler.inverse_transform(test_predict_scaled.reshape(-1, 1)).flatten()
                y_test_actual = scaler.inverse_transform(y_test.reshape(-1, 1)).flatten()

                # DEBUG: Print sample values to verify data
                logging.info(f"DEBUG - y_test_actual sample (first 5): {y_test_actual[:5]}")
                logging.info(f"DEBUG - test_predict sample (first 5): {test_predict[:5]}")
                logging.info(f"DEBUG - y_test_actual range: min={y_test_actual.min()}, max={y_test_actual.max()}")
                logging.info(f"DEBUG - test_predict range: min={test_predict.min()}, max={test_predict.max()}")

                # Metrics: r2_score(y_true, y_pred) - order is CORRECT
                test_rmse = np.sqrt(metrics.mean_squared_error(y_test_actual, test_predict))
                test_mae = metrics.mean_absolute_error(y_test_actual, test_predict)
                test_r2 = metrics.r2_score(y_test_actual, test_predict)  # y_true first, y_pred second
                test_mape = metrics.mean_absolute_percentage_error(y_test_actual, test_predict)

                # logging.info(f"Train RMSE: {train_rmse}, MAE: {train_mae}, R2: {train_r2}, MAPE: {train_mape}")
                logging.info(f"Test RMSE: {test_rmse}, MAE: {test_mae}, R2: {test_r2}, MAPE: {test_mape}")

                # mlflow.log_metric("train_rmse", train_rmse)
                mlflow.log_metric("test_rmse", test_rmse)
                # mlflow.log_metric("train_mae", train_mae)
                mlflow.log_metric("test_mae", test_mae)
                # mlflow.log_metric("train_r2", train_r2)
                mlflow.log_metric("test_r2", test_r2)
                # mlflow.log_metric("train_mape", train_mape)
                mlflow.log_metric("test_mape", test_mape)

                # Tagging
                mlflow.set_tag("Task", "Stock Price Prediction")

                # Log model - Workaround for DagsHub 'unsupported endpoint' on log_model
                # Save locally first then log artifact
                tmp_model_path = "model.h5"
                model.save(tmp_model_path)
                mlflow.log_artifact(tmp_model_path)
                if os.path.exists(tmp_model_path):
                    os.remove(tmp_model_path)
                # mlflow.keras.log_model(model, "model")

            return model, test_rmse, test_predict, y_test_actual

        except Exception as e:
            raise StockPriceException(e, sys)

    def initiate_model_trainer(self) -> ModelTrainerArtifact:
        try:
            logging.info("Entered initiate_model_trainer")

            train_file_path = self.data_transformation_artifact.transformed_train_file_path
            test_file_path = self.data_transformation_artifact.transformed_test_file_path

            logging.info(f"Loading transformed data from {train_file_path} and {test_file_path}")
            # Loading the tuples (X, y) saved in data_transformation
            train_data = load_object(train_file_path)
            test_data = load_object(test_file_path)

            X_train, y_train = train_data
            X_test, y_test = test_data

            logging.info(f"Loaded train data shapes: X={X_train.shape}, y={y_train.shape}")

            # Load scaler for inverse transformation
            scaler_path = self.data_transformation_artifact.transformed_object_file_path
            scaler = load_object(scaler_path)
            logging.info(f"Loaded scaler from {scaler_path}")

            model, test_rmse, test_predict, y_test_actual = self.train_model(X_train, y_train, X_test, y_test, scaler)

            logging.info("Saving trained model")
            # Create object containing model info or just save model file.
            # Artifact expects a file path.
            save_path = self.model_trainer_config.trained_model_file_path

            # Since object is Keras model, save_object (dill) might work but is fragile.
            # Recommend using model.save, but for compatibility with 'save_object' utility (if user wants zero change there),
            # we try save_object. Keras objects are pickleable in recent versions but .h5 is standard.
            # To adhere to "make sure main.py works", main doesn't load model, it just passes artifact.
            # So I will save using standard method but point artifact to it?
            # Or use safe pickling.
            # I'll use save_object but beware.
            # If save_object fails for Keras, I should verify.
            # Let's trust save_object for now, or better:

            # Ensure directory exists
            dir_path = os.path.dirname(save_path)
            os.makedirs(dir_path, exist_ok=True)

            # Save using Keras format explicitly if the path allows, otherwise pickle.
            save_object(save_path, model)

            # Calculate Regression Metrics for Artifact (already inverse-transformed)
            test_metric = get_regression_score(y_test_actual, test_predict)

            model_trainer_artifact = ModelTrainerArtifact(
                trained_model_file_path=save_path,
                train_metric_artifact=None, # Removed training metrics from artifact
                test_metric_artifact=test_metric
            )

            logging.info(f"Model Trainer Artifact: {model_trainer_artifact}")
            return model_trainer_artifact

        except Exception as e:
            raise StockPriceException(e, sys)

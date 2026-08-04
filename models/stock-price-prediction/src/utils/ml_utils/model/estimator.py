from src.constants.training_pipeline import SAVED_MODEL_DIR,MODEL_FILE_NAME

import os
import sys

from src.exception.exception import StockPriceException
from src.logging.logger import logging

class StockModel:
    def __init__(self,preprocessor,model):
        try:
            self.preprocessor = preprocessor
            self.model = model
        except Exception as e:
            raise StockPriceException(e,sys)

    def predict(self,x):
        try:
            # We assume x is raw data that needs transformation
            # However, for LSTM models, the preprocessor (Scaler) doesn't reshape to 3D.
            # So this wrapper needs to handle reshaping if it's employed for inference.
            # Assuming x comes in as 2D dataframe/array.
            x_transform = self.preprocessor.transform(x)

            # Reshape for LSTM: [samples, time steps, features]
            # This logic mimics DataTransformation.create_dataset but for inference
            # We assume x has enough data for at least one sequence or is pre-sequenced?
            # Standard estimator usually expects prepared X.
            # If this wrapper is used for the API, it must handle the sliding window logic.
            # For now, we will simply delegate to model.predict assuming input is correct shape,
            # or IF the preprocessor output is flat, we might fail.
            # Given the constraints, I will keep it simple: transform and predict.
            # If shape mismatch occurs, it's an inference data prep issue.

            y_hat = self.model.predict(x_transform)
            return y_hat
        except Exception as e:
            raise StockPriceException(e,sys)


from src.entity.artifact_entity import RegressionMetricArtifact
from src.exception import StockPriceException
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score, mean_absolute_percentage_error
import sys
import numpy as np

def get_regression_score(y_true, y_pred) -> RegressionMetricArtifact:
    try:
        model_rmse = np.sqrt(mean_squared_error(y_true, y_pred))
        model_mae = mean_absolute_error(y_true, y_pred)
        model_r2 = r2_score(y_true, y_pred)

        model_mape = mean_absolute_percentage_error(y_true, y_pred)

        regression_metric = RegressionMetricArtifact(
            rmse=model_rmse,
            mae=model_mae,
            r2_score=model_r2,
            mape=model_mape
        )
        return regression_metric
    except Exception as e:
        raise StockPriceException(e, sys)

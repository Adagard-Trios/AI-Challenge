"""
Stock Prediction DAG
Runs daily at 4:15 AM IST (22:45 UTC)
Trains BiLSTM models for 10 stocks
"""
import os
import sys
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
STOCK_MODEL_PATH = PROJECT_ROOT / "models" / "stock-price-prediction"

default_args = {
    "owner": "Sri Lanka AI Challenge 2026",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
}


def run_stock_training(**context):
    """Run the multi-stock training pipeline."""
    main_py = STOCK_MODEL_PATH / "main.py"
    
    if not main_py.exists():
        raise FileNotFoundError(f"Stock training script not found: {main_py}")
    
    result = subprocess.run(
        [sys.executable, str(main_py)],
        capture_output=True,
        text=True,
        cwd=str(STOCK_MODEL_PATH)
    )
    
    print("STDOUT:", result.stdout[-5000:] if len(result.stdout) > 5000 else result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr[-2000:])
    
    if result.returncode != 0:
        raise Exception(f"Stock training failed with exit code {result.returncode}")
    
    return True


with DAG(
    dag_id="stock_prediction_daily",
    default_args=default_args,
    description="Daily stock prediction for 10 stocks using BiLSTM",
    schedule_interval="45 22 * * *",  # 4:15 AM IST = 22:45 UTC (staggered)
    start_date=datetime(2024, 12, 1),
    catchup=False,
    tags=["stock", "ml", "prediction", "lstm", "daily"],
    max_active_runs=1,
) as dag:
    
    train_stocks = PythonOperator(
        task_id="train_all_stocks",
        python_callable=run_stock_training,
        provide_context=True,
        execution_timeout=timedelta(hours=4),  # 10 stocks take time
    )


if __name__ == "__main__":
    print(f"Stock Prediction DAG - Schedule: 4:15 AM IST daily")

"""
Currency Prediction DAG
Runs daily at 4:00 AM IST (22:30 UTC)
Trains GRU model for USD/LKR exchange rate prediction
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
CURRENCY_MODEL_PATH = PROJECT_ROOT / "models" / "currency-volatility-prediction"

default_args = {
    "owner": "Sri Lanka AI Challenge 2026",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
}


def run_currency_training(**context):
    """Run the currency prediction training pipeline."""
    main_py = CURRENCY_MODEL_PATH / "main.py"
    
    if not main_py.exists():
        raise FileNotFoundError(f"Currency training script not found: {main_py}")
    
    result = subprocess.run(
        [sys.executable, str(main_py), "--mode", "full"],
        capture_output=True,
        text=True,
        cwd=str(CURRENCY_MODEL_PATH)
    )
    
    print("STDOUT:", result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr[-1000:])
    
    if result.returncode != 0:
        raise Exception(f"Currency training failed with exit code {result.returncode}")
    
    return True


with DAG(
    dag_id="currency_prediction_daily",
    default_args=default_args,
    description="Daily USD/LKR exchange rate prediction using GRU model",
    schedule_interval="35 22 * * *",  # 4:05 AM IST = 22:35 UTC (staggered)
    start_date=datetime(2024, 12, 1),
    catchup=False,
    tags=["currency", "ml", "prediction", "gru", "daily", "forex"],
    max_active_runs=1,
) as dag:
    
    train_currency = PythonOperator(
        task_id="train_currency_model",
        python_callable=run_currency_training,
        provide_context=True,
        execution_timeout=timedelta(hours=1),
    )


if __name__ == "__main__":
    print(f"Currency Prediction DAG - Schedule: 4:05 AM IST daily")

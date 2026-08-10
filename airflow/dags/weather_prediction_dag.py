"""
Weather Prediction DAG
Runs daily at 4:00 AM IST (22:30 UTC)
Trains LSTM model for 25 Sri Lankan districts
"""
import os
import sys
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
WEATHER_MODEL_PATH = PROJECT_ROOT / "models" / "weather-prediction"

default_args = {
    "owner": "Sri Lanka AI Challenge 2026",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
}


def run_weather_training(**context):
    """Run the weather prediction training pipeline."""
    main_py = WEATHER_MODEL_PATH / "main.py"
    
    if not main_py.exists():
        raise FileNotFoundError(f"Weather training script not found: {main_py}")
    
    result = subprocess.run(
        [sys.executable, str(main_py), "--mode", "full"],
        capture_output=True,
        text=True,
        cwd=str(WEATHER_MODEL_PATH)
    )
    
    print("STDOUT:", result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr[-1000:])
    
    if result.returncode != 0:
        raise Exception(f"Weather training failed with exit code {result.returncode}")
    
    return True


with DAG(
    dag_id="weather_prediction_daily",
    default_args=default_args,
    description="Daily weather prediction model training for 25 Sri Lankan districts",
    schedule_interval="30 22 * * *",  # 4:00 AM IST = 22:30 UTC
    start_date=datetime(2024, 12, 1),
    catchup=False,
    tags=["weather", "ml", "prediction", "lstm", "daily"],
    max_active_runs=1,
) as dag:
    
    train_weather = PythonOperator(
        task_id="train_weather_model",
        python_callable=run_weather_training,
        provide_context=True,
        execution_timeout=timedelta(hours=2),
    )


if __name__ == "__main__":
    print(f"Weather Prediction DAG - Schedule: 4:00 AM IST daily")

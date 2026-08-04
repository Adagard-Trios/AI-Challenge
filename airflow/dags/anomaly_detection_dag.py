"""
Anomaly Detection DAG
Runs every 6 hours
Retrains anomaly detection model on latest data
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
ANOMALY_MODEL_PATH = PROJECT_ROOT / "models" / "anomaly-detection"

default_args = {
    "owner": "Sri Lanka AI Challenge 2026",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def run_anomaly_training(**context):
    """Run the anomaly detection training pipeline."""
    main_py = ANOMALY_MODEL_PATH / "main.py"
    
    if not main_py.exists():
        raise FileNotFoundError(f"Anomaly training script not found: {main_py}")
    
    result = subprocess.run(
        [sys.executable, str(main_py)],
        capture_output=True,
        text=True,
        cwd=str(ANOMALY_MODEL_PATH)
    )
    
    print("STDOUT:", result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr[-1000:])
    
    if result.returncode != 0:
        raise Exception(f"Anomaly training failed with exit code {result.returncode}")
    
    return True


with DAG(
    dag_id="anomaly_detection_periodic",
    default_args=default_args,
    description="Periodic anomaly detection model retraining",
    schedule_interval="0 */6 * * *",  # Every 6 hours
    start_date=datetime(2024, 12, 1),
    catchup=False,
    tags=["anomaly", "ml", "detection", "periodic"],
    max_active_runs=1,
) as dag:
    
    train_anomaly = PythonOperator(
        task_id="train_anomaly_model",
        python_callable=run_anomaly_training,
        provide_context=True,
        execution_timeout=timedelta(minutes=30),
    )


if __name__ == "__main__":
    print(f"Anomaly Detection DAG - Schedule: Every 6 hours")

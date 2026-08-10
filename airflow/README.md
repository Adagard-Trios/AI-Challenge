# Sri Lanka AI Challenge 2026 Astro Airflow

Centralized Apache Airflow setup using Astronomer's Astro CLI for managing all ML pipelines.

## DAGs Overview

| DAG | Schedule | Description |
|-----|----------|-------------|
| `weather_prediction_daily` | 4:00 AM IST | LSTM model for 25 Sri Lankan districts |
| `currency_prediction_daily` | 4:05 AM IST | GRU model for USD/LKR forex |
| `stock_prediction_daily` | 4:15 AM IST | BiLSTM models for 10 stocks |
| `anomaly_detection_periodic` | Every 6h | Anomaly detection retraining |

## Quick Start

### 1. Install Astro CLI
```bash
# macOS
brew install astro

# Windows (PowerShell as Admin)
winget install -e --id Astronomer.Astro

# Linux
curl -sSL install.astronomer.io | sudo bash -s
```

### 2. Start Airflow
```bash
cd airflow
astro dev start
```

### 3. Access Airflow UI
- URL: http://localhost:8080
- Username: `admin`
- Password: `admin`

### 4. Enable DAGs
Turn on the DAGs in the Airflow UI to start scheduled runs.

## Directory Structure
```
airflow/
├── dags/
│   ├── weather_prediction_dag.py
│   ├── currency_prediction_dag.py
│   ├── stock_prediction_dag.py
│   └── anomaly_detection_dag.py
├── Dockerfile
├── requirements.txt
├── airflow.env.example
└── README.md
```

## Manual Trigger
```bash
# Trigger a specific DAG
astro dev run dags trigger weather_prediction_daily
```

## Logs
```bash
# View scheduler logs
astro dev logs --scheduler

# View webserver logs
astro dev logs --webserver
```

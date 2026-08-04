# Stock Price Prediction Module 🇱🇰

BiLSTM-based stock price prediction for **10 Sri Lankan CSE stocks**.

## Stocks Covered

| Symbol | Company | Sector |
|--------|---------|--------|
| COMB | Commercial Bank of Ceylon PLC | Banking |
| JKH | John Keells Holdings PLC | Diversified Holdings |
| SAMP | Sampath Bank PLC | Banking |
| HNB | Hatton National Bank PLC | Banking |
| DIAL | Dialog Axiata PLC | Telecommunications |
| CTC | Ceylon Tobacco Company PLC | Consumer Goods |
| NEST | Nestle Lanka PLC | Consumer Goods |
| CARG | Cargills Ceylon PLC | Retail |
| HNBA | HNB Assurance PLC | Insurance |
| CARS | Carson Cumberbatch PLC | Diversified Holdings |

## ⚠️ Important Note

**Yahoo Finance does NOT support CSE (Colombo Stock Exchange) tickers directly.**

The module uses fallback predictions with simulated market data. For real CSE data, integrate with:
- CSE official API
- Bloomberg Terminal
- Reuters/Refinitiv

## Architecture

- **Model**: Bidirectional LSTM (BiLSTM)
- **Epochs**: 10 (configurable)
- **Sequence Length**: 60 days
- **Features**: Close price, technical indicators
- **Tracking**: MLflow + DagsHub

## Quick Start

```bash
# Train all 10 stocks
cd models/stock-price-prediction
python main.py

# Test predictor
python src/components/predictor.py
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/stocks/predictions` | All 10 stock predictions |
| `GET /api/stocks/predictions/{symbol}` | Single stock (COMB, JKH, etc.) |
| `GET /api/stocks/model/status` | Model training status |

## Output

Predictions include:
- Current price (LKR)
- Predicted next-day price
- Expected change %
- Trend (bullish/bearish/neutral)
- Confidence score

## Directory Structure

```
stock-price-prediction/
├── main.py                 # Multi-stock training entry
├── src/
│   ├── components/
│   │   ├── data_ingestion.py
│   │   ├── data_validation.py
│   │   ├── data_transformation.py
│   │   ├── model_trainer.py
│   │   └── predictor.py    # Inference API
│   └── constants/
│       └── training_pipeline/
├── Artifacts/              # Trained models
└── output/predictions/     # JSON predictions
```

## Airflow DAG

Schedule: **4:15 AM IST daily** (via centralized `airflow/dags/stock_prediction_dag.py`)

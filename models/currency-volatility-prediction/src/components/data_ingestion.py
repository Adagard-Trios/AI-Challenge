"""
models/currency-volatility-prediction/src/components/data_ingestion.py
Data Ingestion for LKR/USD Currency Prediction using yfinance
"""
import os
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np

# yfinance for currency data
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    print("[WARNING] yfinance not available. Install with: pip install yfinance")

sys.path.insert(0, str(Path(__file__).parent.parent))

from entity.config_entity import DataIngestionConfig, ECONOMIC_INDICATORS

logger = logging.getLogger("currency_prediction.data_ingestion")


class CurrencyDataIngestion:
    """
    Ingests LKR/USD exchange rate data and economic indicators from yfinance.
    
    Features collected:
    - USD/LKR exchange rate (primary)
    - CSE stock index (correlation)
    - Gold, Oil prices (global factors)
    - USD strength index
    - Regional currencies (INR)
    """

    def __init__(self, config: Optional[DataIngestionConfig] = None):
        if not YFINANCE_AVAILABLE:
            raise RuntimeError("yfinance is required. Install: pip install yfinance")

        self.config = config or DataIngestionConfig()
        os.makedirs(self.config.raw_data_dir, exist_ok=True)

    def fetch_currency_data(
        self,
        symbol: str = "USDLKR=X",
        period: str = "2y"
    ) -> pd.DataFrame:
        """
        Fetch historical currency data from yfinance.
        
        Args:
            symbol: Yahoo Finance symbol (USDLKR=X for USD to LKR)
            period: Data period (1y, 2y, 5y, max)
            
        Returns:
            DataFrame with OHLCV data
        """
        logger.info(f"[CURRENCY] Fetching {symbol} data for {period}...")

        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval="1d")

            if df.empty:
                logger.warning(f"[CURRENCY] No data for {symbol}, trying alternative...")
                # Try alternative symbol format
                alt_symbol = "LKR=X" if "USD" in symbol else symbol
                ticker = yf.Ticker(alt_symbol)
                df = ticker.history(period=period, interval="1d")

            if df.empty:
                raise ValueError(f"No data available for {symbol}")

            # Standardize column names
            df = df.reset_index()
            df.columns = [c.lower().replace(" ", "_") for c in df.columns]

            # Keep essential columns
            keep_cols = ["date", "open", "high", "low", "close", "volume"]
            df = df[[c for c in keep_cols if c in df.columns]]

            # Add symbol identifier
            df["symbol"] = symbol

            logger.info(f"[CURRENCY] ✓ Fetched {len(df)} records for {symbol}")
            return df

        except Exception as e:
            logger.error(f"[CURRENCY] Error fetching {symbol}: {e}")
            return pd.DataFrame()

    def fetch_indicators(self) -> Dict[str, pd.DataFrame]:
        """
        Fetch economic indicators data.
        
        Returns:
            Dictionary of DataFrames by indicator name
        """
        indicators_data = {}

        for name, config in self.config.indicators.items():
            logger.info(f"[INDICATORS] Fetching {name} ({config['yahoo_symbol']})...")

            try:
                df = self.fetch_currency_data(
                    symbol=config["yahoo_symbol"],
                    period=self.config.history_period
                )

                if not df.empty:
                    # Rename columns with prefix
                    df = df.rename(columns={
                        "close": f"{name}_close",
                        "open": f"{name}_open",
                        "high": f"{name}_high",
                        "low": f"{name}_low",
                        "volume": f"{name}_volume"
                    })
                    indicators_data[name] = df
                    logger.info(f"[INDICATORS] ✓ {name}: {len(df)} records")
                else:
                    logger.warning(f"[INDICATORS] ✗ No data for {name}")

            except Exception as e:
                logger.warning(f"[INDICATORS] Error fetching {name}: {e}")

        return indicators_data

    def merge_all_data(
        self,
        currency_df: pd.DataFrame,
        indicators: Dict[str, pd.DataFrame]
    ) -> pd.DataFrame:
        """
        Merge currency data with economic indicators.
        
        Args:
            currency_df: Primary USD/LKR data
            indicators: Dictionary of indicator DataFrames
            
        Returns:
            Merged DataFrame with all features
        """
        if currency_df.empty:
            raise ValueError("Primary currency data is empty")

        # Start with currency data
        merged = currency_df.copy()
        merged["date"] = pd.to_datetime(merged["date"]).dt.tz_localize(None)

        # Merge each indicator
        for name, ind_df in indicators.items():
            if ind_df.empty:
                continue

            ind_df = ind_df.copy()
            ind_df["date"] = pd.to_datetime(ind_df["date"]).dt.tz_localize(None)

            # Select only relevant columns
            merge_cols = ["date"] + [c for c in ind_df.columns if name in c.lower()]
            ind_subset = ind_df[merge_cols].drop_duplicates(subset=["date"])

            merged = merged.merge(ind_subset, on="date", how="left")

        # Sort by date
        merged = merged.sort_values("date").reset_index(drop=True)

        # Forward fill missing indicator values
        merged = merged.ffill()

        logger.info(f"[MERGE] Combined data: {len(merged)} rows, {len(merged.columns)} columns")
        return merged

    def add_technical_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add technical analysis features.
        
        Args:
            df: DataFrame with price data
            
        Returns:
            DataFrame with additional features
        """
        df = df.copy()

        # Price-based features
        df["daily_return"] = df["close"].pct_change()
        df["daily_range"] = (df["high"] - df["low"]) / df["close"]

        # Moving averages
        df["sma_5"] = df["close"].rolling(window=5).mean()
        df["sma_10"] = df["close"].rolling(window=10).mean()
        df["sma_20"] = df["close"].rolling(window=20).mean()

        # EMA
        df["ema_5"] = df["close"].ewm(span=5).mean()
        df["ema_10"] = df["close"].ewm(span=10).mean()

        # Volatility
        df["volatility_5"] = df["daily_return"].rolling(window=5).std()
        df["volatility_20"] = df["daily_return"].rolling(window=20).std()

        # Momentum
        df["momentum_5"] = df["close"] / df["close"].shift(5) - 1
        df["momentum_10"] = df["close"] / df["close"].shift(10) - 1

        # RSI (14-day)
        delta = df["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df["rsi_14"] = 100 - (100 / (1 + rs))

        # MACD
        ema_12 = df["close"].ewm(span=12).mean()
        ema_26 = df["close"].ewm(span=26).mean()
        df["macd"] = ema_12 - ema_26
        df["macd_signal"] = df["macd"].ewm(span=9).mean()

        # Bollinger Bands
        df["bb_middle"] = df["close"].rolling(window=20).mean()
        bb_std = df["close"].rolling(window=20).std()
        df["bb_upper"] = df["bb_middle"] + 2 * bb_std
        df["bb_lower"] = df["bb_middle"] - 2 * bb_std
        df["bb_position"] = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])

        # Day of week (cyclical encoding)
        df["day_of_week"] = pd.to_datetime(df["date"]).dt.dayofweek
        df["day_sin"] = np.sin(2 * np.pi * df["day_of_week"] / 7)
        df["day_cos"] = np.cos(2 * np.pi * df["day_of_week"] / 7)

        # Month (cyclical)
        df["month"] = pd.to_datetime(df["date"]).dt.month
        df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
        df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)

        logger.info(f"[TECHNICAL] Added {len(df.columns) - 10} technical features")
        return df

    def ingest_all(self) -> str:
        """
        Complete data ingestion pipeline.
        
        Returns:
            Path to saved CSV file
        """
        logger.info("[INGESTION] Starting complete data ingestion...")

        # 1. Fetch primary currency data
        currency_df = self.fetch_currency_data(
            symbol=self.config.primary_pair,
            period=self.config.history_period
        )

        if currency_df.empty:
            raise ValueError("Failed to fetch primary currency data")

        # 2. Fetch economic indicators
        indicators = {}
        if self.config.include_indicators:
            indicators = self.fetch_indicators()

        # 3. Merge all data
        merged_df = self.merge_all_data(currency_df, indicators)

        # 4. Add technical features
        final_df = self.add_technical_features(merged_df)

        # 5. Drop rows with NaN (from rolling calculations)
        final_df = final_df.dropna().reset_index(drop=True)

        # 6. Save to CSV
        timestamp = datetime.now().strftime("%Y%m%d")
        save_path = os.path.join(
            self.config.raw_data_dir,
            f"currency_data_{timestamp}.csv"
        )
        final_df.to_csv(save_path, index=False)

        logger.info(f"[INGESTION] ✓ Complete! Saved {len(final_df)} records to {save_path}")
        logger.info(f"[INGESTION] Features: {list(final_df.columns)}")

        return save_path

    def load_existing(self, path: Optional[str] = None) -> pd.DataFrame:
        """Load existing ingested data."""
        if path and os.path.exists(path):
            return pd.read_csv(path, parse_dates=["date"])

        data_dir = Path(self.config.raw_data_dir)
        csv_files = list(data_dir.glob("currency_data_*.csv"))

        if not csv_files:
            raise FileNotFoundError(f"No currency data found in {data_dir}")

        latest = max(csv_files, key=lambda p: p.stat().st_mtime)
        logger.info(f"[INGESTION] Loading {latest}")

        return pd.read_csv(latest, parse_dates=["date"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Test ingestion
    ingestion = CurrencyDataIngestion()

    print("Testing USD/LKR data ingestion...")
    try:
        save_path = ingestion.ingest_all()

        df = ingestion.load_existing(save_path)
        print(f"\nLoaded {len(df)} records")
        print(f"Columns: {list(df.columns)}")
        print(f"\nLatest rate: {df['close'].iloc[-1]:.2f} LKR per USD")
        print(f"Date range: {df['date'].min()} to {df['date'].max()}")
    except Exception as e:
        print(f"Error: {e}")

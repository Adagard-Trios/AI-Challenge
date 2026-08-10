"""
models/weather-prediction/src/components/data_ingestion.py
Data Ingestion component for Weather Prediction Pipeline
"""
import os
import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd

# Add parent paths
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.tutiempo_scraper import TutiempoScraper
from entity.config_entity import DataIngestionConfig, WEATHER_STATIONS

logger = logging.getLogger("weather_prediction.data_ingestion")


class DataIngestion:
    """
    Handles ingestion of historical weather data from Tutiempo.net
    
    Ingests data for all 20 Sri Lankan weather stations and saves
    to CSV for training.
    """

    def __init__(self, config: Optional[DataIngestionConfig] = None):
        self.config = config or DataIngestionConfig()
        os.makedirs(self.config.raw_data_dir, exist_ok=True)

        self.scraper = TutiempoScraper(cache_dir=self.config.raw_data_dir)

    def ingest_all(self) -> str:
        """
        Ingest historical weather data for all stations.
        Falls back to synthetic data if scraping fails.
        
        Returns:
            Path to saved CSV file
        """
        timestamp = datetime.now().strftime("%Y%m%d")
        save_path = os.path.join(
            self.config.raw_data_dir,
            f"weather_history_{timestamp}.csv"
        )

        logger.info(f"[DATA_INGESTION] Starting ingestion for {len(self.config.stations)} stations")
        logger.info(f"[DATA_INGESTION] Fetching {self.config.months_to_fetch} months of history")

        df = self.scraper.scrape_all_stations(
            stations=self.config.stations,
            months=self.config.months_to_fetch,
            save_path=save_path
        )

        # Fallback to synthetic data if scraping failed
        if df.empty or len(df) < 100:
            logger.warning("[DATA_INGESTION] Scraping failed or insufficient data. Generating synthetic training data.")
            df = self._generate_synthetic_data()
            df.to_csv(save_path, index=False)
            logger.info(f"[DATA_INGESTION] Generated {len(df)} synthetic records")

        logger.info(f"[DATA_INGESTION] [OK] Ingested {len(df)} total records")
        return save_path

    def _generate_synthetic_data(self) -> pd.DataFrame:
        """
        Generate synthetic weather data for training when scraping fails.
        Uses realistic Sri Lankan climate patterns.
        """
        import numpy as np

        # Generate 1 year of daily data for priority stations
        priority_stations = ["COLOMBO", "KANDY", "JAFFNA", "BATTICALOA", "RATNAPURA"]

        records = []
        for station in priority_stations:
            if station not in self.config.stations:
                continue

            config = self.config.stations[station]

            # Generate 365 days of data
            for day_offset in range(365):
                date = datetime.now() - pd.Timedelta(days=day_offset)
                month = date.month

                # Monsoon-aware temperature (more realistic for Sri Lanka)
                # South-West monsoon: May-Sep, North-East: Dec-Feb
                base_temp = 28 if month in [3, 4, 5, 6, 7, 8] else 26
                temp_variation = np.random.normal(0, 2)
                temp_mean = base_temp + temp_variation

                # Monsoon rainfall patterns
                if month in [10, 11, 12]:  # NE monsoon - heavy rain
                    rainfall = max(0, np.random.exponential(15))
                elif month in [5, 6, 7]:  # SW monsoon - moderate rain
                    rainfall = max(0, np.random.exponential(10))
                else:  # Inter-monsoon / dry
                    rainfall = max(0, np.random.exponential(3))

                records.append({
                    "date": date.strftime("%Y-%m-%d"),
                    "year": date.year,
                    "month": month,
                    "day": date.day,
                    "station_code": config["code"],
                    "station_name": station,
                    "temp_mean": round(temp_mean, 1),
                    "temp_max": round(temp_mean + np.random.uniform(3, 6), 1),
                    "temp_min": round(temp_mean - np.random.uniform(3, 5), 1),
                    "rainfall": round(rainfall, 1),
                    "humidity": round(np.random.uniform(65, 90), 1),
                    "wind_speed": round(np.random.uniform(5, 25), 1),
                    "pressure": round(np.random.uniform(1008, 1015), 1),
                })

        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values(["station_name", "date"]).reset_index(drop=True)
        return df

    def ingest_station(self, station_name: str, months: int = None) -> pd.DataFrame:
        """
        Ingest data for a single station.
        
        Args:
            station_name: Name of station (e.g., "COLOMBO")
            months: Override months to fetch
            
        Returns:
            DataFrame with station data
        """
        if station_name not in self.config.stations:
            raise ValueError(f"Unknown station: {station_name}")

        station_config = self.config.stations[station_name]
        months = months or self.config.months_to_fetch

        df = self.scraper.scrape_historical(
            station_code=station_config["code"],
            station_name=station_name,
            months=months
        )

        return df

    def load_existing(self, path: Optional[str] = None) -> pd.DataFrame:
        """
        Load existing ingested data.
        
        Args:
            path: Path to CSV file, or uses latest in data dir
            
        Returns:
            DataFrame with weather data
        """
        if path and os.path.exists(path):
            return pd.read_csv(path, parse_dates=["date"])

        # Find latest CSV
        data_dir = Path(self.config.raw_data_dir)
        csv_files = list(data_dir.glob("weather_history_*.csv"))

        if not csv_files:
            raise FileNotFoundError(f"No weather data found in {data_dir}")

        latest = max(csv_files, key=lambda p: p.stat().st_mtime)
        logger.info(f"[DATA_INGESTION] Loading {latest}")

        return pd.read_csv(latest, parse_dates=["date"])

    def get_data_stats(self, df: pd.DataFrame) -> Dict:
        """Get statistics about ingested data."""
        return {
            "total_records": len(df),
            "stations": df["station_name"].nunique() if "station_name" in df.columns else 0,
            "date_range": {
                "start": str(df["date"].min()),
                "end": str(df["date"].max())
            },
            "columns": list(df.columns),
            "missing_percentage": df.isnull().mean().to_dict()
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Test ingestion
    ingestion = DataIngestion()

    # Test single station
    print("Testing single station ingestion...")
    df = ingestion.ingest_station("COLOMBO", months=2)

    print(f"\nIngested {len(df)} records for COLOMBO")
    if not df.empty:
        print("\nSample data:")
        print(df.head())

        print("\nStats:")
        stats = ingestion.get_data_stats(df)
        for k, v in stats.items():
            print(f"  {k}: {v}")

"""
scripts/scrape_weather_data.py
Weather Data Scraper for ML Model Training

Scrapes historical weather data from publicly available sources:
1. Open-Meteo API (Free, no API key required) - Historical weather data
2. NASA FIRMS API - Fire/heat spot data
3. DWD ICON Model data (optional)

Creates CSV files for training weather/flood prediction models.

Usage:
    python scripts/scrape_weather_data.py --start 2020-01-01 --end 2024-12-31 --output datasets/weather_historical.csv
"""

import os
import sys
import json
import time
import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

import requests
import pandas as pd

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Sri Lanka coordinates (bounding box)
SRI_LANKA_BOUNDS = {
    "north": 9.85,
    "south": 5.92,
    "west": 79.65,
    "east": 81.88,
    "center_lat": 7.87,
    "center_lon": 80.77
}

# All 25 districts with approximate coordinates
SRI_LANKA_DISTRICTS = {
    "Colombo": (6.9271, 79.8612),
    "Gampaha": (7.0917, 80.0000),
    "Kalutara": (6.5854, 79.9607),
    "Kandy": (7.2906, 80.6337),
    "Matale": (7.4675, 80.6234),
    "Nuwara Eliya": (6.9497, 80.7891),
    "Galle": (6.0535, 80.2210),
    "Matara": (5.9549, 80.5550),
    "Hambantota": (6.1429, 81.1212),
    "Jaffna": (9.6615, 80.0255),
    "Kilinochchi": (9.3803, 80.3770),
    "Mannar": (8.9810, 79.9044),
    "Mullaitivu": (9.2671, 80.8142),
    "Vavuniya": (8.7542, 80.4982),
    "Batticaloa": (7.7310, 81.6747),
    "Ampara": (7.2912, 81.6820),
    "Trincomalee": (8.5874, 81.2152),
    "Kurunegala": (7.4818, 80.3609),
    "Puttalam": (8.0408, 79.8394),
    "Anuradhapura": (8.3114, 80.4037),
    "Polonnaruwa": (7.9403, 81.0188),
    "Badulla": (6.9934, 81.0550),
    "Monaragala": (6.8728, 81.3507),
    "Ratnapura": (6.6828, 80.3992),
    "Kegalle": (7.2513, 80.3464),
}


class OpenMeteoScraper:
    """
    Scrape historical weather data from Open-Meteo API.
    Free, no API key required, extensive historical data.
    
    API Docs: https://open-meteo.com/en/docs/historical-weather-api
    """
    
    BASE_URL = "https://archive-api.open-meteo.com/v1/archive"
    
    # Rate limit: max 10,000 requests/day, be respectful
    REQUEST_DELAY = 0.5  # seconds between requests
    
    HOURLY_VARIABLES = [
        "temperature_2m",
        "relative_humidity_2m",
        "dew_point_2m",
        "precipitation",
        "rain",
        "pressure_msl",
        "wind_speed_10m",
        "wind_direction_10m",
        "wind_gusts_10m",
        "cloud_cover",
    ]
    
    DAILY_VARIABLES = [
        "temperature_2m_max",
        "temperature_2m_min",
        "temperature_2m_mean",
        "precipitation_sum",
        "rain_sum",
        "precipitation_hours",
        "wind_speed_10m_max",
        "wind_gusts_10m_max",
        "wind_direction_10m_dominant",
    ]
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Roger-Weather-Scraper/1.0 (research purposes)"
        })
    
    def fetch_district_data(
        self,
        district: str,
        lat: float,
        lon: float,
        start_date: str,
        end_date: str,
        resolution: str = "daily"
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch historical weather data for a district.
        
        Args:
            district: District name
            lat, lon: Coordinates
            start_date, end_date: Date range (YYYY-MM-DD)
            resolution: "hourly" or "daily"
        
        Returns:
            Dict with weather data or None on failure
        """
        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": start_date,
            "end_date": end_date,
            "timezone": "Asia/Colombo",
        }
        
        if resolution == "hourly":
            params["hourly"] = ",".join(self.HOURLY_VARIABLES)
        else:
            params["daily"] = ",".join(self.DAILY_VARIABLES)
        
        try:
            logger.info(f"Fetching {resolution} data for {district} ({start_date} to {end_date})")
            response = self.session.get(self.BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            data["district"] = district
            data["latitude"] = lat
            data["longitude"] = lon
            
            time.sleep(self.REQUEST_DELAY)
            return data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching data for {district}: {e}")
            return None
    
    def fetch_all_districts(
        self,
        start_date: str,
        end_date: str,
        resolution: str = "daily"
    ) -> pd.DataFrame:
        """
        Fetch weather data for all 25 Sri Lankan districts.
        
        Returns:
            DataFrame with all district weather data
        """
        all_data = []
        
        for district, (lat, lon) in SRI_LANKA_DISTRICTS.items():
            data = self.fetch_district_data(
                district=district,
                lat=lat,
                lon=lon,
                start_date=start_date,
                end_date=end_date,
                resolution=resolution
            )
            
            if data is None:
                continue
            
            # Parse into rows
            if resolution == "daily":
                time_key = "daily"
                times = data.get("daily", {}).get("time", [])
            else:
                time_key = "hourly"
                times = data.get("hourly", {}).get("time", [])
            
            for i, timestamp in enumerate(times):
                row = {
                    "district": district,
                    "latitude": lat,
                    "longitude": lon,
                    "timestamp": timestamp,
                }
                
                # Add all weather variables
                for var in data.get(time_key, {}):
                    if var != "time":
                        values = data[time_key].get(var, [])
                        row[var] = values[i] if i < len(values) else None
                
                all_data.append(row)
        
        df = pd.DataFrame(all_data)
        logger.info(f"Collected {len(df)} records for {len(SRI_LANKA_DISTRICTS)} districts")
        return df


class NASAFirmsScraper:
    """
    Scrape fire/heat spot data from NASA FIRMS API.
    Free API key available at: https://firms.modaps.eosdis.nasa.gov/api/area/
    
    Note: Historical data available for past 60 days for free,
    older data requires special request.
    """
    
    BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/country/csv"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("NASA_FIRMS_API_KEY", "")
        self.session = requests.Session()
    
    def fetch_sri_lanka_fires(self, days: int = 10) -> pd.DataFrame:
        """
        Fetch recent fire detections for Sri Lanka.
        
        Args:
            days: Number of past days (max 60 for free tier)
        
        Returns:
            DataFrame with fire detections
        """
        if not self.api_key:
            logger.warning("NASA FIRMS API key not set. Using demo mode (limited data).")
            # Use demo endpoint
            url = f"https://firms.modaps.eosdis.nasa.gov/api/country/csv/VIIRS_SNPP_NRT/LKA/{days}"
        else:
            url = f"{self.BASE_URL}/{self.api_key}/VIIRS_SNPP_NRT/LKA/{days}"
        
        try:
            logger.info(f"Fetching NASA FIRMS fire data for past {days} days")
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            # Parse CSV response
            from io import StringIO
            df = pd.read_csv(StringIO(response.text))
            logger.info(f"Found {len(df)} fire detections")
            return df
            
        except Exception as e:
            logger.error(f"Error fetching FIRMS data: {e}")
            return pd.DataFrame()


class WeatherDataPipeline:
    """
    Complete pipeline to scrape and prepare weather data for ML training.
    """
    
    def __init__(self, output_dir: str = "datasets/weather"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.meteo_scraper = OpenMeteoScraper()
        self.firms_scraper = NASAFirmsScraper()
    
    def scrape_historical_weather(
        self,
        start_date: str,
        end_date: str,
        resolution: str = "daily"
    ) -> str:
        """
        Scrape historical weather data and save to CSV.
        
        Args:
            start_date, end_date: Date range (YYYY-MM-DD)
            resolution: "daily" or "hourly"
        
        Returns:
            Path to output CSV file
        """
        logger.info(f"Starting historical weather scrape: {start_date} to {end_date}")
        
        # Fetch data
        df = self.meteo_scraper.fetch_all_districts(
            start_date=start_date,
            end_date=end_date,
            resolution=resolution
        )
        
        if df.empty:
            logger.error("No data collected!")
            return ""
        
        # Add metadata
        df["scraped_at"] = datetime.utcnow().isoformat()
        df["source"] = "open-meteo"
        
        # Save to CSV
        filename = f"weather_{resolution}_{start_date}_{end_date}.csv"
        output_path = self.output_dir / filename
        df.to_csv(output_path, index=False)
        
        logger.info(f"Saved {len(df)} records to {output_path}")
        return str(output_path)
    
    def scrape_fire_data(self, days: int = 30) -> str:
        """
        Scrape NASA FIRMS fire data.
        
        Returns:
            Path to output CSV file
        """
        logger.info(f"Scraping fire data for past {days} days")
        
        df = self.firms_scraper.fetch_sri_lanka_fires(days=days)
        
        if df.empty:
            logger.warning("No fire data collected")
            return ""
        
        filename = f"fire_detections_{datetime.now().strftime('%Y%m%d')}.csv"
        output_path = self.output_dir / filename
        df.to_csv(output_path, index=False)
        
        logger.info(f"Saved {len(df)} fire detections to {output_path}")
        return str(output_path)
    
    def scrape_yearly_data(self, years: List[int]) -> List[str]:
        """
        Scrape full-year weather data for multiple years.
        Useful for building training datasets.
        
        Args:
            years: List of years to scrape (e.g., [2020, 2021, 2022, 2023])
        
        Returns:
            List of output file paths
        """
        output_files = []
        
        for year in years:
            start = f"{year}-01-01"
            end = f"{year}-12-31"
            
            logger.info(f"\n{'='*50}")
            logger.info(f"Processing year {year}")
            logger.info(f"{'='*50}")
            
            output_path = self.scrape_historical_weather(
                start_date=start,
                end_date=end,
                resolution="daily"
            )
            
            if output_path:
                output_files.append(output_path)
            
            # Pause between years to be respectful
            time.sleep(2)
        
        return output_files
    
    def combine_yearly_files(self, files: List[str], output_name: str = "weather_combined.csv") -> str:
        """
        Combine multiple yearly CSV files into one.
        """
        if not files:
            logger.error("No files to combine")
            return ""
        
        dfs = []
        for f in files:
            if os.path.exists(f):
                dfs.append(pd.read_csv(f))
        
        if not dfs:
            return ""
        
        combined = pd.concat(dfs, ignore_index=True)
        combined = combined.drop_duplicates(subset=["district", "timestamp"])
        combined = combined.sort_values(["district", "timestamp"])
        
        output_path = self.output_dir / output_name
        combined.to_csv(output_path, index=False)
        
        logger.info(f"Combined {len(files)} files into {output_path} ({len(combined)} records)")
        return str(output_path)


def main():
    parser = argparse.ArgumentParser(description="Scrape weather data for ML training")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--years", type=str, help="Comma-separated years (e.g., 2020,2021,2022)")
    parser.add_argument("--output", type=str, default="datasets/weather", help="Output directory")
    parser.add_argument("--resolution", type=str, default="daily", choices=["daily", "hourly"])
    parser.add_argument("--fires", action="store_true", help="Also fetch fire detection data")
    parser.add_argument("--fire-days", type=int, default=30, help="Days of fire data to fetch")
    
    args = parser.parse_args()
    
    pipeline = WeatherDataPipeline(output_dir=args.output)
    
    # Yearly scraping mode
    if args.years:
        years = [int(y.strip()) for y in args.years.split(",")]
        files = pipeline.scrape_yearly_data(years)
        
        if len(files) > 1:
            pipeline.combine_yearly_files(files)
    
    # Date range mode
    elif args.start and args.end:
        pipeline.scrape_historical_weather(
            start_date=args.start,
            end_date=args.end,
            resolution=args.resolution
        )
    
    else:
        # Default: last 30 days
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        pipeline.scrape_historical_weather(
            start_date=start,
            end_date=end,
            resolution="daily"
        )
    
    # Fire data
    if args.fires:
        pipeline.scrape_fire_data(days=args.fire_days)
    
    logger.info("\n✅ Weather data scraping complete!")


if __name__ == "__main__":
    main()

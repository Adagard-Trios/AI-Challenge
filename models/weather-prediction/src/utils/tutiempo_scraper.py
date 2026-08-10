"""
models/weather-prediction/src/utils/tutiempo_scraper.py
Scraper for historical weather data from Tutiempo.net
"""
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import pandas as pd
import logging
import time
import re
import os

logger = logging.getLogger("weather_prediction.scraper")


class TutiempoScraper:
    """
    Scrapes historical weather data from Tutiempo.net for Sri Lankan weather stations.
    
    Data includes:
    - Temperature (high/low/mean)
    - Rainfall (mm)
    - Humidity (%)
    - Wind speed (km/h)
    - Pressure (hPa)
    - Visibility (km)
    """

    BASE_URL = "https://en.tutiempo.net/climate"

    # Column mappings from Tutiempo HTML table
    COLUMN_MAPPING = {
        "T": "temp_mean",      # Mean temperature (°C)
        "TM": "temp_max",      # Maximum temperature
        "Tm": "temp_min",      # Minimum temperature
        "SLP": "pressure",     # Sea level pressure (hPa)
        "H": "humidity",       # Humidity (%)
        "PP": "rainfall",      # Precipitation (mm)
        "VV": "visibility",    # Visibility (km)
        "V": "wind_speed",     # Wind speed (km/h)
        "VM": "wind_gust",     # Maximum wind gust
        "RA": "rain_indicator", # Rain indicator
        "SN": "snow_indicator", # Snow indicator
        "TS": "storm_indicator", # Thunderstorm indicator
    }

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_dir = cache_dir
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

    def scrape_month(
        self,
        station_code: str,
        year: int,
        month: int
    ) -> List[Dict[str, Any]]:
        """
        Scrape weather data for a specific month from a station.
        
        Args:
            station_code: Tutiempo station code (e.g., "434660" for Colombo)
            year: Year (e.g., 2024)
            month: Month (1-12)
            
        Returns:
            List of daily weather records
        """
        url = f"{self.BASE_URL}/{month:02d}-{year}/ws-{station_code}.html"
        logger.info(f"[TUTIEMPO] Fetching {url}")

        try:
            response = requests.get(url, headers=self.HEADERS, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"[TUTIEMPO] Failed to fetch {url}: {e}")
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        records = []

        # Find the main data table
        table = soup.find("table", {"id": "ClimasData"}) or soup.find("table", class_="medias")

        if not table:
            # Try alternative table selection
            tables = soup.find_all("table")
            for t in tables:
                if t.find("th") and "Day" in t.get_text():
                    table = t
                    break

        if not table:
            logger.warning(f"[TUTIEMPO] No data table found for {station_code} {year}/{month}")
            return []

        # Parse headers
        headers = []
        header_row = table.find("tr")
        if header_row:
            for th in header_row.find_all(["th", "td"]):
                header_text = th.get_text(strip=True)
                headers.append(header_text)

        # Parse data rows
        rows = table.find_all("tr")[1:]  # Skip header row

        for row in rows:
            cells = row.find_all("td")
            if not cells or len(cells) < 5:
                continue

            try:
                day_text = cells[0].get_text(strip=True)
                if not day_text.isdigit():
                    continue

                day = int(day_text)

                record = {
                    "date": f"{year}-{month:02d}-{day:02d}",
                    "year": year,
                    "month": month,
                    "day": day,
                    "station_code": station_code,
                }

                # Map cell values to column names
                for i, cell in enumerate(cells[1:], 1):
                    if i < len(headers):
                        col_name = headers[i]
                        mapped_name = self.COLUMN_MAPPING.get(col_name, col_name.lower())

                        cell_text = cell.get_text(strip=True)

                        # Parse numeric values
                        if cell_text in ["-", "", "—"]:
                            record[mapped_name] = None
                        else:
                            try:
                                record[mapped_name] = float(cell_text.replace(",", "."))
                            except ValueError:
                                record[mapped_name] = cell_text

                records.append(record)

            except Exception as e:
                logger.debug(f"[TUTIEMPO] Error parsing row: {e}")
                continue

        logger.info(f"[TUTIEMPO] Parsed {len(records)} records for {station_code} {year}/{month}")
        return records

    def scrape_historical(
        self,
        station_code: str,
        station_name: str,
        months: int = 12
    ) -> pd.DataFrame:
        """
        Scrape multiple months of historical data for a station.
        
        Args:
            station_code: Tutiempo station code
            station_name: Human-readable station name
            months: Number of months to fetch (going backwards from current)
            
        Returns:
            DataFrame with all historical records
        """
        all_records = []

        # IMPORTANT: TuTiempo has data publication delay of ~2-3 months
        # Start from 3 months ago to avoid 404 errors on recent months
        current = datetime.now()
        start_date = current - timedelta(days=90)  # Start 3 months ago

        consecutive_failures = 0
        max_consecutive_failures = 3

        for i in range(months):
            target_date = start_date - timedelta(days=30 * i)
            year = target_date.year
            month = target_date.month

            records = self.scrape_month(station_code, year, month)

            if not records:
                consecutive_failures += 1
                if consecutive_failures >= max_consecutive_failures:
                    logger.warning(f"[TUTIEMPO] {max_consecutive_failures} consecutive failures for {station_name}, stopping")
                    break
            else:
                consecutive_failures = 0  # Reset on success
                for r in records:
                    r["station_name"] = station_name
                all_records.extend(records)

            # Be nice to the server
            time.sleep(1)

        if not all_records:
            logger.warning(f"[TUTIEMPO] No data collected for {station_name}")
            return pd.DataFrame()

        df = pd.DataFrame(all_records)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        logger.info(f"[TUTIEMPO] Collected {len(df)} total records for {station_name}")
        return df

    def scrape_all_stations(
        self,
        stations: Dict[str, Dict],
        months: int = 12,
        save_path: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Scrape historical data for all Sri Lankan weather stations.
        
        Args:
            stations: Dictionary of station configurations
            months: Months of history per station
            save_path: Optional path to save combined CSV
            
        Returns:
            Combined DataFrame for all stations
        """
        all_data = []

        for station_name, config in stations.items():
            logger.info(f"[TUTIEMPO] === Scraping {station_name} ===")

            df = self.scrape_historical(
                station_code=config["code"],
                station_name=station_name,
                months=months
            )

            if not df.empty:
                df["districts"] = str(config.get("districts", []))
                all_data.append(df)

            # Pause between stations
            time.sleep(2)

        if not all_data:
            logger.error("[TUTIEMPO] No data collected from any station!")
            return pd.DataFrame()

        combined = pd.concat(all_data, ignore_index=True)

        if save_path:
            combined.to_csv(save_path, index=False)
            logger.info(f"[TUTIEMPO] Saved {len(combined)} records to {save_path}")

        return combined


if __name__ == "__main__":
    # Test scraper
    logging.basicConfig(level=logging.INFO)

    scraper = TutiempoScraper()

    # Test single month
    records = scraper.scrape_month("434660", 2024, 11)  # Colombo, Nov 2024

    print(f"\nFetched {len(records)} records")
    if records:
        print("\nSample record:")
        for k, v in records[0].items():
            print(f"  {k}: {v}")

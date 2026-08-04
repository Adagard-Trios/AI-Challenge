"""
models/anomaly-detection/src/components/data_ingestion.py
Data ingestion from SQLite feed cache and CSV files
"""
import os
import sqlite3
import pandas as pd
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..entity import DataIngestionConfig, DataIngestionArtifact

logger = logging.getLogger("data_ingestion")


class DataIngestion:
    """
    Data ingestion component that fetches feed data from:
    1. SQLite database (feed_cache.db) - production deduped feeds
    2. CSV files in datasets/political_feeds/ - historical data
    """

    def __init__(self, config: Optional[DataIngestionConfig] = None):
        """
        Initialize data ingestion component.
        
        Args:
            config: Optional configuration, uses defaults if None
        """
        self.config = config or DataIngestionConfig()

        # Ensure output directory exists
        Path(self.config.output_directory).mkdir(parents=True, exist_ok=True)

        logger.info("[DataIngestion] Initialized")
        logger.info(f"  SQLite: {self.config.sqlite_db_path}")
        logger.info(f"  CSV Dir: {self.config.csv_directory}")
        logger.info(f"  Output: {self.config.output_directory}")

    def _fetch_from_sqlite(self) -> pd.DataFrame:
        """
        Fetch feed data from SQLite cache database.
        
        Returns:
            DataFrame with feed records
        """
        db_path = self.config.sqlite_db_path

        if not os.path.exists(db_path):
            logger.warning(f"[DataIngestion] SQLite DB not found: {db_path}")
            return pd.DataFrame()

        try:
            conn = sqlite3.connect(db_path)

            # Query the seen_hashes table
            query = """
                SELECT 
                    content_hash as post_id,
                    first_seen as timestamp,
                    event_id,
                    summary_preview as text
                FROM seen_hashes
                ORDER BY last_seen DESC
            """
            df = pd.read_sql_query(query, conn)
            conn.close()

            # Add default columns for compatibility
            if not df.empty:
                df["platform"] = "mixed"
                df["category"] = "feed"
                df["content_hash"] = df["post_id"]
                df["source"] = "sqlite"

            logger.info(f"[DataIngestion] Fetched {len(df)} records from SQLite")
            return df

        except Exception as e:
            logger.error(f"[DataIngestion] SQLite error: {e}")
            return pd.DataFrame()

    def _fetch_from_csv(self) -> pd.DataFrame:
        """
        Fetch feed data from CSV files in datasets directory.
        
        Returns:
            Combined DataFrame from all CSV files
        """
        csv_dir = Path(self.config.csv_directory)

        if not csv_dir.exists():
            logger.warning(f"[DataIngestion] CSV directory not found: {csv_dir}")
            return pd.DataFrame()

        all_dfs = []
        csv_files = list(csv_dir.glob("*.csv"))

        for csv_file in csv_files:
            try:
                df = pd.read_csv(csv_file)
                df["source_file"] = csv_file.name
                df["source"] = "csv"
                all_dfs.append(df)
                logger.info(f"[DataIngestion] Loaded {len(df)} records from {csv_file.name}")
            except Exception as e:
                logger.warning(f"[DataIngestion] Failed to load {csv_file}: {e}")

        if not all_dfs:
            return pd.DataFrame()

        combined = pd.concat(all_dfs, ignore_index=True)
        logger.info(f"[DataIngestion] Total {len(combined)} records from {len(csv_files)} CSV files")
        return combined

    def _deduplicate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Remove duplicate records based on content_hash.
        
        Args:
            df: Input DataFrame
            
        Returns:
            Deduplicated DataFrame
        """
        if df.empty:
            return df

        initial_count = len(df)

        # Use content_hash for deduplication, fallback to post_id
        if "content_hash" in df.columns:
            df = df.drop_duplicates(subset=["content_hash"], keep="first")
        elif "post_id" in df.columns:
            df = df.drop_duplicates(subset=["post_id"], keep="first")

        deduped_count = len(df)
        removed = initial_count - deduped_count

        if removed > 0:
            logger.info(f"[DataIngestion] Deduplicated: removed {removed} duplicates")

        return df

    def _filter_valid_records(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Filter records with sufficient text content.
        
        Args:
            df: Input DataFrame
            
        Returns:
            Filtered DataFrame
        """
        if df.empty:
            return df

        initial_count = len(df)

        # Ensure text column exists
        if "text" not in df.columns:
            # Try alternative column names
            text_cols = ["summary_preview", "title", "content"]
            for col in text_cols:
                if col in df.columns:
                    df["text"] = df[col]
                    break

        if "text" not in df.columns:
            logger.warning("[DataIngestion] No text column found")
            df["text"] = ""

        # Filter by minimum text length
        df = df[df["text"].str.len() >= self.config.min_text_length]

        filtered_count = len(df)
        removed = initial_count - filtered_count

        if removed > 0:
            logger.info(f"[DataIngestion] Filtered: removed {removed} short texts")

        return df

    def initiate_data_ingestion(self) -> DataIngestionArtifact:
        """
        Execute data ingestion pipeline.
        
        Returns:
            DataIngestionArtifact with paths and statistics
        """
        logger.info("[DataIngestion] Starting data ingestion...")

        # Fetch from both sources
        sqlite_df = self._fetch_from_sqlite()
        csv_df = self._fetch_from_csv()

        records_from_sqlite = len(sqlite_df)
        records_from_csv = len(csv_df)

        # Combine sources
        if not sqlite_df.empty and not csv_df.empty:
            # Ensure compatible columns
            common_cols = list(set(sqlite_df.columns) & set(csv_df.columns))
            combined_df = pd.concat([
                sqlite_df[common_cols],
                csv_df[common_cols]
            ], ignore_index=True)
        elif not sqlite_df.empty:
            combined_df = sqlite_df
        elif not csv_df.empty:
            combined_df = csv_df
        else:
            combined_df = pd.DataFrame()

        # Deduplicate
        combined_df = self._deduplicate(combined_df)

        # Filter valid records
        combined_df = self._filter_valid_records(combined_df)

        total_records = len(combined_df)
        is_data_available = total_records > 0

        # Save to output
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path(self.config.output_directory) / f"ingested_data_{timestamp}.parquet"

        if is_data_available:
            # Convert timestamp column to datetime to avoid parquet conversion error
            if "timestamp" in combined_df.columns:
                combined_df["timestamp"] = pd.to_datetime(combined_df["timestamp"], errors="coerce")
            combined_df.to_parquet(output_path, index=False)
            logger.info(f"[DataIngestion] Saved {total_records} records to {output_path}")
        else:
            output_path = str(output_path)
            logger.warning("[DataIngestion] No data available to save")

        artifact = DataIngestionArtifact(
            raw_data_path=str(output_path),
            total_records=total_records,
            records_from_sqlite=records_from_sqlite,
            records_from_csv=records_from_csv,
            ingestion_timestamp=timestamp,
            is_data_available=is_data_available
        )

        logger.info(f"[DataIngestion] ✓ Complete: {total_records} records")
        return artifact

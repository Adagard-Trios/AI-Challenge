"""
models/anomaly-detection/src/components/data_transformation.py
Data transformation with language detection and text vectorization
Integrates with Vectorization Agent Graph for LLM-enhanced processing
"""
import os
import pandas as pd
import numpy as np
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from tqdm import tqdm

from ..entity import DataTransformationConfig, DataTransformationArtifact
from ..utils import detect_language, get_vectorizer

logger = logging.getLogger("data_transformation")


class DataTransformation:
    """
    Data transformation component that:
    1. Detects language (Sinhala/Tamil/English)
    2. Extracts text embeddings using language-specific BERT models
    3. Engineers temporal and engagement features
    4. Optionally integrates with Vectorizer Agent Graph for LLM insights
    """

    def __init__(self, config: Optional[DataTransformationConfig] = None, use_agent_graph: bool = True):
        """
        Initialize data transformation component.
        
        Args:
            config: Optional configuration, uses defaults if None
            use_agent_graph: If True, use vectorizer agent graph for processing
        """
        self.config = config or DataTransformationConfig()
        self.use_agent_graph = use_agent_graph

        # Ensure output directory exists
        Path(self.config.output_directory).mkdir(parents=True, exist_ok=True)

        # Get vectorizer (lazy loaded)
        self.vectorizer = get_vectorizer(self.config.models_cache_dir)

        # Vectorization API integration
        # Note: Direct import of vectorizationAgentGraph fails due to 'src' namespace collision
        # between this project (models/anomaly-detection/src) and main project (src).
        # Instead, we call the Vectorization API via HTTP when available.
        self.vectorizer_graph = None  # Not used - we use HTTP API instead
        self.vectorization_api_url = os.getenv("VECTORIZATION_API_URL", "http://localhost:8001")
        self.vectorization_api_available = False

        if self.use_agent_graph:
            # Check if vectorization API is available
            try:
                import requests
                response = requests.get(f"{self.vectorization_api_url}/health", timeout=10)
                if response.status_code == 200:
                    self.vectorization_api_available = True
                    logger.info(f"[DataTransformation] [OK] Vectorization API available at {self.vectorization_api_url}")
                else:
                    logger.warning(f"[DataTransformation] Vectorization API returned status {response.status_code}")
            except Exception as e:
                logger.warning(f"[DataTransformation] Vectorization API not available: {e}")
                logger.info("[DataTransformation] Using local vectorization (no LLM insights)")

        logger.info("[DataTransformation] Initialized")
        logger.info(f"  Models cache: {self.config.models_cache_dir}")
        logger.info(f"  Vectorization API: {'enabled' if self.vectorization_api_available else 'disabled (using local)'}")

    def _process_with_agent_graph(self, texts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Process texts through the Vectorization API.
        
        Uses HTTP calls to the vectorization API server which runs the
        Vectorizer Agent Graph. This avoids the 'src' namespace collision.
        
        This provides:
        - Language detection
        - Vector embeddings
        - LLM expert summary
        - Opportunity/threat analysis
        
        Args:
            texts: List of {text, post_id, metadata} dicts
            
        Returns:
            Dict with language_detection_results, vector_embeddings, expert_summary, etc.
        """
        if not self.vectorization_api_available:
            logger.warning("[DataTransformation] Vectorization API not available, using fallback")
            return None

        try:
            import requests

            batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Prepare request payload
            payload = {
                "texts": [
                    {
                        "text": item.get("text", ""),
                        "post_id": item.get("post_id", f"text_{i}"),
                        "metadata": item.get("metadata", {})
                    }
                    for i, item in enumerate(texts)
                ],
                "batch_id": batch_id,
                "include_vectors": True,
                "include_expert_summary": True
            }

            # Call vectorization API
            response = requests.post(
                f"{self.vectorization_api_url}/vectorize",
                json=payload,
                timeout=120  # 2 minutes for large batches
            )

            if response.status_code == 200:
                result = response.json()
                logger.info(f"[DataTransformation] Vectorization API processed {len(texts)} texts")

                # Convert API response to expected format
                return {
                    "language_detection_results": result.get("vectors", []),
                    "vector_embeddings": result.get("vectors", []),
                    "expert_summary": result.get("expert_summary", ""),
                    "opportunities": [],  # Extracted from domain_insights
                    "threats": [],  # Extracted from domain_insights
                    "domain_insights": result.get("domain_insights", []),
                    "processing_stats": {
                        "language_distribution": result.get("language_distribution", {}),
                        "processing_time": result.get("processing_time_seconds", 0)
                    }
                }
            else:
                logger.error(f"[DataTransformation] Vectorization API error: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"[DataTransformation] Vectorization API call failed: {e}")
            return None

    def _detect_languages(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Detect language for each text entry.
        
        Args:
            df: Input DataFrame with 'text' column
            
        Returns:
            DataFrame with 'language' and 'language_confidence' columns
        """
        logger.info("[DataTransformation] Detecting languages...")

        languages = []
        confidences = []

        for text in tqdm(df["text"].fillna(""), desc="Language Detection"):
            lang, conf = detect_language(text)
            languages.append(lang)
            confidences.append(conf)

        df["language"] = languages
        df["language_confidence"] = confidences

        # Log distribution
        lang_counts = df["language"].value_counts()
        logger.info("[DataTransformation] Language distribution:")
        for lang, count in lang_counts.items():
            logger.info(f"  {lang}: {count} ({100*count/len(df):.1f}%)")

        return df

    def _extract_temporal_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Extract temporal features from timestamp.
        
        Args:
            df: Input DataFrame with 'timestamp' column
            
        Returns:
            DataFrame with temporal feature columns
        """
        logger.info("[DataTransformation] Extracting temporal features...")

        if "timestamp" not in df.columns:
            logger.warning("[DataTransformation] No timestamp column found")
            return df

        # Convert to datetime
        try:
            df["datetime"] = pd.to_datetime(df["timestamp"], errors='coerce')
        except Exception as e:
            logger.warning(f"[DataTransformation] Timestamp conversion error: {e}")
            return df

        # Extract features
        df["hour_of_day"] = df["datetime"].dt.hour.fillna(0).astype(int)
        df["day_of_week"] = df["datetime"].dt.dayofweek.fillna(0).astype(int)
        df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
        df["is_business_hours"] = ((df["hour_of_day"] >= 9) & (df["hour_of_day"] <= 17)).astype(int)

        # Drop intermediate column
        df = df.drop(columns=["datetime"], errors='ignore')

        return df

    def _extract_engagement_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Extract and normalize engagement features.
        
        Args:
            df: Input DataFrame
            
        Returns:
            DataFrame with engagement feature columns
        """
        logger.info("[DataTransformation] Extracting engagement features...")

        # Check for engagement columns
        engagement_cols = ["engagement_score", "engagement_likes", "engagement_shares", "engagement_comments"]

        for col in engagement_cols:
            if col not in df.columns:
                df[col] = 0

        # Combined engagement score
        df["total_engagement"] = (
            df["engagement_likes"].fillna(0) +
            df["engagement_shares"].fillna(0) * 2 +  # Shares weighted more
            df["engagement_comments"].fillna(0)
        )

        # Log transform for better distribution
        df["log_engagement"] = np.log1p(df["total_engagement"])

        # Normalize to 0-1 range
        max_engagement = df["total_engagement"].max()
        if max_engagement > 0:
            df["normalized_engagement"] = df["total_engagement"] / max_engagement
        else:
            df["normalized_engagement"] = 0

        return df

    def _extract_text_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Extract basic text features.
        
        Args:
            df: Input DataFrame with 'text' column
            
        Returns:
            DataFrame with text feature columns
        """
        logger.info("[DataTransformation] Extracting text features...")

        df["text_length"] = df["text"].fillna("").str.len()
        df["word_count"] = df["text"].fillna("").str.split().str.len().fillna(0).astype(int)

        return df

    def _vectorize_texts(self, df: pd.DataFrame) -> np.ndarray:
        """
        Vectorize texts using language-specific BERT models.
        
        Args:
            df: Input DataFrame with 'text' and 'language' columns
            
        Returns:
            numpy array of shape (n_samples, 768)
        """
        logger.info("[DataTransformation] Vectorizing texts with BERT models...")

        embeddings = []

        for idx, row in tqdm(df.iterrows(), total=len(df), desc="Text Vectorization"):
            text = row.get("text", "")
            language = row.get("language", "english")

            try:
                embedding = self.vectorizer.vectorize(text, language)
                embeddings.append(embedding)
            except Exception as e:
                logger.debug(f"Vectorization error at {idx}: {e}")
                embeddings.append(np.zeros(self.config.vector_dim))

        return np.array(embeddings)

    def _build_feature_matrix(self, df: pd.DataFrame, embeddings: np.ndarray) -> np.ndarray:
        """
        Combine all features into a single feature matrix.
        
        Args:
            df: DataFrame with engineered features
            embeddings: Text embeddings array
            
        Returns:
            Combined feature matrix
        """
        logger.info("[DataTransformation] Building feature matrix...")

        # Numeric features to include
        numeric_cols = [
            "hour_of_day", "day_of_week", "is_weekend", "is_business_hours",
            "log_engagement", "normalized_engagement",
            "text_length", "word_count"
        ]

        # Filter to available columns
        available_cols = [col for col in numeric_cols if col in df.columns]

        if available_cols:
            numeric_features = df[available_cols].fillna(0).values
            # Normalize numeric features
            from sklearn.preprocessing import StandardScaler
            scaler = StandardScaler()
            numeric_features = scaler.fit_transform(numeric_features)
        else:
            numeric_features = np.zeros((len(df), 1))

        # Combine with embeddings
        feature_matrix = np.hstack([embeddings, numeric_features])

        logger.info(f"[DataTransformation] Feature matrix shape: {feature_matrix.shape}")
        return feature_matrix

    def initiate_data_transformation(self, data_path: str) -> DataTransformationArtifact:
        """
        Execute data transformation pipeline.
        Integrates with Vectorizer Agent Graph for LLM-enhanced processing.
        
        Args:
            data_path: Path to validated data
            
        Returns:
            DataTransformationArtifact with paths and statistics
        """
        import json

        logger.info(f"[DataTransformation] Starting transformation: {data_path}")

        # Load data
        df = pd.read_parquet(data_path)
        total_records = len(df)
        logger.info(f"[DataTransformation] Loaded {total_records} records")

        # Initialize agent graph results
        agent_result = None
        expert_summary = None

        # Try to process with vectorizer agent graph first
        if self.vectorizer_graph and self.use_agent_graph:
            logger.info("[DataTransformation] Using Vectorizer Agent Graph...")

            # Prepare texts for agent graph
            texts_for_agent = []
            for idx, row in df.iterrows():
                texts_for_agent.append({
                    "post_id": str(row.get("id", idx)),
                    "text": str(row.get("text", "")),
                    "metadata": {
                        "source": row.get("source", "unknown"),
                        "timestamp": str(row.get("timestamp", ""))
                    }
                })

            # Process through agent graph
            agent_result = self._process_with_agent_graph(texts_for_agent)

            if agent_result:
                expert_summary = agent_result.get("expert_summary", "")
                logger.info("[DataTransformation] Agent graph completed with expert summary")

        # Run standard transformations (fallback or additional)
        df = self._detect_languages(df)
        df = self._extract_temporal_features(df)
        df = self._extract_engagement_features(df)
        df = self._extract_text_features(df)

        # Vectorize texts (use agent result if available, otherwise fallback)
        if agent_result and agent_result.get("vector_embeddings"):
            # Extract vectors from agent graph result
            agent_embeddings = agent_result.get("vector_embeddings", [])
            embeddings = np.array([
                item.get("vector", [0.0] * 768) for item in agent_embeddings
            ])
            logger.info(f"[DataTransformation] Using agent graph vectors: {embeddings.shape}")
        else:
            # Fallback to direct vectorization
            embeddings = self._vectorize_texts(df)

        # Build combined feature matrix
        feature_matrix = self._build_feature_matrix(df, embeddings)

        # Save outputs
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Save transformed dataframe
        transformed_path = Path(self.config.output_directory) / f"transformed_data_{timestamp}.parquet"
        df.to_parquet(transformed_path, index=False)

        # Save embeddings
        embeddings_path = Path(self.config.output_directory) / f"embeddings_{timestamp}.npy"
        np.save(embeddings_path, embeddings)

        # Save language labels for per-language model training
        languages_path = Path(self.config.output_directory) / f"languages_{timestamp}.npy"
        np.save(languages_path, df["language"].values)
        logger.info(f"[DataTransformation] Saved language labels to {languages_path.name}")

        # Save feature matrix
        features_path = Path(self.config.output_directory) / f"features_{timestamp}.npy"
        np.save(features_path, feature_matrix)

        # Save agent graph insights if available
        insights_path = None
        if agent_result:
            insights_path = Path(self.config.output_directory) / f"llm_insights_{timestamp}.json"
            insights_data = {
                "expert_summary": agent_result.get("expert_summary", ""),
                "opportunities": agent_result.get("opportunities", []),
                "threats": agent_result.get("threats", []),
                "domain_insights": agent_result.get("domain_insights", []),
                "processing_stats": agent_result.get("processing_stats", {})
            }
            with open(insights_path, "w", encoding="utf-8") as f:
                json.dump(insights_data, f, indent=2, ensure_ascii=False)
            logger.info(f"[DataTransformation] Saved LLM insights to {insights_path}")

        # Language distribution
        lang_dist = df["language"].value_counts().to_dict()

        # Build report
        report = {
            "timestamp": timestamp,
            "total_records": total_records,
            "embedding_dim": embeddings.shape[1] if len(embeddings.shape) > 1 else 0,
            "feature_dim": feature_matrix.shape[1],
            "language_distribution": lang_dist,
            "used_agent_graph": agent_result is not None,
            "expert_summary_available": expert_summary is not None
        }

        artifact = DataTransformationArtifact(
            transformed_data_path=str(transformed_path),
            vector_embeddings_path=str(embeddings_path),
            feature_store_path=str(features_path),
            total_records=total_records,
            language_distribution=lang_dist,
            transformation_report=report
        )

        logger.info(f"[DataTransformation] ✓ Complete: {feature_matrix.shape}")
        if agent_result:
            logger.info(f"[DataTransformation] ✓ LLM Expert Summary: {len(expert_summary or '')} chars")
        return artifact


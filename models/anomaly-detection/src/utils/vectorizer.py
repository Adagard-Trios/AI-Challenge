"""
models/anomaly-detection/src/utils/vectorizer.py
Text vectorization using language-specific BERT models (downloaded locally)
"""
import os
import logging
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import numpy as np

logger = logging.getLogger("vectorizer")

# Transformers
try:
    from transformers import AutoTokenizer, AutoModel
    import torch
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False
    logger.warning("Transformers not available. Install with: pip install transformers torch")

# Sentence Transformers for fallback
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False


class MultilingualVectorizer:
    """
    Vectorizer using language-specific BERT models.
    Downloads and caches models locally from HuggingFace.
    
    Models:
    - English: distilbert-base-uncased (fast, accurate)
    - Sinhala: keshan/SinhalaBERTo (specialized)
    - Tamil: l3cube-pune/tamil-bert (specialized)
    """

    MODEL_MAP = {
        "english": "distilbert-base-uncased",
        "sinhala": "keshan/SinhalaBERTo",
        "tamil": "l3cube-pune/tamil-bert"
    }

    def __init__(self, models_cache_dir: Optional[str] = None, device: Optional[str] = None):
        """
        Initialize the multilingual vectorizer.
        
        Args:
            models_cache_dir: Directory to cache downloaded models
            device: 'cuda' or 'cpu' (auto-detected if None)
        """
        self.models_cache_dir = models_cache_dir or str(
            Path(__file__).parent.parent.parent / "models_cache"
        )
        Path(self.models_cache_dir).mkdir(parents=True, exist_ok=True)

        # Set cache dir for HuggingFace
        os.environ["TRANSFORMERS_CACHE"] = self.models_cache_dir
        os.environ["HF_HOME"] = self.models_cache_dir

        # Auto-detect device
        if device is None:
            if TRANSFORMERS_AVAILABLE and torch.cuda.is_available():
                self.device = "cuda"
            else:
                self.device = "cpu"
        else:
            self.device = device

        logger.info(f"[Vectorizer] Using device: {self.device}")

        # Lazy load models
        self.models: Dict[str, Tuple] = {}  # {lang: (tokenizer, model)}
        self.fallback_model = None

    def _load_model(self, language: str) -> Tuple:
        """
        Load language-specific model from cache or download.
        
        Returns:
            Tuple of (tokenizer, model)
        """
        if language in self.models:
            return self.models[language]

        model_name = self.MODEL_MAP.get(language, self.MODEL_MAP["english"])

        if not TRANSFORMERS_AVAILABLE:
            raise RuntimeError("Transformers library not available")

        logger.info(f"[Vectorizer] Loading model: {model_name}")

        try:
            tokenizer = AutoTokenizer.from_pretrained(
                model_name,
                cache_dir=self.models_cache_dir
            )
            model = AutoModel.from_pretrained(
                model_name,
                cache_dir=self.models_cache_dir
            ).to(self.device)
            model.eval()

            self.models[language] = (tokenizer, model)
            logger.info(f"[Vectorizer] ✓ Loaded {model_name} ({language})")
            return tokenizer, model

        except Exception as e:
            logger.error(f"[Vectorizer] Failed to load {model_name}: {e}")
            # Fallback to English model
            if language != "english":
                logger.info("[Vectorizer] Falling back to English model")
                return self._load_model("english")
            raise

    def _get_embedding(self, text: str, tokenizer, model) -> np.ndarray:
        """
        Get embedding vector using mean pooling.
        
        Args:
            text: Input text
            tokenizer: HuggingFace tokenizer
            model: HuggingFace model
            
        Returns:
            768-dim numpy array
        """
        if not TRANSFORMERS_AVAILABLE:
            raise RuntimeError("Transformers not available")

        # Tokenize
        inputs = tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=512,
            padding=True
        ).to(self.device)

        # Get embeddings
        with torch.no_grad():
            outputs = model(**inputs)

        # Mean pooling over sequence length
        attention_mask = inputs["attention_mask"]
        hidden_states = outputs.last_hidden_state

        # Mask and average
        mask_expanded = attention_mask.unsqueeze(-1).expand(hidden_states.size()).float()
        sum_embeddings = torch.sum(hidden_states * mask_expanded, 1)
        sum_mask = torch.clamp(mask_expanded.sum(1), min=1e-9)
        mean_embedding = sum_embeddings / sum_mask

        return mean_embedding.cpu().numpy().flatten()

    def vectorize(self, text: str, language: str = "english") -> np.ndarray:
        """
        Convert text to vector embedding.
        
        Args:
            text: Input text
            language: 'english', 'sinhala', 'tamil', or 'unknown'
            
        Returns:
            768-dim numpy array
        """
        if not text or not text.strip():
            return np.zeros(768)

        # Map unknown to english
        if language == "unknown":
            language = "english"

        try:
            tokenizer, model = self._load_model(language)
            return self._get_embedding(text, tokenizer, model)
        except Exception as e:
            logger.error(f"[Vectorizer] Error vectorizing: {e}")
            # Return zeros as fallback
            return np.zeros(768)

    def vectorize_batch(
        self,
        texts: List[str],
        languages: Optional[List[str]] = None
    ) -> np.ndarray:
        """
        Batch vectorization for multiple texts.
        
        Args:
            texts: List of text strings
            languages: Optional list of language codes (same length as texts)
            
        Returns:
            numpy array of shape (n_texts, 768)
        """
        if languages is None:
            languages = ["english"] * len(texts)

        embeddings = []
        for text, lang in zip(texts, languages):
            emb = self.vectorize(text, lang)
            embeddings.append(emb)

        return np.array(embeddings)

    def download_all_models(self):
        """Pre-download all language models"""
        for language in self.MODEL_MAP.keys():
            try:
                logger.info(f"[Vectorizer] Pre-downloading {language} model...")
                self._load_model(language)
            except Exception as e:
                logger.warning(f"[Vectorizer] Failed to download {language}: {e}")


# Singleton instance
_vectorizer: Optional[MultilingualVectorizer] = None


def get_vectorizer(models_cache_dir: Optional[str] = None) -> MultilingualVectorizer:
    """Get or create singleton vectorizer instance"""
    global _vectorizer
    if _vectorizer is None:
        _vectorizer = MultilingualVectorizer(models_cache_dir)
    return _vectorizer


def vectorize_text(text: str, language: str = "english") -> np.ndarray:
    """
    Convenience function for text vectorization.
    
    Args:
        text: Input text
        language: Language code
        
    Returns:
        768-dim numpy array
    """
    return get_vectorizer().vectorize(text, language)

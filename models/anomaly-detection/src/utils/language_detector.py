"""
models/anomaly-detection/src/utils/language_detector.py
Language detection using FastText or lingua-py for Sinhala/Tamil/English
"""
import os
import logging
from typing import Tuple, Optional
from pathlib import Path
import re

logger = logging.getLogger("language_detector")

# Try FastText first, fallback to lingua
try:
    import fasttext
    fasttext.FastText.eprint = lambda x: None  # Suppress warnings
    FASTTEXT_AVAILABLE = True
except ImportError:
    FASTTEXT_AVAILABLE = False
    logger.warning("FastText not available. Install with: pip install fasttext")

try:
    from lingua import Language, LanguageDetectorBuilder
    LINGUA_AVAILABLE = True
except ImportError:
    LINGUA_AVAILABLE = False
    logger.warning("Lingua not available. Install with: pip install lingua-language-detector")


class LanguageDetector:
    """
    Multilingual language detector supporting Sinhala, Tamil, and English.
    Uses FastText as primary detector with lingua fallback.
    """

    # Language code mapping
    LANG_MAP = {
        "en": "english",
        "si": "sinhala",
        "ta": "tamil",
        "__label__en": "english",
        "__label__si": "sinhala",
        "__label__ta": "tamil",
        "ENGLISH": "english",
        "SINHALA": "sinhala",
        "TAMIL": "tamil"
    }

    # Unicode ranges for script detection
    SINHALA_RANGE = (0x0D80, 0x0DFF)
    TAMIL_RANGE = (0x0B80, 0x0BFF)

    def __init__(self, models_cache_dir: Optional[str] = None):
        """
        Initialize language detector.
        
        Args:
            models_cache_dir: Directory for cached FastText models
        """
        self.models_cache_dir = models_cache_dir or str(
            Path(__file__).parent.parent.parent / "models_cache"
        )
        Path(self.models_cache_dir).mkdir(parents=True, exist_ok=True)

        self.fasttext_model = None
        self.lingua_detector = None

        self._init_detectors()

    def _init_detectors(self):
        """Initialize detection models"""
        # Try FastText
        if FASTTEXT_AVAILABLE:
            model_path = Path(self.models_cache_dir) / "lid.176.bin"
            if model_path.exists():
                try:
                    self.fasttext_model = fasttext.load_model(str(model_path))
                    logger.info(f"[LanguageDetector] Loaded FastText model from {model_path}")
                except Exception as e:
                    logger.warning(f"[LanguageDetector] Failed to load FastText: {e}")
            else:
                logger.warning(f"[LanguageDetector] FastText model not found at {model_path}")
                logger.info("Download from: https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin")

        # Initialize lingua as fallback
        if LINGUA_AVAILABLE:
            try:
                self.lingua_detector = LanguageDetectorBuilder.from_languages(
                    Language.ENGLISH,
                    Language.TAMIL,
                    # Note: Lingua may not have Sinhala, we'll use script detection
                ).build()
                logger.info("[LanguageDetector] Initialized Lingua detector")
            except Exception as e:
                logger.warning(f"[LanguageDetector] Failed to init Lingua: {e}")

    def _detect_by_script(self, text: str) -> Optional[str]:
        """
        Detect language by Unicode script analysis.
        More reliable for Sinhala/Tamil which have distinct scripts.
        """
        sinhala_count = 0
        tamil_count = 0
        latin_count = 0

        for char in text:
            code = ord(char)
            if self.SINHALA_RANGE[0] <= code <= self.SINHALA_RANGE[1]:
                sinhala_count += 1
            elif self.TAMIL_RANGE[0] <= code <= self.TAMIL_RANGE[1]:
                tamil_count += 1
            elif char.isalpha() and code < 128:
                latin_count += 1

        total_alpha = sinhala_count + tamil_count + latin_count
        if total_alpha == 0:
            return None

        # Threshold-based detection
        if sinhala_count / total_alpha > 0.3:
            return "sinhala"
        if tamil_count / total_alpha > 0.3:
            return "tamil"
        if latin_count / total_alpha > 0.5:
            return "english"

        return None

    def detect(self, text: str) -> Tuple[str, float]:
        """
        Detect language of text.
        
        Args:
            text: Input text
            
        Returns:
            Tuple of (language_code, confidence)
            language_code: 'english', 'sinhala', 'tamil', or 'unknown'
        """
        if not text or len(text.strip()) < 3:
            return "unknown", 0.0

        # Clean text
        clean_text = re.sub(r'http\S+|@\w+|#\w+', '', text)
        clean_text = clean_text.strip()

        if not clean_text:
            return "unknown", 0.0

        # 1. First try script detection (most reliable for Sinhala/Tamil)
        script_lang = self._detect_by_script(clean_text)
        if script_lang in ["sinhala", "tamil"]:
            return script_lang, 0.95

        # 2. Try FastText
        if self.fasttext_model:
            try:
                predictions = self.fasttext_model.predict(clean_text.replace("\n", " "))
                label = predictions[0][0]
                confidence = predictions[1][0]

                lang = self.LANG_MAP.get(label, "unknown")
                if lang != "unknown" and confidence > 0.5:
                    return lang, float(confidence)
            except Exception as e:
                logger.debug(f"FastText error: {e}")

        # 3. Try Lingua
        if self.lingua_detector:
            try:
                detected = self.lingua_detector.detect_language_of(clean_text)
                if detected:
                    lang = self.LANG_MAP.get(detected.name, "unknown")
                    # Lingua doesn't return confidence, estimate based on text
                    confidence = 0.8 if len(clean_text) > 20 else 0.6
                    return lang, confidence
            except Exception as e:
                logger.debug(f"Lingua error: {e}")

        # 4. Fallback to script detection result or default
        if script_lang == "english":
            return "english", 0.7

        return "english", 0.5  # Default to English


# Singleton instance
_detector: Optional[LanguageDetector] = None


def get_detector(models_cache_dir: Optional[str] = None) -> LanguageDetector:
    """Get or create singleton detector instance"""
    global _detector
    if _detector is None:
        _detector = LanguageDetector(models_cache_dir)
    return _detector


def detect_language(text: str) -> Tuple[str, float]:
    """
    Convenience function for language detection.
    
    Args:
        text: Input text
        
    Returns:
        Tuple of (language: str, confidence: float)
    """
    return get_detector().detect(text)

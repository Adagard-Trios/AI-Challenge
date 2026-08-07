"""
Images: captured, read, and searchable.

A large share of what gets posted about a flood is a photograph -- a DMC
notice, a road-closure sign, a screenshot of a warning -- and none of it was
reaching the pipeline. The scrapers captured no image URLs at all, and the
Instagram scraper went further: it discarded any post whose caption was
shorter than MIN_TEXT_LEN, which is exactly the image-only post whose entire
content lives in the picture.

These tests hold the properties that make the feature honest rather than
merely present: that OCR text is labelled as machine-read, that a weak read is
marked rather than asserted, that "same photograph" and "looks similar" stay
distinct claims, and that an unreadable image never costs the post.
"""

import ast
import io
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _function(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"{path.name} has no function {name!r}")


# --- capture -----------------------------------------------------------------

def test_every_scraper_emits_images():
    """All four, or the feature only works on whichever one was remembered."""
    for platform in ("twitter", "facebook", "linkedin", "instagram"):
        source = (PROJECT_ROOT / "src" / "scrapers" / f"{platform}.py").read_text(
            encoding="utf-8")
        assert '"images"' in source, f"{platform} does not capture image URLs"


def test_image_only_posts_are_no_longer_discarded():
    """
    REGRESSION. `if not text or len(text) < MIN_TEXT_LEN: continue` threw away
    every caption-less post -- on Instagram a large share of them, and exactly
    the ones OCR exists to read.
    """
    source = (PROJECT_ROOT / "src" / "scrapers" / "instagram.py").read_text(
        encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    assert "if not text or len(text) < MIN_TEXT_LEN" not in code
    assert "and not images" in code, (
        "the skip does not consider whether the post has an image"
    )


def test_instagram_gets_caption_and_images_from_one_request():
    """
    Every request against a logged-in account spends daily budget, so fetching
    them separately would double the cost of the most expensive call we make.
    """
    text_py = PROJECT_ROOT / "src" / "scrapers" / "text.py"
    fn = _function(text_py, "fetch_media_via_private_api")
    assert "caption" in fn and "images" in fn
    assert "carousel_media" in fn, "a carousel's images would be missed"


def test_the_largest_candidate_is_chosen():
    """OCR on a thumbnail reads nothing useful."""
    fn = _function(PROJECT_ROOT / "src" / "scrapers" / "text.py", "_best_image_url")
    assert "area" in fn, "picks by list order rather than by resolution"


def test_avatars_and_icons_are_filtered_out():
    source = (PROJECT_ROOT / "src" / "scrapers" / "text.py").read_text(encoding="utf-8")
    assert "profile_pic" in source or "profile_images" in source
    assert "MIN_IMAGE_DIMENSION" in source


# --- OCR ---------------------------------------------------------------------

def test_ocr_reads_text_from_an_image():
    """The whole feature, exercised for real rather than mocked."""
    pytest.importorskip("rapidocr_onnxruntime")
    from PIL import Image, ImageDraw

    from src.images.pipeline import _read_text

    import tempfile

    image = Image.new("RGB", (900, 200), "white")
    ImageDraw.Draw(image).text((30, 80), "FLOOD WARNING RATNAPURA", fill="black")
    path = Path(tempfile.mkdtemp()) / "notice.png"
    image.save(path)

    text, confidence = _read_text(path)
    assert "FLOOD" in text.upper()
    assert "RATNAPURA" in text.upper()
    assert confidence and confidence > 0.5


def test_script_detection_is_exact_not_probabilistic():
    """
    Sinhala and Tamil occupy distinct Unicode blocks, so this is decidable.
    Exactness matters because it decides whether to trust a read.
    """
    from src.images.pipeline import _detect_script

    assert _detect_script("FLOOD WARNING") == "english"
    assert _detect_script("ගංවතුර අනතුරු") == "sinhala"
    assert _detect_script("வெள்ள எச்சரிக்கை") == "tamil"
    assert _detect_script("12345 !!") == "unknown"


def test_extracted_text_is_labelled_as_machine_read():
    """
    A reader of the resulting event should be able to tell which words a human
    typed and which a machine read off a photograph. They deserve different
    levels of trust, and these are natural-scene images, not scans.
    """
    from src.images.pipeline import ImageResult, text_from

    result = ImageResult(url="u", ocr_text="EVACUATE NOW")
    assert "[text in image]" in text_from([result])
    assert text_from([]) == "", "empty results should add nothing"


def test_a_weak_read_is_kept_but_marked():
    """
    Discarding it loses signal; presenting it unqualified asserts text that may
    not have been there. Storing the score allows the UI to do neither.
    """
    source = (PROJECT_ROOT / "src" / "images" / "pipeline.py").read_text(encoding="utf-8")
    assert "MIN_OCR_CONFIDENCE" in source
    assert "ocr_confidence" in source

    from auth.models import PostImage

    assert "ocr_confidence" in {c.name for c in PostImage.__table__.columns}


def test_an_unreadable_image_never_costs_the_post():
    for name in ("process_image", "ingest_post_images"):
        fn = _function(PROJECT_ROOT / "src" / "images" / "pipeline.py", name)
        assert "except Exception" in fn


def test_downloads_are_bounded():
    """A server is free to lie about Content-Length."""
    fn = _function(PROJECT_ROOT / "src" / "images" / "pipeline.py", "_download")
    assert "MAX_IMAGE_BYTES" in fn
    assert "iter_content" in fn, "reads the whole body before checking its size"


# --- the text reaches classification -----------------------------------------

def test_ocr_text_is_appended_before_the_post_is_classified():
    """
    Doing it afterwards would mean severity, entities and stories were all
    decided without the contents of the image -- which on an image-only post is
    the entire post.
    """
    routes = PROJECT_ROOT / "src" / "social" / "routes.py"
    store = _function(routes, "_store")

    assert "ingest_post_images" in store
    assert "text_from" in store

    enriched = store.index("enriched")
    handoff = store.index("_to_intelligence_pipeline")
    assert enriched < handoff, (
        "the post is handed on before its images are read"
    )


# --- search ------------------------------------------------------------------

def test_same_image_and_similar_scene_stay_distinct():
    """
    They are different claims. Collapsing them into one score would let a loose
    visual resemblance read as proof that a photograph was reused.
    """
    source = (PROJECT_ROOT / "src" / "images" / "search.py").read_text(encoding="utf-8")
    assert '"same_image"' in source
    assert '"similar_scene"' in source


def test_the_hash_threshold_errs_toward_missing_a_match():
    """
    The output is "this photo is recycled", so a false positive is worse than a
    false negative.
    """
    from src.images.search import PHASH_MAX_DISTANCE

    assert 0 < PHASH_MAX_DISTANCE <= 16


def test_phash_search_works_without_clip():
    """
    CLIP is ~600 MB and downloads on first use. The layer that answers the
    actual question -- has this photograph been posted before -- must not wait
    on it.
    """
    from src.images.search import _hamming

    assert _hamming("ffff", "ffff") == 0
    assert _hamming("0000", "ffff") == 16
    assert _hamming("ffff", "") is None, "incomparable hashes must not score 0"


def test_clip_is_opt_in(monkeypatch):
    from src.images import search

    monkeypatch.delenv("ENABLE_CLIP_SEARCH", raising=False)
    assert search._clip_enabled() is False, (
        "CLIP on by default turns the first search into a multi-minute download"
    )
    monkeypatch.setenv("ENABLE_CLIP_SEARCH", "1")
    assert search._clip_enabled() is True


def test_no_face_recognition():
    """
    Identifying a specific person across platforms processes biometric data of
    people who never consented -- a special category under Sri Lanka's PDPA
    No. 9 of 2022. Similarity search covers the legitimate uses without
    building an identity index. If this ever changes it should be a deliberate
    act, not a quiet commit.
    """
    images = PROJECT_ROOT / "src" / "images"
    for path in images.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for term in ("face_recognition", "insightface", "facenet",
                     "dlib", "face_encodings", "arcface"):
            assert term not in text, f"{path.name} references {term!r}"


def test_image_search_is_readable_by_any_signed_in_user():
    """
    Unlike the credential routes it touches no session and reads only
    already-collected intelligence, so a viewer can verify a photograph.
    """
    source = (PROJECT_ROOT / "src" / "social" / "routes.py").read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "search_images"
    )
    body = ast.get_source_segment(source, fn) or ""
    assert "require_user" in body
    assert "require_admin" not in body


# --- both collection paths read images, not just one -------------------------

def test_the_agent_path_reads_images_too():
    """
    REGRESSION, and the same shape as every gap before it: a feature that works
    on one path and silently does not on the other.

    Images were read in _store() -- the "Collect now" button -- and nowhere
    else. The agent loop reaches scraping through scraper_registry.run(), so
    automatic collection captured image URLs and threw them away. An image-only
    flood notice collected by the agent would have arrived with no text at all.
    """
    source = (PROJECT_ROOT / "src" / "scrapers" / "registry.py").read_text(
        encoding="utf-8")
    assert "_read_images(" in source, (
        "registry.run does not read images, so the agent loop discards them"
    )

    fn = _function(PROJECT_ROOT / "src" / "scrapers" / "registry.py", "_read_images")
    assert "process_image" in fn
    assert "[text in image]" in fn, "extracted text is not labelled"


def test_the_hook_is_on_the_shared_seam():
    """
    run() is where the agent tools, Collect now and the selftest all arrive.
    Enriching in a caller instead is exactly how the gap happened.
    """
    fn = _function(PROJECT_ROOT / "src" / "scrapers" / "registry.py", "run")
    assert "_read_images(" in fn


def test_reading_images_never_costs_the_posts():
    fn = _function(PROJECT_ROOT / "src" / "scrapers" / "registry.py", "_read_images")
    assert "except Exception" in fn
    assert "return" in fn


def test_posts_without_images_are_left_alone():
    """A no-op path must not touch the text or pay for an import."""
    from src.scrapers.registry import _read_images

    payload = {"posts": [{"text": "plain post", "images": []}]}
    _read_images(payload)
    assert payload["posts"][0]["text"] == "plain post"


# --- the extracted text is visible, not just stored --------------------------

def test_collected_posts_api_returns_the_extracted_text():
    """
    Stored since the image pipeline landed and exposed nowhere, so the panel
    could not explain why an apparently empty post had been kept -- which on an
    image-only post is the entire content.
    """
    import ast

    source = (PROJECT_ROOT / "auth" / "routes.py").read_text(encoding="utf-8")
    fn = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef) and n.name == "recent_ingested"
    )
    body = ast.get_source_segment(source, fn) or ""

    assert '"images"' in body
    assert '"ocr_text"' in body
    assert '"ocr_confidence"' in body, (
        "confidence is not exposed, so a weak read cannot be marked as one"
    )


def test_the_ui_marks_a_low_confidence_read():
    panel = (
        PROJECT_ROOT.parent / "frontend" / "app" / "components" / "settings"
        / "CollectedPosts.tsx"
    )
    if not panel.exists():
        pytest.skip("frontend not present")

    text = panel.read_text(encoding="utf-8")
    assert "Text in image" in text
    assert "uncertain" in text.lower(), (
        "a weak extraction is presented as if it were certainly there"
    )


# --- the dependencies are recorded -------------------------------------------

def test_the_image_dependencies_are_declared():
    """
    Installed with `uv pip install`, which updates the venv and nothing else --
    so a fresh checkout would import-error at runtime rather than fail to
    install.
    """
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for package in ("imagehash", "rapidocr-onnxruntime"):
        assert package in pyproject, f"{package} is not in pyproject.toml"

    lock = (PROJECT_ROOT / "uv.lock").read_text(encoding="utf-8")
    for package in ("imagehash", "rapidocr-onnxruntime"):
        assert f'name = "{package}"' in lock, f"{package} is not in uv.lock"

    for requirements in ("requirements.txt", "requirements-service.txt"):
        text = (PROJECT_ROOT / requirements).read_text(encoding="utf-8")
        assert "rapidocr" in text, f"{requirements} omits the OCR engine"

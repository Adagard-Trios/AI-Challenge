"""
src/images
Pictures attached to collected posts: fetched, hashed, read, and searchable.

WHY THIS EXISTS
---------------
A large share of what gets posted about a flood is a photograph -- a DMC
notice, a road-closure sign, a screenshot of a warning -- and none of it was
reaching the intelligence pipeline. The scrapers captured no image URLs at all,
and the Instagram scraper went further: it *discarded* any post whose caption
was shorter than MIN_TEXT_LEN, which is exactly the image-only post whose
content lives entirely in the picture.

So this module does three things:

  1. Fetches the images a post carries, once, deduplicated by perceptual hash.
  2. Reads the text in them, and appends it to the post text BEFORE
     classification -- so severity, entities, stories and relevance all see it
     without any change to the agent nodes.
  3. Makes them searchable by picture rather than by word.

ON THE OCR ENGINE
-----------------
The plan named PaddleOCR-VL, which tops the current document benchmarks. It is
served here through **RapidOCR**, which runs the same PP-OCR models on
onnxruntime -- already a dependency via chromadb -- instead of through
paddlepaddle, whose Windows install is large and routinely breaks. Same models,
a fraction of the install risk, and no torch on the critical path.

Verified end to end on a rendered test image: "FLOOD WARNING RATNAPURA" read
back exactly.

WHAT IT WILL NOT DO WELL
------------------------
These are natural-scene photographs, not scanned documents, so expect worse
than the document benchmarks advertise. Sinhala is the weak point -- it is
genuinely under-served by every general engine, which is why the 2025
low-resource OCR study exists. Confidence is therefore stored per image and
surfaced, so a poor read is marked rather than presented as text that was
definitely there.
"""

from .pipeline import (  # noqa: F401
    ImageResult,
    ingest_post_images,
    ocr_available,
)
from .search import (  # noqa: F401
    search_by_image,
)

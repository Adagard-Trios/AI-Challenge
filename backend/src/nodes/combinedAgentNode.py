"""
src/nodes/combinedAgentNode.py
COMPLETE IMPLEMENTATION - Orchestration nodes for Roger Mother Graph
Implements: GraphInitiator, FeedAggregator, DataRefresher
UPDATED: Supports 'Opportunity' tracking and new Scoring Logic
"""

from __future__ import annotations
import json
import logging
import os
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

# Import storage manager for production-grade persistence
from src.storage.storage_manager import StorageManager

# Canonical names for the things events are about. Relevance scoring is a join
# between event entities and a user's exposure, and that join only works if both
# sides agree on the name -- see src/intelligence/taxonomy.py.
from src.intelligence.taxonomy import canonicalise_many
from src.intelligence.stories import get_story_tracker

# Import trending detector for velocity metrics
try:
    from src.utils.trending_detector import get_trending_detector, record_topic_mention

    TRENDING_ENABLED = True
except ImportError:
    TRENDING_ENABLED = False


# --- trending topics ---------------------------------------------------------
#
# A "topic" used to be the first five words of the event summary, lowercased:
#
#     words = summary.split()[:5]
#
# That is not a topic, it is a prefix, and the dashboard showed what you would
# expect from one. "Sri Lanka Economy (Sri Lanka" trended at 50x -- five words
# ending inside a parenthesis it never closed -- alongside "passed", "social"
# and "presence", which are the incidental words that happened to sit in
# position four of some summary.
#
# Two better sources, in order. The pipeline already extracts entities and
# canonicalises them through the taxonomy, so five spellings of "Colombo Port"
# are one entry; those ARE topics and cost nothing to reuse. Where the
# extractor did not run, capitalised phrases are a far better guess than a
# prefix, because what trends in news is named things.

# Anything shorter is an abbreviation or noise once stopwords are gone.
_MIN_TOPIC_CHARS = 4
_MAX_TOPICS_PER_EVENT = 4

# Leading "Sri Lanka Economy (Sri Lanka Economy):" style labels the scrapers
# prepend. They are the source, not the subject, and they produced the
# unbalanced parenthesis in the trending list.
_SOURCE_LABEL = re.compile(r"^[^:]{0,60}?\([^)]{0,60}\)\s*:\s*")
# Runs of capitalised words: "Ministry of Education", "Asiri Hospitals".
_PROPER_NOUN = re.compile(
    r"\b([A-Z][\w’'-]+(?:\s+(?:of|and|for|the)\s+[A-Z][\w’'-]+|\s+[A-Z][\w’'-]+){0,3})"
)
# "The Gazette" and "Gazette" are the same topic and must not be counted twice.
_ARTICLE = re.compile(r"^(?:The|A|An)\s+")


def topics_from_event(item: dict) -> List[str]:
    """
    Topics worth counting for a trending signal.

    Deliberately returns fewer topics rather than filling a quota: a bad topic
    does not merely fail to be useful, it competes with real ones for the five
    slots the dashboard shows.
    """
    from src.utils.trending_detector import TRENDING_STOPWORDS

    def acceptable(candidate: str) -> bool:
        cleaned = candidate.strip(" .,:;()[]\"'").strip()
        if len(cleaned) < _MIN_TOPIC_CHARS:
            return False
        lowered = cleaned.lower()
        if lowered in TRENDING_STOPWORDS:
            return False
        # A phrase made entirely of stopwords is still noise.
        parts = [p for p in lowered.split() if p not in TRENDING_STOPWORDS]
        return bool(parts)

    out: List[str] = []
    seen = set()

    def add(candidate: str) -> None:
        cleaned = candidate.strip(" .,:;()[]\"'").strip()
        key = cleaned.lower()
        if key and key not in seen and acceptable(cleaned):
            seen.add(key)
            out.append(cleaned)

    # 1. Canonicalised entities, when the extractor ran on this event.
    for entity in item.get("entities") or []:
        if isinstance(entity, dict) and entity.get("name"):
            add(str(entity["name"]))
        if len(out) >= _MAX_TOPICS_PER_EVENT:
            return out

    # 2. Otherwise, the named things in the summary.
    summary = _SOURCE_LABEL.sub("", str(item.get("summary") or ""), count=1)

    # Where a sentence begins. A capital letter there is grammar, not a name --
    # it is why "What", "Correction" and "Limited" were being counted as
    # trending topics.
    sentence_starts = {0}
    for boundary in re.finditer(r"[.!?]\s+", summary):
        sentence_starts.add(boundary.end())

    for match in _PROPER_NOUN.finditer(summary):
        phrase = match.group(1)
        # Multi-word phrases survive at a sentence start ("Ministry of Lands
        # has ruled..."); a lone capitalised word there does not.
        if match.start() in sentence_starts and len(phrase.split()) == 1:
            continue
        add(_ARTICLE.sub("", phrase, count=1))
        if len(out) >= _MAX_TOPICS_PER_EVENT:
            break

    return out


def _salvage_json_objects(content: str) -> List[Dict[str, Any]]:
    """
    Every complete top-level object in a possibly-truncated JSON array.

    Scans with a brace counter rather than a regex, because the objects contain
    nested objects (entities) and a regex cannot match balanced braces. Strings
    are tracked so a brace inside a summary -- which happens -- does not
    unbalance the count.

    Returns [] when nothing complete is present, so the caller can re-raise and
    fall back to unfiltered rather than silently reporting success.
    """
    objects: List[Dict[str, Any]] = []
    malformed = 0
    depth = 0
    start = None
    in_string = False
    escaped = False

    for index, char in enumerate(content):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    objects.append(json.loads(content[start:index + 1]))
                except json.JSONDecodeError:
                    # Counted, not swallowed. Skipping a malformed object IS
                    # the intent here -- salvage takes the complete ones -- but
                    # a bare `pass` would make "the model emitted garbage" and
                    # "there was nothing to salvage" produce identical
                    # evidence, which is this project's recurring failure.
                    malformed += 1
                start = None
            elif depth < 0:
                depth = 0        # stray brace; resynchronise

    if malformed:
        # One line per salvage attempt, not per object: a badly truncated reply
        # can contain many fragments and a log per fragment is a log nobody
        # reads.
        logger.debug("[LLM_FILTER] salvage skipped %d malformed object(s)",
                     malformed)

    return objects


def _blackboard_enabled() -> bool:
    """
    Whether to mirror events onto the board.

    On by default and killable without a redeploy. The board is new and writes
    on the hot path of every cycle; a switch that needs a deploy to flip is not
    a switch you can use when something is wrong at 2am.
    """
    return os.getenv("BLACKBOARD_ENABLED", "1").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _shadow_write_board(events: List[Dict[str, Any]]) -> None:
    """
    Mirror classified events onto the blackboard. Best-effort, always.

    Nothing reads these yet -- this is the shadow stage, where the board is
    populated and observed before anything depends on it. Doing it in this
    order means the stage that starts consuming the board has real data to be
    judged against rather than an empty table and a hypothesis.
    """
    if not events or not _blackboard_enabled():
        return

    try:
        from src.blackboard.store import BoardStore
    except Exception:  # noqa: BLE001
        return

    store = BoardStore()
    written = 0
    failed = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        try:
            entity_names = [
                e.get("name") for e in (event.get("entities") or [])
                if isinstance(e, dict) and e.get("name")
            ]
            if store.record_event(
                event_id=event.get("event_id") or "",
                summary=event.get("summary") or "",
                domain=event.get("domain"),
                severity=event.get("severity"),
                impact_type=event.get("impact_type"),
                confidence=event.get("confidence"),
                entity_keys=entity_names,
                payload={
                    "region": event.get("region"),
                    "fake_news_score": event.get("fake_news_score"),
                    "llm_filtered": event.get("llm_filtered"),
                },
            ):
                written += 1
        except Exception:  # noqa: BLE001
            failed += 1
            continue

    if written:
        logger.info("[Blackboard] mirrored %d/%d events", written, len(events))
    if failed:
        # Counted rather than logged per event: a board that is entirely down
        # would otherwise produce one line per event per cycle. But it must
        # say something, or "mirrored 0" and "wrote nothing because there was
        # nothing" look the same.
        logger.warning("[Blackboard] %d/%d events could not be mirrored",
                       failed, len(events))


def _shadow_write_assessment(snapshot: Dict[str, Any]) -> None:
    """Mirror the risk snapshot onto the board. Best-effort."""
    if not snapshot or not _blackboard_enabled():
        return
    try:
        from src.blackboard.store import BoardStore

        BoardStore().record_assessment(snapshot=snapshot)
    except Exception as exc:  # noqa: BLE001
        # Logged, not swallowed. A bare `pass` here would make "the board is
        # broken" and "there was nothing to record" produce identical
        # evidence, which is the failure mode this project keeps hitting.
        logger.warning("[Blackboard] could not record the assessment: %s", exc)


def _write_foci(snapshot: Dict[str, Any]) -> None:
    """
    Turn the cheap signals this cycle already computed into board foci.

    NOTHING CONSUMES THESE YET, on purpose. This is the stage that answers
    whether opportunistic control is worth building: foci are written from real
    signals, the log records what a controller WOULD have prioritised, and that
    can be compared against what the fixed schedule actually collected. If the
    foci turn out to be uninformative, the right answer is to stop here -- and
    finding that out before building a scheduler is much cheaper than after.
    """
    if not _blackboard_enabled():
        return

    try:
        from src.blackboard import sensors
    except Exception:  # noqa: BLE001
        return

    written = 0
    try:
        written += len(sensors.from_trending(snapshot.get("spike_alerts") or []))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Blackboard] trending sensor failed: %s", exc)

    # RiverNet is read directly rather than from the snapshot: the snapshot
    # carries derived indices, not the station-level alerts, and the station
    # severity is the whole signal.
    try:
        from src.utils.utils import tool_rivernet_status

        written += len(sensors.from_rivernet(tool_rivernet_status()))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Blackboard] rivernet sensor failed: %s", exc)

    try:
        # recent() already carries the DERIVED state -- developing, escalating,
        # quiet, resolved -- computed from the timeline rather than stored, so
        # there is nothing to recompute here.
        tracker = get_story_tracker()
        written += len(sensors.from_stories(tracker.recent(limit=10) if tracker else []))
    except Exception as exc:  # noqa: BLE001
        logger.debug("[Blackboard] story sensor unavailable: %s", exc)

    if written:
        logger.info("[Blackboard] %d foci written or reinforced", written)
    sensors.report_what_control_would_do()


def _run_shadow_controller() -> None:
    """
    Compute the agenda a scheduler would follow, record it, and run nothing.

    The fan-out above has already collected everything this cycle, unchanged.
    What this adds is a checkable record of what a controller would have
    SKIPPED -- so that before collection is handed to it, we can ask whether
    those runs were actually producing anything.

    The risk being managed is specific: opportunistic control yields less data,
    not obviously smarter data, and "the feed looks dead" is a failure this
    project has hit repeatedly and been slow to notice each time.
    """
    if not _blackboard_enabled():
        return
    try:
        from src.blackboard import controller

        controller.tick()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Blackboard] controller tick failed: %s", exc)


def _run_decay_pass() -> None:
    """
    Age the board and delete what has stopped describing the present.

    Also closes two leaks that predate the board entirely: ChromaDB had no
    delete method at all, so the semantic corpus grew forever, and
    trending_detector.cleanup_old_data has always been defined and never
    called.
    """
    if not _blackboard_enabled():
        return
    try:
        from src.blackboard import maintenance

        maintenance.run()
    except Exception as exc:  # noqa: BLE001
        logger.debug("[Blackboard] maintenance skipped: %s", exc)


logger = logging.getLogger("combined_node")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(ch)


class CombinedAgentNode:
    """
    Orchestration nodes for the Mother Graph (CombinedAgentState).

    Implements the Fan-In logic after domain agents complete:
    1. GraphInitiator - Starts each iteration & Clears previous state
    2. FeedAggregator - Collects and ranks domain insights (Risks & Opportunities)
    3. DataRefresher - Updates risk dashboard
    4. DataRefreshRouter - Decides to loop or end
    """

    def __init__(self, llm):
        self.llm = llm
        # Initialize production storage manager
        self.storage = StorageManager()
        # Track seen summaries for corroboration scoring
        self._seen_summaries_count: Dict[str, int] = {}
        logger.info(
            "[CombinedAgentNode] Initialized with production storage layer + LLM filter"
        )

    # =========================================================================
    # LLM POST FILTER - Quality control and enhancement
    # =========================================================================

    # Posts per LLM call. The filter used to run once per post, serially,
    # inside a 60s loop -- 50-150 sequential Groq calls per cycle, which is both
    # slow and the reason rate limiting was hit routinely. Batching by domain
    # brings a typical cycle to roughly one call per agent.
    LLM_FILTER_BATCH_SIZE = 12

    # Per-post input budget inside a batch. Lower than the 1500 used for a
    # single post, since a dozen share one context window.
    LLM_FILTER_INPUT_CHARS = 600

    @staticmethod
    def _guess_region(summary: str) -> str:
        lowered = summary.lower()
        return (
            "sri_lanka"
            if any(kw in lowered for kw in ["sri lanka", "colombo", "kandy", "galle"])
            else "world"
        )

    def _unfiltered_result(self, summary: str) -> Dict[str, Any]:
        """
        The honest failure shape.

        The old fallback returned severity="medium" and fake_news_score=0.3 --
        values no model produced. A throttled run therefore filled the dashboard
        with invented scores that were indistinguishable from real ones, and
        only a logger.warning recorded it.

        severity and fake_news_score are None here, which the caller reads as
        "unknown": it falls back to the agent's own keyword-derived severity and
        applies no fake-news penalty. llm_filtered=False travels with the event
        so downstream consumers can tell verified from unverified.
        """
        words = summary.split()
        return {
            "keep": True,
            "enhanced_summary": " ".join(words[:200]) if len(words) > 200 else summary,
            "severity": None,
            "fake_news_score": None,
            # No model ran, so nothing was extracted. Not an empty verdict.
            "entities": [],
            "entities_extracted": False,
            "region": self._guess_region(summary),
            "confidence_boost": 0.0,
            "original_summary": summary,
            "llm_filtered": False,
        }

    # Stories whose briefs are refreshed in one call per cycle. The cap is what
    # keeps this at ONE additional LLM call regardless of how many stories are
    # live -- a per-story call would put the cost back on a 60s loop, which is
    # the mistake the post filter already made once.
    STORY_BRIEF_BATCH = 8

    def regenerate_story_briefs(self) -> int:
        """
        Refresh the briefs of stories that have moved.

        Dataminr's ReGenAI regenerates an event brief as the event unfolds;
        this is that, batched. Returns how many briefs were rewritten.

        A story whose brief could not be regenerated keeps its previous text
        and is marked stale. An old brief beats no brief, but the UI has to be
        able to say which one it is showing.
        """
        tracker = get_story_tracker()
        pending = tracker.stories_needing_a_brief(limit=self.STORY_BRIEF_BATCH)
        if not pending:
            return 0

        numbered = "\n\n".join(
            f"[{i}] ({s['event_count']} reports, peak severity {s['peak_severity']})\n"
            f"Current brief: {str(s['brief'])[:400]}"
            for i, s in enumerate(pending)
        )

        prompt = f"""These {len(pending)} ongoing stories have received new reports.
Rewrite each brief to reflect the story as it now stands.

STORIES:
{numbered}

Respond with a JSON array only, one object per story, using the bracketed
number as "id":
[{{"id": 0, "title": "Short headline, max 12 words", "brief": "2-3 sentences on what is happening and what changed"}}]

Rules:
1. Write the CURRENT state, not a changelog. A reader arriving now should
   understand the situation without reading earlier versions.
2. Keep concrete facts -- places, numbers, named organisations.
3. Do not speculate beyond what the reports say.
4. Return exactly {len(pending)} objects, ids 0 to {len(pending) - 1}.

JSON array only:"""

        try:
            response = self.llm.invoke(prompt)
            content = (
                response.content if hasattr(response, "content") else str(response)
            )
            verdicts = self._parse_batch_response(content, len(pending))
        except Exception as exc:
            logger.warning(
                "[Stories] brief regeneration failed for %d stories (%s); "
                "keeping previous briefs and marking them stale",
                len(pending), exc,
            )
            for story in pending:
                tracker.save_brief(story["id"], None)
            return 0

        written = 0
        for i, story in enumerate(pending):
            verdict = verdicts.get(i) or {}
            brief = str(verdict.get("brief") or "").strip()
            if tracker.save_brief(story["id"], brief or None):
                written += 1

        missed = len(pending) - written
        if missed:
            logger.warning(
                "[Stories] %d of %d briefs were not regenerated and are marked "
                "stale", missed, len(pending),
            )
        return written

    def _parse_batch_response(self, content: str, count: int) -> Dict[int, Dict]:
        """
        Parse one batch reply into {index: verdict}.

        Indices missing from the reply are simply absent, so the caller marks
        them unfiltered rather than assuming a verdict.
        """
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```\w*\n?", "", content)
            content = re.sub(r"\n?```$", "", content)

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            # Salvage whatever completed.
            #
            # agent_model() is a REASONING model with no max_tokens set, so it
            # spends budget thinking before it writes and the array is
            # regularly cut off mid-object:
            #
            #   [LLM_FILTER] intelligence batch of 6 failed
            #       (Expecting value: line 58 column 18 (char 2244))
            #
            # json.loads on the whole string then loses EVERY verdict in the
            # batch, including the ones the model finished perfectly. Measured
            # on a real cycle: 6 of 15 events came through unclassified, with
            # no entities -- and entities are what relevance scoring joins on,
            # so those events could never match anyone's exposure.
            #
            # Parsing the complete objects out of a truncated array turns
            # "lose twelve" into "lose the one that was cut".
            parsed = _salvage_json_objects(content)
            if not parsed:
                raise
            logger.warning(
                "[LLM_FILTER] reply was not valid JSON; salvaged %d complete "
                "object(s) from it", len(parsed),
            )

        if isinstance(parsed, dict):
            # Tolerate {"results": [...]} as well as a bare array.
            parsed = parsed.get("results") or parsed.get("posts") or [parsed]
        if not isinstance(parsed, list):
            raise ValueError(f"expected a JSON array, got {type(parsed).__name__}")

        verdicts: Dict[int, Dict] = {}
        for position, entry in enumerate(parsed):
            if not isinstance(entry, dict):
                continue
            # Prefer the model's own id; fall back to positional order.
            try:
                idx = int(entry.get("id", position))
            except (TypeError, ValueError):
                idx = position
            if 0 <= idx < count:
                verdicts[idx] = entry
        return verdicts

    def _llm_filter_batch(
        self, summaries: List[str], domain: str
    ) -> List[Dict[str, Any]]:
        """Filter and enhance up to LLM_FILTER_BATCH_SIZE posts in one call."""
        numbered = "\n\n".join(
            f"[{i}] {s[: self.LLM_FILTER_INPUT_CHARS]}"
            for i, s in enumerate(summaries)
        )

        filter_prompt = f"""Analyze these {len(summaries)} news posts for quality and classification.

DOMAIN: {domain}

POSTS:
{numbered}

Respond with a JSON array only (no markdown, no explanation), one object per
post, using the post's bracketed number as "id":
[
  {{
    "id": 0,
    "keep": true/false,
    "fake_news_probability": 0.0-1.0,
    "severity": "low/medium/high/critical",
    "region": "sri_lanka/world",
    "enhanced_summary": "Cleaned, concise summary (max 200 words)",
    "is_meaningful": true/false,
    "entities": [
      {{"type": "PLACE|ORG|SECTOR|INFRASTRUCTURE|LANE", "name": "...", "role": "affected|actor|mentioned"}}
    ]
  }}
]

Rules:
1. keep=false if: spam, ads, meaningless text, or fake_news_probability > 0.7
2. severity: critical=emergency/disaster, high=significant impact, medium=notable, low=informational
3. region: "sri_lanka" if about Sri Lanka, otherwise "world"
4. enhanced_summary: Clean, professional, max 200 words. Keep key facts.
5. is_meaningful: false if no actionable intelligence or just social chatter
6. entities: the real-world things this post is about, so a business can tell
   whether it affects them. Extract only what the text actually names.
   - PLACE: a Sri Lankan district, city or region (e.g. "Gampaha", "Colombo")
   - ORG: a named company, ministry or authority (e.g. "CEB", "Hayleys")
   - SECTOR: an industry (e.g. "apparel", "tea", "logistics", "banking")
   - INFRASTRUCTURE: a port, airport, expressway or utility network
   - LANE: a named trade route or corridor
   role: "affected" if the thing is impacted, "actor" if it is doing something,
   "mentioned" otherwise. Use [] when the post names nothing concrete -- do not
   invent entities to fill the field.
7. Return exactly {len(summaries)} objects, ids 0 to {len(summaries) - 1}.

JSON array only:"""

        try:
            response = self.llm.invoke(filter_prompt)
            content = (
                response.content if hasattr(response, "content") else str(response)
            )
            verdicts = self._parse_batch_response(content, len(summaries))
        except Exception as exc:
            logger.warning(
                "[LLM_FILTER] %s batch of %d failed (%s); "
                "posts pass through unfiltered and are marked as such",
                domain,
                len(summaries),
                exc,
            )
            return [self._unfiltered_result(s) for s in summaries]

        missing = len(summaries) - len(verdicts)
        if missing:
            logger.warning(
                "[LLM_FILTER] %s batch returned %d/%d verdicts; the rest are "
                "marked unfiltered",
                domain,
                len(verdicts),
                len(summaries),
            )

        results = []
        for i, summary in enumerate(summaries):
            verdict = verdicts.get(i)
            if verdict is None:
                results.append(self._unfiltered_result(summary))
                continue

            try:
                fake_score = float(verdict.get("fake_news_probability", 0.5))
            except (TypeError, ValueError):
                fake_score = 0.5

            keep = bool(verdict.get("keep", False)) and bool(
                verdict.get("is_meaningful", False)
            )
            if fake_score > 0.7:
                keep = False

            enhanced = verdict.get("enhanced_summary") or summary
            words = str(enhanced).split()
            if len(words) > 200:
                enhanced = " ".join(words[:200])

            # Entities drive relevance scoring, so "the model returned none"
            # and "the model never answered" must not look the same. An absent
            # key means the reply did not carry the field at all -- a prompt or
            # parsing problem worth surfacing. An empty list is a real verdict:
            # this post names nothing concrete.
            raw_entities = verdict.get("entities")
            extracted = raw_entities is not None
            entities = canonicalise_many(raw_entities) if extracted else []

            results.append(
                {
                    "entities": entities,
                    "entities_extracted": extracted,
                    "keep": keep,
                    "enhanced_summary": enhanced,
                    "severity": verdict.get("severity"),
                    "fake_news_score": fake_score,
                    "region": verdict.get("region", "sri_lanka"),
                    "confidence_boost": self._calculate_corroboration_boost(summary),
                    "original_summary": summary,
                    "llm_filtered": True,
                }
            )
        return results

    def _llm_filter_posts(
        self, posts: List[Dict[str, Any]]
    ) -> List[Optional[Dict[str, Any]]]:
        """
        Filter every post, batching one LLM call per domain chunk.

        Returns a list aligned 1:1 with `posts`. None means the post was
        rejected before reaching the model (too short to judge).
        """
        results: List[Optional[Dict[str, Any]]] = [None] * len(posts)

        by_domain: Dict[str, List[int]] = {}
        for i, post in enumerate(posts):
            summary = str(post.get("summary", ""))
            if not summary or len(summary.strip()) < 20:
                results[i] = {"keep": False, "reason": "too_short"}
                continue
            by_domain.setdefault(str(post.get("domain", "unknown")), []).append(i)

        calls = 0
        for domain, indices in by_domain.items():
            for start in range(0, len(indices), self.LLM_FILTER_BATCH_SIZE):
                chunk = indices[start : start + self.LLM_FILTER_BATCH_SIZE]
                summaries = [str(posts[i].get("summary", "")) for i in chunk]
                calls += 1
                for i, result in zip(chunk, self._llm_filter_batch(summaries, domain)):
                    results[i] = result

        logger.info(
            "[LLM_FILTER] %d posts across %d domains in %d LLM call(s)",
            sum(len(v) for v in by_domain.values()),
            len(by_domain),
            calls,
        )
        return results

    def _calculate_corroboration_boost(self, summary: str) -> float:
        """
        Calculate confidence boost based on similar news corroboration.
        More sources reporting similar news = higher confidence.
        """
        try:
            # Each corroborating source adds 0.1, capped at 0.3.
            #
            # This used to be `min(0.3, 0.1)` -- a constant 0.1 whenever ANY
            # match existed. The comment described counting sources; the code
            # never counted anything, so a story corroborated by six outlets
            # scored exactly the same as one corroborated by a single tweet.
            similar = self.storage.chromadb.find_similar(summary, threshold=0.75)
            if not similar:
                return 0.0
            corroborations = len(similar) if isinstance(similar, (list, tuple)) else 1
            return min(0.3, 0.1 * corroborations)
        except Exception as exc:
            logger.debug("[Corroboration] lookup failed: %s", exc)
            return 0.0

    # =========================================================================
    # 1. GRAPH INITIATOR
    # =========================================================================

    def graph_initiator(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Initialization step executed at START in the graph.

        Responsibilities:
        - Increment run counter
        - Timestamp the execution

        Returns:
            Dict updating run_count, last_run_ts, and clearing data lists
        """
        logger.info("[GraphInitiator] ===== STARTING GRAPH ITERATION =====")

        current_run = getattr(state, "run_count", 0)
        new_run_count = current_run + 1

        logger.info(f"[GraphInitiator] Run count: {new_run_count}")
        logger.info(f"[GraphInitiator] Timestamp: {datetime.utcnow().isoformat()}")

        return {
            "run_count": new_run_count,
            "last_run_ts": datetime.utcnow(),
            # No "domain_insights" key at all.
            #
            # This used to send the string "RESET" to trigger a sentinel branch
            # in the reducer. main.py builds a fresh CombinedAgentState every
            # cycle, so the list is already empty when this node runs and the
            # sentinel cleared nothing -- while forcing every reader of
            # domain_insights to defend against a str where a list is declared.
            "final_ranked_feed": [],
        }

    # =========================================================================
    # 2. FEED AGGREGATOR AGENT
    # =========================================================================

    def feed_aggregator_agent(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        CRITICAL NODE: Aggregates outputs from all domain agents.

        This implements the "Fan-In (Reduce Phase)" from your architecture:
        - Collects domain_insights from all agents
        - Deduplicates similar events
        - Ranks by risk_score + severity + impact_type
        - Converts to ClassifiedEvent format

        Input: domain_insights (List[Dict]) from state
        Output: final_ranked_feed (List[Dict])
        """
        logger.info("[FeedAggregatorAgent] ===== AGGREGATING DOMAIN INSIGHTS =====")

        # Step 1: Gather domain insights
        # Note: In the new state model, this will be a List[Dict] gathered from parallel agents
        incoming = getattr(state, "domain_insights", [])

        # Defensive, and kept even though the "RESET" sentinel that produced a
        # str here is gone: domain_insights is reduced, and a reducer that ever
        # receives the wrong type would otherwise fail deep inside the flatten
        # below rather than here.
        if isinstance(incoming, str):
            incoming = []

        if not incoming:
            logger.warning("[FeedAggregatorAgent] No domain insights received!")
            return {"final_ranked_feed": []}

        # Step 2: Flatten nested lists
        # Some agents may return [[insight], [insight]] due to reducer logic
        flattened: List[Dict[str, Any]] = []
        for item in incoming:
            if isinstance(item, list):
                flattened.extend(item)
            else:
                flattened.append(item)

        logger.info(
            f"[FeedAggregatorAgent] Received {len(flattened)} raw insights from domain agents"
        )

        # Step 3: PRODUCTION DEDUPLICATION - 3-tier pipeline (SQLite → ChromaDB → Accept)
        unique: List[Dict[str, Any]] = []
        dedup_stats = {
            "exact_matches": 0, "semantic_matches": 0, "unique_events": 0,
            # Semantic duplicates that became part of a story, and those that
            # could not be (no database). Kept apart so a disabled feature
            # never reads as a working one.
            "threaded": 0, "thread_failed": 0,
        }
        story_tracker = get_story_tracker()

        for ins in flattened:
            summary = str(ins.get("summary", "")).strip()
            if not summary:
                continue

            # Use storage manager's 3-tier deduplication
            is_dup, reason, match_data = self.storage.is_duplicate(summary)

            if is_dup:
                if reason == "exact_match":
                    dedup_stats["exact_matches"] += 1
                elif reason == "semantic_match":
                    dedup_stats["semantic_matches"] += 1
                    # A semantic match is not noise to discard -- it is the
                    # next instalment of a story already running. This is the
                    # only place the system knows two events belong together,
                    # and it used to spend that knowledge on
                    # link_similar_events(), which writes to Neo4j, which
                    # render.yaml disables. So a flood developing over three
                    # days was thirty-nine silently dropped events and no
                    # object anywhere representing the flood.
                    if match_data and "id" in match_data:
                        event_id = ins.get("source_event_id") or str(uuid.uuid4())
                        story_id = story_tracker.attach(
                            event_id=event_id,
                            matched_event_id=match_data["id"],
                            summary=summary,
                            severity=str(ins.get("severity", "low")),
                            domain=str(ins.get("domain", "unknown")),
                            similarity=match_data.get("similarity", 0.85),
                        )
                        if story_id:
                            dedup_stats["threaded"] += 1
                        else:
                            # Threading unavailable (no database). The event is
                            # still dropped, exactly as before -- but say so,
                            # rather than letting a disabled feature look active.
                            dedup_stats["thread_failed"] += 1
                continue

            # Event is unique - accept it
            dedup_stats["unique_events"] += 1
            unique.append(ins)

        logger.info(
            f"[FeedAggregatorAgent] Deduplication complete: "
            f"{dedup_stats['unique_events']} unique, "
            f"{dedup_stats['exact_matches']} exact dups, "
            f"{dedup_stats['semantic_matches']} semantic dups"
        )

        # Step 4: Rank by severity + Opportunity Logic

        # Severity is the only signal every agent actually emits, so it carries
        # the base score rather than acting as a bonus on top of a risk_score
        # that is never set.
        #
        # The previous formula was `risk_score + boost + opp_boost`, and NO node
        # anywhere sets risk_score -- so base was always 0.0 and the ceiling was
        # 0.0 + 0.3 + 0.2 + 0.1 = 0.6, below the 0.7 threshold at :528. The
        # "High Priority Events" tile was therefore mathematically pinned at 0,
        # and avg_confidence sat near 0.1, making every event look low-confidence.
        severity_base_map = {"low": 0.25, "medium": 0.45, "high": 0.7, "critical": 0.9}

        def calculate_score(item: Dict[str, Any]) -> float:
            """Composite score for Risks AND Opportunities."""
            severity = str(item.get("severity", "low")).lower()
            impact = str(item.get("impact_type", "risk")).lower()

            # Honour risk_score when an agent does provide one; otherwise fall
            # back to severity. Either way the range reaches 1.0.
            explicit = item.get("risk_score")
            base = (
                float(explicit) if explicit not in (None, "", 0, 0.0)
                else severity_base_map.get(severity, 0.25)
            )

            # Opportunities are High Priority too -- keep them near the top.
            opp_boost = 0.1 if impact == "opportunity" else 0.0

            return min(1.0, base + opp_boost)

        # Sort descending by score
        ranked = sorted(unique, key=calculate_score, reverse=True)

        logger.info("[FeedAggregatorAgent] Top 3 events by score:")
        for i, ins in enumerate(ranked[:3]):
            score = calculate_score(ins)
            domain = ins.get("domain", "unknown")
            impact = ins.get("impact_type", "risk")
            summary_preview = str(ins.get("summary", ""))[:80]
            logger.info(
                f"  {i+1}. [{domain}] ({impact}) Score={score:.3f} | {summary_preview}..."
            )

        # Step 5: LLM FILTER + Convert to ClassifiedEvent format + Store
        # Process each post through LLM for quality control
        converted: List[Dict[str, Any]] = []
        filtered_count = 0
        llm_processed = 0

        logger.info(
            f"[FeedAggregatorAgent] Processing {len(ranked)} posts through LLM filter..."
        )

        # One call per domain chunk rather than one per post.
        llm_results = self._llm_filter_posts(ranked)
        unverified_count = 0

        for ins, llm_result in zip(ranked, llm_results):
            event_id = ins.get("source_event_id") or str(uuid.uuid4())
            original_summary = str(ins.get("summary", ""))
            domain = ins.get("domain", "unknown")
            original_severity = ins.get("severity", "medium")
            impact_type = ins.get("impact_type", "risk")
            base_confidence = round(calculate_score(ins), 3)
            timestamp = datetime.utcnow().isoformat()

            llm_processed += 1

            # Skip if LLM says don't keep
            if not llm_result.get("keep", False):
                filtered_count += 1
                logger.debug(f"[LLM_FILTER] Filtered out: {original_summary[:60]}...")
                continue

            # Use LLM-enhanced data where the model actually produced it.
            # severity and fake_news_score are None when the call failed, so the
            # agent's own keyword-derived severity stands and no fake-news
            # penalty is applied -- rather than the old fallback, which invented
            # severity="medium" and fake_news_score=0.3 and let them reach the
            # dashboard indistinguishable from real verdicts.
            llm_filtered = bool(llm_result.get("llm_filtered", False))
            if not llm_filtered:
                unverified_count += 1

            summary = llm_result.get("enhanced_summary") or original_summary
            severity = llm_result.get("severity") or original_severity
            region = llm_result.get("region", "sri_lanka")
            fake_score = llm_result.get("fake_news_score")
            confidence_boost = llm_result.get("confidence_boost", 0.0)

            fake_penalty = (fake_score * 0.2) if fake_score is not None else 0.0

            # Final confidence = base + corroboration boost - fake penalty
            final_confidence = min(
                1.0, max(0.0, base_confidence + confidence_boost - fake_penalty)
            )

            # FRONTEND-COMPATIBLE FORMAT
            classified = {
                "event_id": event_id,
                "summary": summary,  # Frontend expects 'summary'
                "domain": domain,  # Frontend expects 'domain'
                "confidence": round(
                    final_confidence, 3
                ),  # Frontend expects 'confidence'
                "severity": severity,
                "impact_type": impact_type,
                "region": region,  # NEW: for sidebar filtering
                "fake_news_score": fake_score,  # None when unverified
                "llm_filtered": llm_filtered,  # False = model never judged this
                # What the event is ABOUT, canonicalised. This is what relevance
                # scoring joins against a business's exposure profile.
                "entities": llm_result.get("entities") or [],
                "entities_extracted": bool(llm_result.get("entities_extracted")),
                "timestamp": timestamp,
            }
            converted.append(classified)

            # Store in all databases (SQLite, ChromaDB, Neo4j).
            #
            # dedup_key is the ORIGINAL summary -- the text is_duplicate() was
            # called with further up. `summary` here is the LLM's rewrite, and
            # storing that as the dedup key meant the md5 could never match the
            # next cycle's lookup, so exact-match dedup never fired and the same
            # events were re-emitted every 60 seconds forever.
            #
            # region / fake_news_score / llm_filtered are computed above and
            # were not being persisted, so /api/feeds -- the endpoint the
            # frontend loads first -- served events without them. The sidebar's
            # region filter had nothing to filter on until a live update
            # arrived over the websocket with the in-memory copy.
            self.storage.store_event(
                event_id=event_id,
                summary=summary,
                domain=domain,
                severity=severity,
                impact_type=impact_type,
                confidence_score=final_confidence,
                timestamp=timestamp,
                dedup_key=original_summary,
                metadata={
                    "region": region,
                    "fake_news_score": fake_score,
                    "llm_filtered": llm_filtered,
                },
                entities=classified["entities"],
            )

        logger.info(
            f"[FeedAggregatorAgent] LLM Filter: {llm_processed} processed, {filtered_count} filtered out"
        )
        if unverified_count:
            # Loud on purpose. This is the state the old fallback hid: events
            # reaching the dashboard that no model ever actually judged.
            logger.warning(
                "[FeedAggregatorAgent] %d of %d events were NOT verified by the "
                "LLM (call failed or verdict missing) and carry the agent's own "
                "severity with llm_filtered=False",
                unverified_count,
                len(converted),
            )
        if dedup_stats["threaded"]:
            logger.info(
                "[FeedAggregatorAgent] %d duplicate(s) threaded into ongoing "
                "stories rather than discarded", dedup_stats["threaded"],
            )
        if dedup_stats["thread_failed"]:
            logger.warning(
                "[FeedAggregatorAgent] %d duplicate(s) could not be threaded "
                "(no database) and were dropped as before",
                dedup_stats["thread_failed"],
            )

        # One batched call, after the feed is settled, and only for stories that
        # actually moved this cycle.
        try:
            rewritten = self.regenerate_story_briefs()
            if rewritten:
                logger.info("[Stories] regenerated %d brief(s)", rewritten)
        except Exception as exc:
            # Never let a brief take down the cycle that produced the feed.
            logger.error("[Stories] brief regeneration raised: %s", exc)

        logger.info(
            f"[FeedAggregatorAgent] ===== PRODUCED {len(converted)} QUALITY EVENTS ====="
        )

        # NEW: Step 6 - Create categorized feeds for frontend display
        categorized = {
            "political": [],
            "economical": [],
            "social": [],
            "meteorological": [],
            "intelligence": [],
        }

        for ins in flattened:
            domain = ins.get("domain", "unknown")
            structured_data = ins.get("structured_data", {})

            # Skip if no structured data or unknown domain
            if not structured_data or domain not in categorized:
                continue

            # Extract and add feeds for this domain
            domain_feeds = self._extract_feeds(structured_data, domain)
            categorized[domain].extend(domain_feeds)

        # Log categorized counts
        for domain, items in categorized.items():
            logger.info(
                f"[FeedAggregatorAgent] {domain.title()}: {len(items)} categorized items"
            )

        # Shadow-write to the blackboard.
        #
        # Nothing reads this yet. It runs here because `converted` is already
        # exactly the shape the board wants -- classified, deduplicated,
        # entity-extracted -- so mirroring it costs one write per event and no
        # recomputation.
        #
        # Placed AFTER the return value is built, and wrapped, because the
        # board is an enrichment: losing it must never cost the feed.
        _shadow_write_board(converted)

        return {"final_ranked_feed": converted, "categorized_feeds": categorized}

    def _extract_feeds(
        self, structured_data: Dict[str, Any], domain: str
    ) -> List[Dict[str, Any]]:
        """
        Helper to extract and flatten feed items from structured_data.
        Converts nested structured_data into a flat list of feed items.
        """
        extracted = []

        for category, items in structured_data.items():
            # Handle list items (actual feed data)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        feed_item = {
                            **item,
                            "domain": domain,
                            "category": category,
                            "timestamp": item.get(
                                "timestamp", datetime.utcnow().isoformat()
                            ),
                        }
                        extracted.append(feed_item)

            # Handle dictionary items (e.g., intelligence profiles/competitors)
            elif isinstance(items, dict):
                for key, value in items.items():
                    if isinstance(value, list):
                        for item in value:
                            if isinstance(item, dict):
                                feed_item = {
                                    **item,
                                    "domain": domain,
                                    "category": category,
                                    "subcategory": key,
                                    "timestamp": item.get(
                                        "timestamp", datetime.utcnow().isoformat()
                                    ),
                                }
                                extracted.append(feed_item)

        return extracted

    # =========================================================================
    # 3. DATA REFRESHER AGENT
    # =========================================================================

    def data_refresher_agent(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Updates risk dashboard snapshot based on final_ranked_feed.

        This implements the "Operational Risk Radar" from your report:
        - logistics_friction: Route risk from mobility data
        - compliance_volatility: Regulatory risk from political data
        - market_instability: Volatility from economic data
        - opportunity_index: NEW - Growth signals from positive events

        Input: final_ranked_feed
        Output: risk_dashboard_snapshot
        """
        logger.info("[DataRefresherAgent] ===== REFRESHING DASHBOARD =====")

        # Get feed from state - handle both dict and object access
        if isinstance(state, dict):
            feed = state.get("final_ranked_feed", [])
        else:
            feed = getattr(state, "final_ranked_feed", [])

        # Default snapshot structure
        snapshot = {
            "logistics_friction": 0.0,
            "compliance_volatility": 0.0,
            "market_instability": 0.0,
            "opportunity_index": 0.0,
            "avg_confidence": 0.0,
            "high_priority_count": 0,
            "total_events": 0,
            "trending_topics": [],
            "spike_alerts": [],
            "infrastructure_health": 1.0,
            "regulatory_activity": 0.0,
            "investment_climate": 0.5,
            "last_updated": datetime.utcnow().isoformat(),
        }

        if not feed:
            # "No NEW events" is not "no risk". Keep the last snapshot.
            #
            # A cycle whose events were all suppressed by dedup -- which is the
            # NORMAL outcome when the sources have not published anything since
            # the last run -- used to return zeros here, and those zeros
            # overwrote a perfectly good snapshot. Observed: the dashboard went
            # from compliance 0.53 / market 0.52 / 2 high-priority to all
            # zeros, on a cycle that reported "0 unique, 11 exact dups".
            #
            # A reader cannot tell that apart from "the country is calm", which
            # is the opposite of what an intelligence dashboard is for -- and
            # it is the same failure shape as everything else this system has
            # had: reporting zero when the truth is "no change".
            #
            # The previous snapshot is carried forward with the timestamp it
            # was actually computed at, so "nothing changed" is visible as an
            # ageing last_updated rather than hidden behind a fresh one.
            previous = {}
            try:
                from src.runtime import shared_state

                previous = shared_state.get("risk_dashboard_snapshot") or {}
            except Exception:  # noqa: BLE001
                previous = {}

            if previous.get("total_events"):
                logger.info(
                    "[DataRefresherAgent] No new events this cycle; keeping the "
                    "previous snapshot (last computed %s)",
                    previous.get("last_updated"),
                )
                carried = dict(previous)
                carried["stale"] = True
                return {"risk_dashboard_snapshot": carried}

            # Nothing has ever been computed, so zeros are the honest answer.
            logger.info("[DataRefresherAgent] Empty feed and no previous "
                        "snapshot - reporting zero metrics")
            return {"risk_dashboard_snapshot": snapshot}

        # Compute aggregate metrics - feed uses 'confidence' field, not 'confidence_score'
        confidences = [
            float(item.get("confidence", item.get("confidence_score", 0.5)))
            for item in feed
        ]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        # High priority is a severity question with a confidence qualifier, not
        # a float comparison.
        #
        # This counted `confidence >= 0.7` alone. Severity "high" maps to a base
        # of exactly 0.7 (severity_base_map), so the base and the threshold were
        # the same number -- and confidence only moves DOWN from base for a
        # typical event, because the fake-news penalty applies to almost
        # everything while the corroboration boost applies to little. A "high"
        # event carrying a fake_news_score of 0.05 landed at 0.69 and was not
        # counted. In practice only "critical" could ever qualify.
        #
        # That is the same arithmetic-ceiling failure as the original
        # risk_score bug, one decimal place further in: a tile named "High
        # Priority Events" that a high-severity event could not enter. An event
        # the agents called high or critical IS high priority; confidence is a
        # separate axis and still promotes a heavily corroborated medium.
        high_priority_count = sum(
            1 for item, c in zip(feed, confidences)
            if str(item.get("severity", "")).lower() in ("high", "critical") or c >= 0.7
        )

        # Domain-specific scoring buckets
        domain_risks = {}
        opportunity_scores = []

        # The events behind each domain's score, so an index can be opened up.
        # `compliance_volatility: 0.7` tells a reader nothing on its own, and
        # the contributing events are already in hand here -- they were simply
        # discarded once their score had been averaged in.
        domain_drivers: Dict[str, List[Dict[str, Any]]] = {}

        for item in feed:
            # Feed uses 'domain' field, not 'target_agent'
            domain = item.get("domain", item.get("target_agent", "unknown"))
            score = item.get("confidence", item.get("confidence_score", 0.5))
            impact = item.get("impact_type", "risk")

            # Separate Opportunities from Risks
            if impact == "opportunity":
                opportunity_scores.append(score)
            else:
                # Group Risks by Domain
                if domain not in domain_risks:
                    domain_risks[domain] = []
                domain_risks[domain].append(score)

                domain_drivers.setdefault(domain, []).append({
                    "event_id": item.get("event_id"),
                    "summary": str(item.get("summary", ""))[:160],
                    "severity": item.get("severity"),
                    "contribution": round(float(score), 3),
                })

        # Helper for calculating averages safely
        def safe_avg(lst):
            return sum(lst) / len(lst) if lst else 0.0

        # Domain-specific risk scores.
        #
        # These buckets used to read domain_risks.get("mobility") and
        # .get("market") -- strings no agent has ever emitted. The five real
        # domains are social, political, economical, meteorological and
        # intelligence, so those lookups always returned []. Worse,
        # "meteorological" was mapped to nothing at all, meaning weather never
        # influenced the risk radar despite being one of the five agents and the
        # one most likely to disrupt logistics.

        # Social unrest and weather both impede movement of goods.
        snapshot["logistics_friction"] = round(safe_avg(
            domain_risks.get("social", []) + domain_risks.get("meteorological", [])
        ), 3)

        # Political and regulatory activity drives compliance risk.
        political_scores = domain_risks.get("political", [])
        snapshot["compliance_volatility"] = round(safe_avg(political_scores), 3)

        # Economic signals, plus competitor/market intelligence.
        snapshot["market_instability"] = round(safe_avg(
            domain_risks.get("economical", []) + domain_risks.get("intelligence", [])
        ), 3)

        # NEW: Opportunity Index
        # Higher score means stronger positive signals
        snapshot["opportunity_index"] = round(safe_avg(opportunity_scores), 3)

        # What moved each index. An index without its drivers is a number with
        # authority and no accountability -- the reader cannot check it, argue
        # with it, or act on the specific thing behind it. The mapping mirrors
        # the buckets above exactly, so a bucket change that forgets its
        # drivers shows up as an empty list rather than a stale one.
        def top_drivers(*domains, limit=4):
            rows = [d for name in domains for d in domain_drivers.get(name, [])]
            rows.sort(key=lambda d: d["contribution"], reverse=True)
            return rows[:limit]

        snapshot["drivers"] = {
            "logistics_friction": top_drivers("social", "meteorological"),
            "compliance_volatility": top_drivers("political"),
            "market_instability": top_drivers("economical", "intelligence"),
        }

        snapshot["avg_confidence"] = round(avg_confidence, 3)
        snapshot["high_priority_count"] = high_priority_count
        snapshot["total_events"] = len(feed)

        # NEW: Enhanced Operational Indicators
        # Infrastructure Health (inverted logistics friction)
        snapshot["infrastructure_health"] = round(
            max(0, 1.0 - snapshot["logistics_friction"]), 3
        )

        # Regulatory activity is a COUNT of political stories this cycle, not a
        # calibrated index. `len(political_scores) * 0.1` is a story tally with
        # a scaling factor, and it sat on the dashboard beside genuinely scored
        # metrics like compliance_volatility looking identical to them -- a
        # reader had no way to know one was a model output and the other was
        # "we saw seven political headlines".
        #
        # Kept because a rising count is real signal, but reported as what it
        # is. The raw count travels alongside so the UI can say "7 stories"
        # rather than implying a 0.7 index.
        snapshot["regulatory_activity"] = round(min(1.0, len(political_scores) * 0.1), 3)
        snapshot["regulatory_activity_is_count"] = True
        snapshot["regulatory_story_count"] = len(political_scores)

        # Investment Climate (opportunity-weighted)
        if opportunity_scores:
            snapshot["investment_climate"] = round(
                0.5 + safe_avg(opportunity_scores) * 0.5, 3
            )

        # NEW: Record topics for trending analysis and get current trends
        if TRENDING_ENABLED:
            try:
                detector = get_trending_detector()

                # Record topics from feed
                for item in feed:
                    domain = item.get("domain", item.get("target_agent", "unknown"))
                    for topic in topics_from_event(item):
                        record_topic_mention(
                            topic, source="roger_feed", domain=domain
                        )

                # Get trending topics and spike alerts
                snapshot["trending_topics"] = detector.get_trending_topics(limit=5)
                snapshot["spike_alerts"] = detector.get_spike_alerts(limit=3)

                logger.info(
                    f"[DataRefresherAgent] Trending: {len(snapshot['trending_topics'])} topics, {len(snapshot['spike_alerts'])} spikes"
                )
            except Exception as e:
                logger.warning(f"[DataRefresherAgent] Trending detection failed: {e}")

        snapshot["last_updated"] = datetime.utcnow().isoformat()

        logger.info("[DataRefresherAgent] Dashboard Metrics:")
        logger.info(f"  Logistics Friction: {snapshot['logistics_friction']}")
        logger.info(f"  Compliance Volatility: {snapshot['compliance_volatility']}")
        logger.info(f"  Market Instability: {snapshot['market_instability']}")
        logger.info(f"  Opportunity Index: {snapshot['opportunity_index']}")
        logger.info(
            f"  High Priority Events: {snapshot['high_priority_count']}/{snapshot['total_events']}"
        )

        # PRODUCTION FEATURE: Export to CSV for archival
        try:
            if feed:
                self.storage.export_feed_to_csv(feed)
                logger.info(f"[DataRefresherAgent] Exported {len(feed)} events to CSV")
        except Exception as e:
            logger.error(f"[DataRefresherAgent] CSV export error: {e}")

        # Cleanup old cache entries periodically
        try:
            self.storage.cleanup_old_data()
        except Exception as e:
            logger.error(f"[DataRefresherAgent] Cleanup error: {e}")

        # Mirror the assessment onto the board, then age and evict.
        #
        # Placed here rather than in its own node because it needs no new
        # topology: this node already runs once per cycle, last, after
        # everything that writes. Adding a graph node would change the shape of
        # the graph to express "and then tidy up", which is not a stage of the
        # pipeline.
        _shadow_write_assessment(snapshot)
        _write_foci(snapshot)
        _run_shadow_controller()
        _run_decay_pass()

        return {"risk_dashboard_snapshot": snapshot}

    # =========================================================================
    # 4. DATA REFRESH ROUTER
    # =========================================================================


"""
Scraped text, made readable.

Every domain agent built its summary as `f"{prefix}: {post_text[:200]}"`, which
put four things on the dashboard:

  - text cut mid-word with no ellipsis, so a shortened summary was
    indistinguishable from a broken scrape
  - run-on sentences, because LinkedIn and Facebook keep newlines and HTML
    collapses them to spaces
  - RT prefixes, @handle pile-ups, trailing hashtag clusters, stray URLs
  - doubled and non-breaking whitespace from platform markup

These were worst on events the LLM filter could not judge -- which is exactly
when a reader most needs to read the raw text themselves.

The rule the tests enforce throughout: remove chrome, never content. A summary
that keeps a stray hashtag is a far smaller problem than one that has quietly
dropped a fact.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# --- truncation ------------------------------------------------------------

def test_truncation_lands_on_a_word_boundary():
    from src.intelligence.summaries import truncate

    text = "Roads flooded near Kadawatha and traffic is being diverted today"
    out = truncate(text, limit=30)

    assert out.endswith("…")
    assert not out[:-1].endswith(" ")
    # The cut must not sever a word.
    assert out[:-1] in text
    assert text.startswith(out[:-1])


def test_short_text_is_untouched():
    from src.intelligence.summaries import truncate

    assert truncate("Short enough", limit=200) == "Short enough"
    assert "…" not in truncate("Short enough", limit=200)


def test_a_single_enormous_token_still_gets_cut():
    """A URL-like blob with no spaces must not defeat the word-boundary rule."""
    from src.intelligence.summaries import truncate

    out = truncate("A" * 500, limit=50)
    assert len(out) <= 51
    assert out.endswith("…")


def test_trailing_punctuation_is_not_left_dangling():
    from src.intelligence.summaries import truncate

    out = truncate("Flooding reported in Gampaha, Kandy and Galle districts", limit=30)
    assert not out.endswith(",…")


# --- line breaks -----------------------------------------------------------

def test_line_breaks_become_sentence_breaks():
    """
    HTML collapses a newline to a space, so a multi-paragraph post rendered as
    one run-on sentence with no punctuation between the parts.
    """
    from src.intelligence.summaries import clean_post_text

    out = clean_post_text("Port congestion update\nTerminal 2 is closed\nContact ops")

    assert out == "Port congestion update. Terminal 2 is closed. Contact ops"


def test_existing_punctuation_is_not_doubled():
    from src.intelligence.summaries import clean_post_text

    out = clean_post_text("Terminal 2 is closed.\nContact ops for rerouting")

    assert ".." not in out
    assert out == "Terminal 2 is closed. Contact ops for rerouting"


def test_blank_lines_do_not_produce_empty_sentences():
    from src.intelligence.summaries import clean_post_text

    out = clean_post_text("First line\n\n\nSecond line")
    assert out == "First line. Second line"


# --- junk ------------------------------------------------------------------

def test_retweet_prefix_is_removed():
    from src.intelligence.summaries import clean_post_text

    assert clean_post_text("RT @newsfirst: Flooding in Kelani") == "Flooding in Kelani"
    assert clean_post_text("rt @user: Something") == "Something"


def test_rt_inside_a_sentence_is_kept():
    """'RT' is also a word. Only the prefix form is chrome."""
    from src.intelligence.summaries import clean_post_text

    out = clean_post_text("The RT sector reported growth")
    assert "RT sector" in out


def test_leading_handle_pileups_are_removed():
    from src.intelligence.summaries import clean_post_text

    out = clean_post_text("@user1 @user2 @user3 the tariff schedule changed")
    assert out == "the tariff schedule changed"


def test_a_handle_inside_the_text_survives():
    """Removing an inline mention would change the meaning of the sentence."""
    from src.intelligence.summaries import clean_post_text

    out = clean_post_text("The minister told @newsfirst the bill passes today")
    assert "@newsfirst" in out


def test_trailing_hashtag_clusters_are_removed():
    from src.intelligence.summaries import clean_post_text

    out = clean_post_text("Stay safe everyone #SriLanka #flood #weather")
    assert out == "Stay safe everyone"


def test_a_hashtag_used_as_a_word_survives():
    from src.intelligence.summaries import clean_post_text

    out = clean_post_text("The #flood warning covers three districts")
    assert "#flood" in out


@pytest.mark.parametrize(
    "junk",
    ["https://t.co/xYz123", "http://example.com/a/b", "www.example.com"],
)
def test_urls_are_removed(junk):
    from src.intelligence.summaries import clean_post_text

    out = clean_post_text(f"Read more: {junk} about the closure")
    assert junk not in out
    assert "about the closure" in out


def test_platform_chrome_is_removed():
    from src.intelligence.summaries import clean_post_text

    out = clean_post_text("Heavy rain expected Show more")
    assert "Show more" not in out
    assert "Heavy rain expected" in out


def test_invisible_characters_are_normalised():
    from src.intelligence.summaries import clean_post_text

    out = clean_post_text("Heavy rain​ expected")
    assert " " not in out
    assert "​" not in out
    assert out == "Heavy rain expected"


def test_doubled_spaces_collapse():
    from src.intelligence.summaries import clean_post_text

    assert clean_post_text("Heavy   rain    expected") == "Heavy rain expected"


# --- the whole thing -------------------------------------------------------

def test_a_realistic_post_end_to_end():
    from src.intelligence.summaries import build_summary

    raw = (
        "RT @newsfirst: Heavy rain warning issued   for Gampaha\n\n\n"
        "Roads flooded near Kadawatha and traffic is being diverted via the "
        "outer circular highway this morning. Read more: https://t.co/xYz123 "
        "#SriLanka #flood #weather"
    )
    out = build_summary("Gampaha", raw)

    assert out.startswith("Gampaha: Heavy rain warning issued for Gampaha.")
    assert "RT @newsfirst" not in out
    assert "t.co" not in out
    assert "#SriLanka" not in out
    assert "  " not in out
    assert len(out) <= 210  # prefix + 200 + ellipsis


def test_the_prefix_does_not_eat_the_content():
    """
    The limit applies to the post text, not the whole string, so a long label
    cannot silently shorten what the reader came for.
    """
    from src.intelligence.summaries import build_summary

    long_prefix = "Sri Lanka Economy (Manufacturing And Industrial Production)"
    out = build_summary(long_prefix, "A" * 300)

    body = out.split(": ", 1)[1]
    assert len(body) >= 190


def test_an_empty_post_yields_just_the_prefix():
    from src.intelligence.summaries import build_summary

    assert build_summary("Gampaha", "") == "Gampaha"
    assert build_summary("Gampaha", None) == "Gampaha"


def test_no_prefix_yields_just_the_text():
    from src.intelligence.summaries import build_summary

    assert build_summary("", "Heavy rain expected") == "Heavy rain expected"


def test_a_trailing_colon_on_the_prefix_is_not_doubled():
    from src.intelligence.summaries import build_summary

    assert build_summary("Gampaha:", "Rain") == "Gampaha: Rain"


def test_malformed_input_does_not_raise():
    """This runs per post inside the agent loop."""
    from src.intelligence.summaries import build_summary, clean_post_text

    assert clean_post_text(None) == ""
    assert clean_post_text(12345) == "12345"
    assert build_summary(None, None) == ""


# --- every agent uses it ---------------------------------------------------

@pytest.mark.parametrize(
    "node",
    ["socialAgentNode.py", "politicalAgentNode.py", "economicalAgentNode.py",
     "meteorologicalAgentNode.py", "intelligenceAgentNode.py"],
)
def test_no_agent_slices_post_text_into_a_summary(node):
    """
    REGRESSION. `f"{prefix}: {post_text[:200]}"` is the shape that produced all
    four display problems at once.
    """
    import re

    src = (PROJECT_ROOT / "src" / "nodes" / node).read_text(encoding="utf-8")
    code = "\n".join(
        line for line in src.splitlines() if not line.strip().startswith("#")
    )

    offenders = re.findall(r'"summary":\s*f?"[^"]*\[:\d+\]', code)
    assert not offenders, f"{node} still slices text into a summary: {offenders}"

    assert "build_summary" in code, f"{node} does not use the shared formatter"

/**
 * Clean an event summary for display.
 *
 * Summaries are written by an LLM, which emits Markdown whether or not anyone
 * asked: "**Executive Summary - Sri Lanka Weather** 1. **River Conditions:**"
 * rendered literally in the feed, asterisks and all, because the cards drop the
 * string straight into a heading.
 *
 * They also arrive truncated at the source, and the cut lands mid-character:
 * the last byte of a stored summary is U+FFFD, the replacement character, so
 * the card ended on a black diamond. Trimming that here is cosmetic -- the
 * text is genuinely incomplete and the backend is where that gets fixed -- but
 * a clean ellipsis reads as "there is more" rather than as a rendering fault.
 */

/** Markdown emphasis, headings, list markers and code fences. */
function stripMarkdown(text: string): string {
  return text
    // **bold** / __bold__ / *italic* / _italic_ -- keep the words, drop the marks.
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1$2")
    .replace(/`{1,3}([^`]*)`{1,3}/g, "$1")
    // Leading "### " headings and "- " / "1. " list markers at a line start.
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+\.\s+/gm, "")
    // [label](url) -> label
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1");
}

export function formatSummary(raw: string | null | undefined): string {
  if (!raw) return "";

  let text = stripMarkdown(String(raw));

  // U+202F (narrow no-break space) and friends come through the model and
  // render inconsistently across fonts; a normal space is what was meant.
  text = text.replace(/[   ]/g, " ");

  // Collapse the newlines a Markdown list left behind, so a card stays a card.
  text = text.replace(/\s*\n+\s*/g, " ").replace(/\s{2,}/g, " ").trim();

  // Strip a trailing replacement character, which is what a mid-encoding cut
  // leaves behind. Nothing else: this used to append "…" to anything ending in
  // a letter or digit, on the theory that such a summary must have been cut.
  // Plenty of complete summaries end in a word, so it stamped an ellipsis onto
  // them and every card looked truncated -- including the ones that were fine.
  // The backend emits a real U+2026 when it genuinely shortens something, so
  // there is nothing for the client to infer.
  text = text.replace(/[�\s]+$/g, "");

  return text;
}

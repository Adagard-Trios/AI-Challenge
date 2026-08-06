/**
 * frontend/app/lib/format.ts
 * Display formatting for scraped values.
 *
 * Three problems this exists to stop, all of them visible on the dashboard:
 *
 * 1. `new Date(x).toLocaleTimeString()` where x is missing. `new Date(undefined)`
 *    renders "Invalid Date" and `new Date(null)` renders 1 January 1970 — and
 *    feed timestamps genuinely can be null, because storage falls back to
 *    `metadata.timestamp ?? last_seen` and neither is guaranteed.
 * 2. Raw counts. "1204" is harder to read at a glance than "1.2K", and an
 *    engagement figure is scanned, not calculated with.
 * 3. Floats straight from a scraper. A river level of 1.7629999 or a
 *    confidence of 0.6899999 renders every digit it has.
 *
 * Everything here is defensive by default: given something unusable it returns
 * a short dash rather than throwing or printing "NaN". A dash reads as "no
 * value", which is true, where "Invalid Date" reads as a broken page.
 */

/** What to show when there is genuinely nothing to show. */
export const EMPTY = "—";

function parseDate(value?: string | number | null): Date | null {
    // Explicitly reject null/undefined/"" before constructing: new Date(null)
    // is the epoch, which would silently render as 1970 rather than "unknown".
    if (value === null || value === undefined || value === "") return null;

    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
}

/**
 * "2h ago", "just now", "3 Aug".
 *
 * Relative for anything inside a week, because a feed is scanned for recency;
 * absolute beyond that, because "9d ago" stops being meaningful.
 */
export function formatWhen(value?: string | number | null): string {
    const date = parseDate(value);
    if (!date) return EMPTY;

    const seconds = Math.floor((Date.now() - date.getTime()) / 1000);

    // Clock skew between the server and the browser can put a timestamp
    // slightly in the future; "in -3 seconds" helps nobody.
    if (seconds < 45) return "just now";
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;

    return date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** The full timestamp, for a title attribute next to a relative one. */
export function formatExact(value?: string | number | null): string {
    const date = parseDate(value);
    return date ? date.toLocaleString() : EMPTY;
}

/** Clock time only, for cards that show a single "updated" moment. */
export function formatTime(value?: string | number | null): string {
    const date = parseDate(value);
    return date ? date.toLocaleTimeString() : EMPTY;
}

/**
 * 1204 -> "1.2K". Engagement counts are read, not summed.
 */
export function formatCount(value?: number | null): string {
    if (value === null || value === undefined || Number.isNaN(value)) return EMPTY;

    const n = Math.abs(value);
    if (n < 1000) return `${Math.round(value)}`;
    if (n < 1_000_000) return `${trimZero(value / 1000)}K`;
    return `${trimZero(value / 1_000_000)}M`;
}

function trimZero(n: number): string {
    // 1.0K reads worse than 1K; 1.2K is worth the decimal.
    const fixed = n.toFixed(1);
    return fixed.endsWith(".0") ? fixed.slice(0, -2) : fixed;
}

/** A 0-1 score as a percentage. Guards NaN, which renders as "NaN%". */
export function formatPercent(value?: number | null, digits = 0): string {
    if (value === null || value === undefined || Number.isNaN(value)) return EMPTY;
    return `${(value * 100).toFixed(digits)}%`;
}

/** A measurement with a unit, at a sane number of decimals. */
export function formatMeasure(
    value?: number | null,
    unit = "",
    digits = 2,
): string {
    if (value === null || value === undefined || Number.isNaN(value)) return EMPTY;

    const fixed = Number(value).toFixed(digits);
    // Drop trailing zeros so 4.50 reads as 4.5 but 4.00 reads as 4.
    const trimmed = fixed.replace(/\.?0+$/, "");
    return unit ? `${trimmed}${unit}` : trimmed;
}

/** Sri Lankan rupees, as a price is normally written. */
export function formatLKR(value?: number | null): string {
    if (value === null || value === undefined || Number.isNaN(value)) return EMPTY;
    return `Rs. ${Number(value).toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    })}`;
}

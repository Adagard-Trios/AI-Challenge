/**
 * frontend/app/lib/severity.ts
 * One severity scale, matching the warning ladder people already read.
 *
 * WHY THIS EXISTS
 *
 * Severity was mapped independently in six places, to three different colour
 * systems: `IntelligenceFeed` and `DashboardOverview` used design tokens,
 * `WeatherPredictions` and `CurrencyPrediction` used raw `red-500`/`yellow-500`,
 * `IndexDrivers` and `StoryFeed` used a third set. The same "high" event was a
 * different colour depending on which panel you were looking at.
 *
 * THE BUG THAT MOTIVATED IT
 *
 *   medium: 'primary'
 *
 * `--primary` is green (142 45% 45%). So a MEDIUM-severity event -- a river at
 * minor flood level, a scheduled outage -- rendered green. On the warning ladder
 * that every meteorological agency uses, green does not mean "moderate". It
 * means *no warning in force*. The dashboard was painting a live advisory in the
 * one colour reserved for "nothing to worry about".
 *
 * THE LADDER
 *
 * Sri Lanka's DMC, the WMO, Meteoalarm and the Common Alerting Protocol all
 * converge on the same four-step scale, and the people this product is for --
 * district officers -- already read it fluently:
 *
 *   red     take action     extreme / critical
 *   amber   be prepared     severe / high
 *   yellow  be aware        moderate / medium
 *   blue    for information minor / low
 *
 * Green is deliberately absent from event severity. It is reserved for
 * all-clear states ("Normal power supply", an index measured genuinely low), so
 * that green on this dashboard always means the same thing.
 *
 * Colour is never the only channel: `rank` drives a border weight and the label
 * is always rendered, so severity survives greyscale and colour blindness.
 */

export type Severity = "critical" | "high" | "medium" | "low";

export interface SeverityStyle {
    /** Solid badge, for the severity chip itself. */
    badge: string;
    /** Tinted background + matching text, for softer contexts. */
    soft: string;
    /** Left rule on a list row. Thickness tracks rank, so it reads in greyscale. */
    border: string;
    /** Text/icon colour alone. */
    text: string;
    /** What the level means, in the ladder's own words. */
    label: string;
    /** 3 = act now, 0 = informational. */
    rank: number;
}

const STYLES: Record<Severity, SeverityStyle> = {
    critical: {
        badge: "bg-severity-critical text-severity-critical-foreground",
        soft: "bg-severity-critical/20 text-severity-critical",
        border: "border-l-4 border-l-severity-critical",
        text: "text-severity-critical",
        label: "Take action",
        rank: 3,
    },
    high: {
        badge: "bg-severity-high text-severity-high-foreground",
        soft: "bg-severity-high/20 text-severity-high",
        border: "border-l-4 border-l-severity-high",
        text: "text-severity-high",
        label: "Be prepared",
        rank: 2,
    },
    medium: {
        badge: "bg-severity-medium text-severity-medium-foreground",
        soft: "bg-severity-medium/20 text-severity-medium",
        border: "border-l-2 border-l-severity-medium",
        text: "text-severity-medium",
        label: "Be aware",
        rank: 1,
    },
    low: {
        badge: "bg-severity-low text-severity-low-foreground",
        soft: "bg-severity-low/20 text-severity-low",
        border: "border-l-2 border-l-severity-low",
        text: "text-severity-low",
        label: "For information",
        rank: 0,
    },
};

/** Anything we could not place on the ladder. Muted, never green. */
const UNKNOWN: SeverityStyle = {
    badge: "bg-muted text-muted-foreground",
    soft: "bg-muted/40 text-muted-foreground",
    border: "border-l-2 border-l-border",
    text: "text-muted-foreground",
    label: "Unrated",
    rank: -1,
};

/**
 * Styles for a severity value off the wire.
 *
 * Tolerant of case and of the synonyms the agents emit (`extreme`, `severe`,
 * `moderate`, `minor`) so a backend wording change cannot silently fall through
 * to a default colour.
 */
export function severityStyle(value?: string | null): SeverityStyle {
    if (!value) return UNKNOWN;

    const key = value.toLowerCase().trim();
    switch (key) {
        case "critical":
        case "extreme":
            return STYLES.critical;
        case "high":
        case "severe":
            return STYLES.high;
        case "medium":
        case "moderate":
            return STYLES.medium;
        case "low":
        case "minor":
            return STYLES.low;
        default:
            return UNKNOWN;
    }
}

/** Sort helper: most urgent first. */
export function severityRank(value?: string | null): number {
    return severityStyle(value).rank;
}

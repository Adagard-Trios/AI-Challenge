"use client";

import { Badge } from "../ui/badge";
import { Target } from "lucide-react";

/**
 * Why this event is near the top of your feed.
 *
 * The platform used to serve an identical feed to everyone. Now events are
 * ranked against what a business actually depends on — its districts, its port,
 * its suppliers, its sector — and this says which of those matched.
 *
 * The reason is the point, not the score. A number on its own ("relevance
 * 0.85") has authority and no accountability; "your Gampaha operations" can be
 * argued with, which is what makes the ranking trustworthy.
 *
 * Renders nothing when the event was not scored (no exposure profile) or did
 * not match. An absent badge means "not ranked for you", never "irrelevant".
 */

// Structural, matching RogerEvent["relevance"] in use-roger-data.ts. `matches`
// is the machine-readable form of matched_on -- carried for filtering and
// analytics, deliberately not typed narrowly here since this component renders
// only the human-readable reasons.
export interface RelevanceInfo {
    score: number;
    matched_on: string[];
    matches?: Array<Record<string, string | number>>;
}

interface RelevanceBadgeProps {
    relevance?: RelevanceInfo | null;
    /** Show every reason rather than the strongest one. */
    expanded?: boolean;
    className?: string;
}

// Mirrors RELEVANT_THRESHOLD in backend/src/intelligence/relevance.py.
const RELEVANT_THRESHOLD = 0.35;
const STRONG_THRESHOLD = 0.7;

const RelevanceBadge = ({
    relevance,
    expanded = false,
    className = "",
}: RelevanceBadgeProps) => {
    // Not scored, or scored and matched nothing — say nothing either way.
    if (!relevance || !relevance.matched_on?.length) return null;

    const { score, matched_on } = relevance;
    const strong = score >= STRONG_THRESHOLD;
    const relevant = score >= RELEVANT_THRESHOLD;

    if (!relevant) return null;

    const tone = strong
        ? "bg-primary/20 text-primary border border-primary/40"
        : "bg-muted text-muted-foreground border border-border";

    const shown = expanded ? matched_on : matched_on.slice(0, 1);
    const hidden = matched_on.length - shown.length;

    return (
        <Badge
            className={`${tone} text-xs flex items-center gap-1 ${className}`}
            title={
                matched_on.length > 1
                    ? `Matches ${matched_on.join("; ")}`
                    : `Matches ${matched_on[0]}`
            }
        >
            <Target className="w-2.5 h-2.5 shrink-0" />
            <span>
                {shown.join(" · ")}
                {hidden > 0 && ` +${hidden}`}
            </span>
        </Badge>
    );
};

export default RelevanceBadge;

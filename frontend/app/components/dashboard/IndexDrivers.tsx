"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, HelpCircle } from "lucide-react";
import { Badge } from "../ui/badge";
import { formatPercent } from "../../lib/format";
import { severityStyle } from "../../lib/severity";

/**
 * The events behind a risk index.
 *
 * `compliance_volatility: 0.7` is a number with authority and no
 * accountability. The reader cannot check it, argue with it, or act on the
 * specific thing behind it — and a risk score you cannot interrogate is one you
 * either over-trust or ignore, both of which are worse than no score.
 *
 * The aggregator already collects the contributing events while computing each
 * average (`snapshot.drivers` in combinedAgentNode.py); they were simply
 * discarded once the number was produced. This renders them.
 *
 * An empty driver list is shown as "no contributing events", not hidden. An
 * index sitting at 0.0 with nothing behind it means no events landed in that
 * bucket this cycle — which is a real and useful thing to know, and looks
 * identical to a broken pipeline if the UI stays silent.
 */

export interface Driver {
    event_id: string | null;
    summary: string;
    severity: string | null;
    contribution: number;
}

/* SEVERITY_TONE lived here and rendered `critical` and `high` in the SAME red,
   which made the two most urgent levels indistinguishable in the one view whose
   job is ranking. Replaced by the shared ladder. */

interface IndexDriversProps {
    /** Human label for the index, e.g. "Compliance volatility". */
    label: string;
    /** The index value itself, 0-1 — or null when nothing has scored it yet. */
    value: number | null;
    /** What the index measures, in one sentence. */
    explanation: string;
    drivers?: Driver[];
}

const IndexDrivers = ({ label, value, explanation, drivers }: IndexDriversProps) => {
    const [open, setOpen] = useState(false);
    const rows = drivers ?? [];

    return (
        <div className="mt-1.5">
            {/* min-h-[44px] on touch, and a focus ring.
                This was a 71x16px tap target with no focus style — the
                smallest interactive control on the page, and the one that
                delivers the "interrogate the score" idea the whole component
                exists for. */}
            <button
                onClick={() => setOpen(!open)}
                className="flex items-center gap-1 min-h-[44px] sm:min-h-0 sm:py-1 text-xs text-muted-foreground hover:text-foreground transition-colors rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                aria-expanded={open}
                title={`What moved ${label.toLowerCase()}`}
            >
                {open ? (
                    <ChevronDown className="w-3 h-3 shrink-0" />
                ) : (
                    <ChevronRight className="w-3 h-3 shrink-0" />
                )}
                {/* "Why —?" is nonsense, so an unscored index asks the question
                    it can actually answer: what this measures, and why there is
                    no number yet. */}
                {value === null ? "Why no data?" : `Why ${formatPercent(value)}?`}
            </button>

            {open && (
                <div className="mt-2 rounded-md border border-border bg-muted/20 p-2.5 space-y-2">
                    <div className="flex items-start gap-2 text-xs text-muted-foreground">
                        <HelpCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                        <span>{explanation}</span>
                    </div>

                    {value === null ? (
                        <p className="text-xs text-muted-foreground">
                            Not scored yet. No collection cycle has reported a value for
                            this index — that is different from a measured low, so no
                            number is shown.
                        </p>
                    ) : rows.length === 0 ? (
                        <p className="text-xs text-muted-foreground">
                            No contributing events this cycle — nothing landed in this
                            bucket, so the index is an average of nothing rather than a
                            measured low.
                        </p>
                    ) : (
                        <ul className="space-y-1.5">
                            {rows.map((driver, index) => (
                                <li
                                    key={driver.event_id ?? `${index}-${driver.summary.slice(0, 24)}`}
                                    className="flex items-start gap-2 text-xs"
                                >
                                    <Badge
                                        className={`${severityStyle(driver.severity).soft} text-xs shrink-0`}
                                        title={severityStyle(driver.severity).label}
                                    >
                                        {String(driver.severity ?? "n/a").toUpperCase()}
                                    </Badge>
                                    <span className="flex-1 text-muted-foreground leading-snug">
                                        {driver.summary}
                                    </span>
                                    <span
                                        className="font-mono text-muted-foreground shrink-0"
                                        title="This event's confidence, which is what it contributed to the average"
                                    >
                                        {driver.contribution.toFixed(2)}
                                    </span>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            )}
        </div>
    );
};

export default IndexDrivers;

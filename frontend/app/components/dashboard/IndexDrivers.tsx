"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, HelpCircle } from "lucide-react";
import { Badge } from "../ui/badge";
import { formatPercent } from "../../lib/format";

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

const SEVERITY_TONE: Record<string, string> = {
    critical: "bg-destructive/20 text-destructive",
    high: "bg-destructive/15 text-destructive",
    medium: "bg-warning/20 text-warning",
    low: "bg-muted text-muted-foreground",
};

interface IndexDriversProps {
    /** Human label for the index, e.g. "Compliance volatility". */
    label: string;
    /** The index value itself, 0-1. */
    value: number;
    /** What the index measures, in one sentence. */
    explanation: string;
    drivers?: Driver[];
}

const IndexDrivers = ({ label, value, explanation, drivers }: IndexDriversProps) => {
    const [open, setOpen] = useState(false);
    const rows = drivers ?? [];

    return (
        <div className="mt-1.5">
            <button
                onClick={() => setOpen(!open)}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                aria-expanded={open}
                title={`What moved ${label.toLowerCase()}`}
            >
                {open ? (
                    <ChevronDown className="w-3 h-3" />
                ) : (
                    <ChevronRight className="w-3 h-3" />
                )}
                Why {formatPercent(value)}?
            </button>

            {open && (
                <div className="mt-2 rounded-md border border-border bg-muted/20 p-2.5 space-y-2">
                    <div className="flex items-start gap-2 text-xs text-muted-foreground">
                        <HelpCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                        <span>{explanation}</span>
                    </div>

                    {rows.length === 0 ? (
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
                                        className={`${
                                            SEVERITY_TONE[
                                                String(driver.severity ?? "").toLowerCase()
                                            ] ?? SEVERITY_TONE.low
                                        } text-xs shrink-0`}
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

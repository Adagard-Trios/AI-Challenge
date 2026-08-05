"use client";

import { useState } from "react";
import { Info, ShieldCheck, ShieldAlert, Target, Database } from "lucide-react";
import type { RogerEvent } from "../../hooks/use-roger-data";

/**
 * Why this event is in your feed, and how much to trust it.
 *
 * Every field shown here already travels with the event — llm_filtered,
 * fake_news_score, confidence, region, relevance — because earlier work made
 * the pipeline carry its own provenance instead of dropping it. This just puts
 * it in front of the reader.
 *
 * That is the differentiator against a competitor shipping confident black-box
 * chat: the platform can say what it knows, how it knows it, and where it is
 * guessing. It costs almost nothing because the honesty work is already done.
 */

interface WhyThisEventProps {
    event: RogerEvent;
}

const WhyThisEvent = ({ event }: WhyThisEventProps) => {
    const [open, setOpen] = useState(false);

    const verified = event.llm_filtered === true;
    const fake = event.fake_news_score;
    const relevance = event.relevance;

    return (
        <div className="mt-2">
            <button
                onClick={() => setOpen(!open)}
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                aria-expanded={open}
            >
                <Info className="w-3 h-3" />
                {open ? "Hide details" : "Why am I seeing this?"}
            </button>

            {open && (
                <div className="mt-2 rounded-md border border-border bg-muted/20 p-2.5 space-y-1.5 text-xs">
                    <div className="flex items-start gap-2">
                        {verified ? (
                            <ShieldCheck className="w-3.5 h-3.5 mt-0.5 text-success shrink-0" />
                        ) : (
                            <ShieldAlert className="w-3.5 h-3.5 mt-0.5 text-warning shrink-0" />
                        )}
                        <span>
                            {verified
                                ? "Checked by the language model: severity and credibility below are its assessment."
                                : "Not checked by the language model — the call failed or returned nothing for this event. Severity is the collecting agent's own keyword judgement. Treat it as provisional."}
                        </span>
                    </div>

                    <div className="flex items-start gap-2">
                        <Database className="w-3.5 h-3.5 mt-0.5 text-muted-foreground shrink-0" />
                        <span>
                            Confidence {Math.round((event.confidence ?? 0) * 100)}%
                            {" · "}
                            {/* null is not zero. An unjudged event has no score,
                                which is different from a clean one. */}
                            {fake === null || fake === undefined
                                ? "credibility not assessed"
                                : `credibility risk ${Math.round(fake * 100)}%`}
                            {event.region ? ` · ${event.region.replace("_", " ")}` : ""}
                        </span>
                    </div>

                    {relevance && relevance.matched_on?.length > 0 && (
                        <div className="flex items-start gap-2">
                            <Target className="w-3.5 h-3.5 mt-0.5 text-primary shrink-0" />
                            <span>
                                Ranked for you because it touches{" "}
                                {relevance.matched_on.join(", ")}.
                            </span>
                        </div>
                    )}

                    {relevance === null && (
                        <div className="flex items-start gap-2">
                            <Target className="w-3.5 h-3.5 mt-0.5 text-muted-foreground shrink-0" />
                            <span className="text-muted-foreground">
                                Not ranked for you — set an exposure profile in
                                Settings to sort your feed by what your business
                                depends on.
                            </span>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

export default WhyThisEvent;

"use client";

import { Card } from "../ui/card";
import { Badge } from "../ui/badge";
import { FileText, Gauge, Scale, TrendingDown, TrendingUp } from "lucide-react";
import { useRogerData } from "../../hooks/use-roger-data";
import IndexDrivers from "./IndexDrivers";
import { formatPercent } from "../../lib/format";

/**
 * The four risk indices — and, for the first time, what moved them.
 *
 * These numbers have been computed on every cycle since the aggregator was
 * written and rendered nowhere: `logistics_friction`, `compliance_volatility`
 * and `market_instability` existed only in the TypeScript type. The dashboard
 * showed event *counts* instead, which is a different and much weaker claim —
 * "14 risk events" says nothing about whether the country is getting harder to
 * operate in.
 *
 * Each index expands to the events behind it. That pairing is the point: a risk
 * score a reader cannot interrogate gets either over-trusted or ignored, and
 * the contributing events were already being computed and thrown away.
 */

/**
 * Tone for a score, including the case where there ISN'T one.
 *
 * `null` gets muted grey and the word "NO DATA" -- never green, never "LOW".
 * Previously the value was coerced with `?? 0`, so an unreachable backend
 * painted three green bars reading "0% LOW" next to a "Normal power supply"
 * card. On a flood-and-outage warning system, absence rendered as reassurance
 * is the single worst thing the UI can do.
 */
const TONE = (value: number | null) =>
    value === null
        ? { bar: "bg-muted-foreground/30", text: "text-muted-foreground", label: "NO DATA" }
        : value >= 0.7
          ? { bar: "bg-destructive", text: "text-destructive", label: "HIGH" }
          : value >= 0.4
            ? { bar: "bg-warning", text: "text-warning", label: "ELEVATED" }
            : { bar: "bg-success", text: "text-success", label: "LOW" };

/** 0-1 score to a percentage bar width; an unscored index has no bar. */
const barWidth = (value: number | null) =>
    value === null ? 0 : Math.max(0, Math.min(1, value)) * 100;

const RiskIndices = () => {
    const { dashboard } = useRogerData();
    const drivers = dashboard?.drivers;

    const indices = [
        {
            key: "logistics_friction" as const,
            label: "Logistics friction",
            value: dashboard?.logistics_friction ?? null,
            Icon: TrendingDown,
            explanation:
                "How much harder it is to move goods right now. Averages the confidence of social-unrest and weather events, the two things that most often close a road or a port.",
            rows: drivers?.logistics_friction,
        },
        {
            key: "compliance_volatility" as const,
            label: "Compliance volatility",
            value: dashboard?.compliance_volatility ?? null,
            Icon: Scale,
            explanation:
                "How fast the regulatory picture is changing. Averages political and gazette activity — a high value means rules are moving, not that any single rule is bad.",
            rows: drivers?.compliance_volatility,
        },
        {
            key: "market_instability" as const,
            label: "Market instability",
            value: dashboard?.market_instability ?? null,
            Icon: Gauge,
            explanation:
                "Turbulence in economic and competitor signals. Averages economic indicators and market intelligence events.",
            rows: drivers?.market_instability,
        },
    ];

    const opportunity = dashboard?.opportunity_index ?? null;

    return (
        <Card className="p-4 sm:p-5 bg-card border-border">
            <div className="flex items-start justify-between gap-3 mb-4">
                <div>
                    <h3 className="font-bold text-foreground">RISK INDICES</h3>
                    <p className="text-sm text-muted-foreground mt-0.5">
                        Derived from this cycle&apos;s events. Open any index to see the
                        events that moved it.
                    </p>
                </div>
                <Badge
                    className="bg-muted text-muted-foreground text-xs shrink-0"
                    title="Mean confidence across every event in this cycle"
                >
                    {/* formatPercent(null) renders "—", which is the truth
                        before a cycle completes. It used to be `?? 0`, i.e.
                        "confidence 0%" -- a measured-sounding claim. */}
                    confidence {formatPercent(dashboard?.avg_confidence)}
                </Badge>
            </div>

            <div className="space-y-4">
                {indices.map(({ key, label, value, Icon, explanation, rows }) => {
                    const tone = TONE(value);
                    return (
                        <div key={key}>
                            <div className="flex items-center justify-between gap-3 mb-1">
                                <span className="flex items-center gap-2 text-sm text-foreground">
                                    <Icon className={`w-4 h-4 ${tone.text}`} />
                                    {label}
                                </span>
                                <span className={`font-mono text-sm font-semibold ${tone.text}`}>
                                    {formatPercent(value)}
                                    <span className="ml-2 text-xs font-normal opacity-70">
                                        {tone.label}
                                    </span>
                                </span>
                            </div>

                            {/* An unscored index gets an empty track, not a
                                zero-width green bar. */}
                            <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                                <div
                                    className={`h-full ${tone.bar} transition-all duration-500`}
                                    style={{ width: `${barWidth(value)}%` }}
                                />
                            </div>

                            <IndexDrivers
                                label={label}
                                value={value}
                                explanation={explanation}
                                drivers={rows}
                            />
                        </div>
                    );
                })}

                {/* Regulatory activity is a COUNT, not a score.
                    `len(political_scores) * 0.1` is a story tally with a scaling
                    factor, and rendering it as a percentage next to genuinely
                    scored indices made a reader unable to tell a model output
                    from "we saw seven political headlines". The backend flags
                    it; this shows the count it actually is. */}
                {dashboard?.regulatory_activity_is_count && (
                    <div className="pt-3 border-t border-border">
                        <div className="flex items-center justify-between gap-3">
                            <span className="flex items-center gap-2 text-sm text-foreground">
                                <FileText className="w-4 h-4 text-muted-foreground" />
                                Regulatory activity
                            </span>
                            <span className="font-mono text-sm font-semibold text-foreground">
                                {dashboard.regulatory_story_count ?? 0}
                                <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                                    {(dashboard.regulatory_story_count ?? 0) === 1
                                        ? "story"
                                        : "stories"}
                                </span>
                            </span>
                        </div>
                        <p className="mt-1.5 text-xs text-muted-foreground">
                            A count of political and regulatory stories this cycle —
                            not a calibrated index. A rising count is real signal;
                            it just is not a score, so it is not shown as one.
                        </p>
                    </div>
                )}

                {/* Opportunity is the one index where higher is better, so it is
                    kept visually apart rather than sharing the risk colouring. */}
                <div className="pt-3 border-t border-border">
                    <div className="flex items-center justify-between gap-3 mb-1">
                        <span className="flex items-center gap-2 text-sm text-foreground">
                            <TrendingUp className="w-4 h-4 text-success" />
                            Opportunity index
                        </span>
                        <span
                            className={`font-mono text-sm font-semibold ${opportunity === null ? "text-muted-foreground" : "text-success"
                                }`}
                        >
                            {formatPercent(opportunity)}
                            {opportunity === null && (
                                <span className="ml-2 text-xs font-normal opacity-70">NO DATA</span>
                            )}
                        </span>
                    </div>
                    <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                        <div
                            className="h-full bg-success transition-all duration-500"
                            style={{ width: `${barWidth(opportunity)}%` }}
                        />
                    </div>
                    <p className="mt-1.5 text-xs text-muted-foreground">
                        Average confidence of events tagged as opportunities rather than
                        risks. Higher is better.
                    </p>
                </div>
            </div>
        </Card>
    );
};

export default RiskIndices;

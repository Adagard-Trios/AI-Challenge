"use client";

import { Card } from "../ui/card";
import { Badge } from "../ui/badge";
import { Gauge, Scale, TrendingDown, TrendingUp } from "lucide-react";
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

const TONE = (value: number) =>
    value >= 0.7
        ? { bar: "bg-destructive", text: "text-destructive", label: "HIGH" }
        : value >= 0.4
          ? { bar: "bg-warning", text: "text-warning", label: "ELEVATED" }
          : { bar: "bg-success", text: "text-success", label: "LOW" };

const RiskIndices = () => {
    const { dashboard } = useRogerData();
    const drivers = dashboard?.drivers;

    const indices = [
        {
            key: "logistics_friction" as const,
            label: "Logistics friction",
            value: dashboard?.logistics_friction ?? 0,
            Icon: TrendingDown,
            explanation:
                "How much harder it is to move goods right now. Averages the confidence of social-unrest and weather events, the two things that most often close a road or a port.",
            rows: drivers?.logistics_friction,
        },
        {
            key: "compliance_volatility" as const,
            label: "Compliance volatility",
            value: dashboard?.compliance_volatility ?? 0,
            Icon: Scale,
            explanation:
                "How fast the regulatory picture is changing. Averages political and gazette activity — a high value means rules are moving, not that any single rule is bad.",
            rows: drivers?.compliance_volatility,
        },
        {
            key: "market_instability" as const,
            label: "Market instability",
            value: dashboard?.market_instability ?? 0,
            Icon: Gauge,
            explanation:
                "Turbulence in economic and competitor signals. Averages economic indicators and market intelligence events.",
            rows: drivers?.market_instability,
        },
    ];

    const opportunity = dashboard?.opportunity_index ?? 0;

    return (
        <Card className="p-4 sm:p-5 bg-card border-border">
            <div className="flex items-start justify-between gap-3 mb-4">
                <div>
                    <h3 className="font-bold text-foreground">RISK INDICES</h3>
                    <p className="text-xs text-muted-foreground mt-0.5">
                        Derived from this cycle&apos;s events. Open any index to see the
                        events that moved it.
                    </p>
                </div>
                <Badge
                    className="bg-muted text-muted-foreground text-xs shrink-0"
                    title="Mean confidence across every event in this cycle"
                >
                    confidence {formatPercent(dashboard?.avg_confidence ?? 0)}
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

                            <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                                <div
                                    className={`h-full ${tone.bar} transition-all duration-500`}
                                    style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }}
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

                {/* Opportunity is the one index where higher is better, so it is
                    kept visually apart rather than sharing the risk colouring. */}
                <div className="pt-3 border-t border-border">
                    <div className="flex items-center justify-between gap-3 mb-1">
                        <span className="flex items-center gap-2 text-sm text-foreground">
                            <TrendingUp className="w-4 h-4 text-success" />
                            Opportunity index
                        </span>
                        <span className="font-mono text-sm font-semibold text-success">
                            {formatPercent(opportunity)}
                        </span>
                    </div>
                    <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                        <div
                            className="h-full bg-success transition-all duration-500"
                            style={{ width: `${Math.max(0, Math.min(1, opportunity)) * 100}%` }}
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

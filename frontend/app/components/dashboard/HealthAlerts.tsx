"use client";

import { Card } from "../ui/card";
import { Badge } from "../ui/badge";
import { Heart, AlertTriangle, Bug, Activity } from "lucide-react";
import DataProvenance from "./DataProvenance";
import { EMPTY } from "@/app/lib/format";

interface HealthAlert {
    type: string;
    text: string;
    severity: string;
}

interface HealthAlertsProps {
    healthData?: Record<string, unknown> | null;
}

const HealthAlerts = ({ healthData }: HealthAlertsProps) => {
    const alerts = (healthData?.alerts as HealthAlert[]) || [];
    const dengue = (healthData?.dengue as Record<string, unknown>) || {};
    const advisories = (healthData?.advisories as HealthAlert[]) || [];
    const fetchedAt = healthData?.fetched_at as string;

    const hasActiveAlerts = alerts.length > 0 || advisories.length > 0;

    // Same three-state rule as the power and water cards: no reading from the
    // Ministry is not a clean bill of health. "✓ NORMAL" on an empty response
    // is the claim this dashboard is least entitled to make.
    const known = healthData != null;
    const isNormal = known && !hasActiveAlerts;
    const weeklyCases = dengue.weekly_cases as number | undefined;

    return (
        <Card className="p-4 bg-card border-border">
            <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                    <div className={`p-2 rounded-lg ${hasActiveAlerts ? 'bg-warning/20' : isNormal ? 'bg-success/20' : 'bg-muted/30'}`}>
                        <Heart className={`w-5 h-5 ${hasActiveAlerts ? 'text-warning' : isNormal ? 'text-success' : 'text-muted-foreground'}`} />
                    </div>
                    <div>
                        <h3 className="font-bold text-sm">🏥 HEALTH STATUS</h3>
                        <p className="text-xs text-muted-foreground">Ministry of Health</p>
                    </div>
                </div>
                <div className="flex items-center gap-1">
                    <Badge
                        className={
                            hasActiveAlerts
                                ? "bg-warning/20 text-warning"
                                : isNormal
                                    ? "bg-success/20 text-success"
                                    : "bg-muted/20 text-muted-foreground"
                        }
                    >
                        {hasActiveAlerts ? "⚠ ADVISORIES" : isNormal ? "✓ NORMAL" : "○ NO DATA"}
                    </Badge>
                    <DataProvenance
                        status={healthData?.scrape_status as string}
                        showAsOf={false}
                    />
                </div>
            </div>

            {/* Dengue Section */}
            <div className="p-3 rounded-lg bg-muted/30 border border-border mb-2">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <Bug className="w-4 h-4 text-warning" />
                        <span className="text-sm font-medium">Dengue Cases</span>
                    </div>
                    <div className="text-right">
                        {/* `|| 0` printed a confident "0" for "we did not get a
                            number". Zero dengue cases nationally would be
                            extraordinary news; an em-dash is the truth. */}
                        <p className={`text-lg font-bold ${weeklyCases == null ? "text-muted-foreground" : ""}`}>
                            {weeklyCases ?? EMPTY}
                        </p>
                        <p className="text-xs text-muted-foreground">weekly avg</p>
                    </div>
                </div>
                {Array.isArray(dengue.high_risk_districts) && dengue.high_risk_districts.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                        {(dengue.high_risk_districts as string[]).slice(0, 3).map((district: string, idx: number) => (
                            <Badge key={idx} variant="outline" className="text-xs">
                                {String(district)}
                            </Badge>
                        ))}
                    </div>
                )}
            </div>

            {/* Active Alerts */}
            {alerts.length > 0 && (
                <div className="mb-2">
                    {alerts.slice(0, 2).map((alert, idx) => (
                        <div key={idx} className="p-2 rounded bg-destructive/10 border border-destructive/30 mb-1">
                            <div className="flex items-start gap-2">
                                <AlertTriangle className="w-3 h-3 text-destructive mt-0.5 flex-shrink-0" />
                                <p className="text-xs text-destructive">{alert.text}</p>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* Advisories */}
            {advisories.length > 0 && (
                <div className="mb-2">
                    {advisories.slice(0, 2).map((adv, idx) => (
                        <div key={idx} className="p-2 rounded bg-warning/10 border border-warning/30 mb-1">
                            <div className="flex items-start gap-2">
                                <Activity className="w-3 h-3 text-warning mt-0.5 flex-shrink-0" />
                                <p className="text-xs text-warning">{adv.text}</p>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            <p className="text-xs text-muted-foreground mt-2 text-center">
                Source: health.gov.lk (Ministry of Health)
            </p>
        </Card>
    );
};

export default HealthAlerts;

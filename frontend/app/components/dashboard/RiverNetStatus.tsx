"use client";

import { Card } from "../ui/card";
import { Badge } from "../ui/badge";
import { Waves, AlertTriangle, CheckCircle, TrendingUp, Clock } from "lucide-react";
import { motion } from "framer-motion";
import DataProvenance from "./DataProvenance";

// Mirrors what GET /api/rivernet actually returns (fetch_rivernet_levels in
// backend/src/utils/utils.py). The previous shape -- location_key, status,
// water_level.{value,unit} -- was never sent by the API, so `river.status`
// was undefined and `river.status.toUpperCase()` threw on the first station.
// That crash is why the flood panel never appeared.
interface RiverData {
    unit_id?: string;
    name: string;
    region: string;
    severity: "critical" | "warning" | "alert" | "normal" | "unknown";
    level_m: number | null;
    previous_level_m?: number | null;
    max_level_m?: number | null;
    trend?: "rising" | "falling" | "steady" | "unknown";
    alert_colour?: string | null;
    reading_time?: string | null;
    // A station that has stopped reporting is itself signal during a flood.
    reporting: boolean;
    coordinates?: unknown;
}

interface RiverNetData {
    rivers: RiverData[];
    // Note: `alerts` mixes real warning levels with stations that have stopped
    // reporting (severity "no_data"). Only the former is a flood signal, which
    // is why the header keys off summary.flood_alerts and not alerts.length.
    alerts: Array<{
        river: string;
        region: string;
        severity: string;
        level_m: number | null;
        max_level_m?: number | null;
        trend?: string;
        message: string;
    }>;
    summary: {
        total_stations: number;
        reporting: number;
        offline: number;
        rising: number;
        alerts: number;
        flood_alerts: number;
        status: string;
        regions?: string[];
    };
    fetched_at: string;
    source: string;
}

interface RiverNetStatusProps {
    riverData?: RiverNetData | null;
    compact?: boolean;
}

// Keys must cover both vocabularies the API uses: summary.status
// (alert/rising/normal/unknown/error) and a station's severity
// (critical/warning/alert/normal/unknown, plus no_data for a silent gauge).
const statusConfig = {
    critical: {
        color: "destructive",
        bgColor: "bg-destructive/20",
        borderColor: "border-destructive",
        textColor: "text-destructive",
        icon: AlertTriangle,
        emoji: "🔴",
        label: "CRITICAL"
    },
    alert: {
        color: "destructive",
        bgColor: "bg-destructive/15",
        borderColor: "border-destructive/70",
        textColor: "text-destructive",
        icon: AlertTriangle,
        emoji: "🟠",
        label: "ALERT"
    },
    no_data: {
        color: "muted",
        bgColor: "bg-muted/20",
        borderColor: "border-muted",
        textColor: "text-muted-foreground",
        icon: Clock,
        emoji: "⚫",
        label: "NO DATA"
    },
    warning: {
        color: "warning",
        bgColor: "bg-warning/20",
        borderColor: "border-warning",
        textColor: "text-warning",
        icon: AlertTriangle,
        emoji: "🟠",
        label: "WARNING"
    },
    rising: {
        color: "primary",
        bgColor: "bg-primary/20",
        borderColor: "border-primary",
        textColor: "text-primary",
        icon: TrendingUp,
        emoji: "🟡",
        label: "RISING"
    },
    normal: {
        color: "success",
        bgColor: "bg-success/20",
        borderColor: "border-success",
        textColor: "text-success",
        icon: CheckCircle,
        emoji: "🟢",
        label: "NORMAL"
    },
    unknown: {
        color: "muted",
        bgColor: "bg-muted/20",
        borderColor: "border-muted",
        textColor: "text-muted-foreground",
        icon: Clock,
        emoji: "⚪",
        label: "UNKNOWN"
    },
    error: {
        color: "destructive",
        bgColor: "bg-destructive/10",
        borderColor: "border-destructive/50",
        textColor: "text-destructive/70",
        icon: AlertTriangle,
        emoji: "❌",
        label: "ERROR"
    }
};

const RiverNetStatus = ({ riverData, compact = false }: RiverNetStatusProps) => {
    if (!riverData || !riverData.rivers || riverData.rivers.length === 0) {
        return (
            <Card className="p-6 bg-card border-border">
                <div className="flex items-center gap-3 mb-4">
                    <Waves className="w-6 h-6 text-info" />
                    <h3 className="font-bold">FLOOD MONITORING</h3>
                    <Badge className="ml-auto bg-muted">Offline</Badge>
                </div>
                <div className="text-center text-muted-foreground py-4">
                    <Waves className="w-10 h-10 mx-auto mb-2 opacity-50" />
                    <p className="text-sm">River monitoring data unavailable</p>
                    <p className="text-xs mt-1">Check rivernet.lk for live data</p>
                </div>
            </Card>
        );
    }

    const { rivers, summary, alerts, fetched_at } = riverData;
    const overallStatus = summary?.status || "normal";
    const statusInfo = statusConfig[overallStatus as keyof typeof statusConfig] || statusConfig.unknown;

    const floodAlerts = summary?.flood_alerts ?? 0;
    const offline = summary?.offline ?? 0;

    // The API sends no status_breakdown, so this grid was always empty.
    // Counted here from the stations themselves.
    const statusCounts = rivers.reduce<Record<string, number>>((acc, river) => {
        const key = river.reporting ? river.severity || "unknown" : "no_data";
        acc[key] = (acc[key] || 0) + 1;
        return acc;
    }, {});

    return (
        <Card className={`p-6 bg-card border-border ${floodAlerts > 0 ? 'border-warning/50' : ''}`}>
            {/* Header */}
            <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                    <div className={`p-2 rounded-lg ${statusInfo.bgColor}`}>
                        <Waves className={`w-6 h-6 ${statusInfo.textColor}`} />
                    </div>
                    <div>
                        <h3 className="font-bold flex items-center gap-2">
                            🌊 FLOOD MONITORING
                            {floodAlerts > 0 && (
                                <Badge className="bg-warning text-warning-foreground">
                                    {floodAlerts} ALERT{floodAlerts === 1 ? '' : 'S'}
                                </Badge>
                            )}
                        </h3>
                        <p className="text-xs text-muted-foreground">
                            RiverNet.lk • {summary?.reporting ?? rivers.length} of{" "}
                            {summary?.total_stations ?? rivers.length} stations reporting
                            {offline > 0 && ` • ${offline} offline`}
                        </p>
                    </div>
                </div>
                <div className="text-right">
                    <div className="flex items-center gap-1 justify-end">
                        <Badge className={`${statusInfo.bgColor} ${statusInfo.textColor}`}>
                            {statusInfo.emoji} {statusInfo.label}
                        </Badge>
                        <DataProvenance
                            status={(riverData as { scrape_status?: string })?.scrape_status}
                            showAsOf={false}
                        />
                    </div>
                    <p className="text-xs text-muted-foreground mt-1">
                        {new Date(fetched_at).toLocaleTimeString()}
                    </p>
                </div>
            </div>

            {/* Status Summary */}
            <div className="grid grid-cols-3 md:grid-cols-6 gap-2 mb-4">
                {Object.entries(statusCounts).map(([status, count]) => {
                    if (count === 0) return null;
                    const config = statusConfig[status as keyof typeof statusConfig] || statusConfig.unknown;
                    return (
                        <div key={status} className={`p-2 rounded text-center ${config.bgColor}`}>
                            <p className={`text-lg font-bold ${config.textColor}`}>{count}</p>
                            <p className="text-xs text-muted-foreground uppercase">{status}</p>
                        </div>
                    );
                })}
            </div>

            {/* Alerts Section.
                `alert.text` did not exist -- the field is `message` -- so this
                threw a TypeError whenever there was anything to show. */}
            {alerts && alerts.length > 0 && (
                <div className="mb-4 p-3 rounded-lg bg-warning/10 border border-warning/30">
                    <p className="text-sm font-semibold text-warning mb-2">
                        {floodAlerts > 0 ? "⚠️ Active Alerts" : "Stations Not Reporting"}
                    </p>
                    {alerts.slice(0, 3).map((alert, idx) => (
                        <p key={`${alert.river}-${idx}`} className="text-xs text-warning/80 mb-1">
                            • {alert.message}
                        </p>
                    ))}
                    {alerts.length > 3 && (
                        <p className="text-xs text-warning/60 mt-1">
                            +{alerts.length - 3} more
                        </p>
                    )}
                </div>
            )}

            {/* Rivers Grid */}
            <div className={`grid ${compact ? 'grid-cols-2' : 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3'} gap-3`}>
                {rivers.map((river, idx) => {
                    // A silent gauge is shown as such rather than inheriting
                    // whatever severity it last reported.
                    const key = river.reporting ? river.severity || "unknown" : "no_data";
                    const config = statusConfig[key as keyof typeof statusConfig] || statusConfig.unknown;
                    const RiverStatusIcon = config.icon;

                    return (
                        <motion.div
                            key={river.unit_id || `${river.name}-${idx}`}
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: idx * 0.05 }}
                        >
                            <Card className={`p-3 ${config.bgColor} border-l-4 ${config.borderColor} hover:shadow-md transition-all cursor-pointer`}>
                                <div className="flex items-start justify-between">
                                    <div className="flex-1">
                                        <div className="flex items-center gap-2 mb-1">
                                            <RiverStatusIcon className={`w-4 h-4 ${config.textColor}`} />
                                            <span className="font-semibold text-sm">{river.name}</span>
                                        </div>
                                        <p className="text-xs text-muted-foreground">{river.region}</p>
                                        {river.reporting && river.level_m !== null && (
                                            <p className={`text-xs font-mono ${config.textColor} mt-1`}>
                                                Level: {river.level_m}m
                                                {river.max_level_m ? ` / ${river.max_level_m}m` : ""}
                                                {river.trend && river.trend !== "unknown"
                                                    ? ` (${river.trend})`
                                                    : ""}
                                            </p>
                                        )}
                                    </div>
                                    <Badge className={`${config.bgColor} ${config.textColor} text-xs`}>
                                        {config.emoji} {config.label}
                                    </Badge>
                                </div>
                            </Card>
                        </motion.div>
                    );
                })}
            </div>

            {/* Footer Link */}
            <div className="mt-4 pt-3 border-t border-border flex items-center justify-between">
                <p className="text-xs text-muted-foreground">
                    Source: <a href="https://rivernet.lk" target="_blank" rel="noopener noreferrer"
                        className="text-primary hover:underline">rivernet.lk</a>
                </p>
                <p className="text-xs text-muted-foreground">
                    {rivers.length} rivers monitored
                </p>
            </div>
        </Card>
    );
};

export default RiverNetStatus;

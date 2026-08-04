"use client";

import { Card } from "../ui/card";
import { Badge } from "../ui/badge";
import { Waves, AlertTriangle, CheckCircle, TrendingUp, Clock } from "lucide-react";
import { motion } from "framer-motion";

interface RiverData {
    location_key: string;
    name: string;
    region: string;
    status: "danger" | "warning" | "rising" | "normal" | "unknown" | "error";
    water_level?: {
        value: number;
        unit: string;
    };
    url?: string;
    last_updated?: string;
}

interface RiverNetData {
    rivers: RiverData[];
    alerts: Array<{
        text: string;
        severity: string;
        source: string;
    }>;
    summary: {
        total_monitored: number;
        overall_status: string;
        has_alerts: boolean;
        status_breakdown?: Record<string, number>;
    };
    fetched_at: string;
    source: string;
}

interface RiverNetStatusProps {
    riverData?: RiverNetData | null;
    compact?: boolean;
}

const statusConfig = {
    danger: {
        color: "destructive",
        bgColor: "bg-destructive/20",
        borderColor: "border-destructive",
        textColor: "text-destructive",
        icon: AlertTriangle,
        emoji: "🔴",
        label: "DANGER"
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
    const overallStatus = summary?.overall_status || "normal";
    const statusInfo = statusConfig[overallStatus as keyof typeof statusConfig] || statusConfig.unknown;
    const StatusIcon = statusInfo.icon;

    // Count rivers by status
    const statusCounts = summary?.status_breakdown || {};

    return (
        <Card className={`p-6 bg-card border-border ${summary?.has_alerts ? 'border-warning/50' : ''}`}>
            {/* Header */}
            <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                    <div className={`p-2 rounded-lg ${statusInfo.bgColor}`}>
                        <Waves className={`w-6 h-6 ${statusInfo.textColor}`} />
                    </div>
                    <div>
                        <h3 className="font-bold flex items-center gap-2">
                            🌊 FLOOD MONITORING
                            {summary?.has_alerts && (
                                <Badge className="bg-warning text-warning-foreground">ALERTS</Badge>
                            )}
                        </h3>
                        <p className="text-xs text-muted-foreground">
                            RiverNet.lk • {rivers.length} rivers monitored
                        </p>
                    </div>
                </div>
                <div className="text-right">
                    <Badge className={`${statusInfo.bgColor} ${statusInfo.textColor}`}>
                        {statusInfo.emoji} {statusInfo.label}
                    </Badge>
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

            {/* Alerts Section */}
            {alerts && alerts.length > 0 && (
                <div className="mb-4 p-3 rounded-lg bg-warning/10 border border-warning/30">
                    <p className="text-sm font-semibold text-warning mb-2">⚠️ Active Alerts</p>
                    {alerts.slice(0, 2).map((alert, idx) => (
                        <p key={idx} className="text-xs text-warning/80 mb-1">
                            • {alert.text.slice(0, 100)}...
                        </p>
                    ))}
                </div>
            )}

            {/* Rivers Grid */}
            <div className={`grid ${compact ? 'grid-cols-2' : 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3'} gap-3`}>
                {rivers.map((river, idx) => {
                    const config = statusConfig[river.status] || statusConfig.normal;
                    const RiverStatusIcon = config.icon;

                    return (
                        <motion.div
                            key={river.location_key}
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
                                        {river.water_level && (
                                            <p className={`text-xs font-mono ${config.textColor} mt-1`}>
                                                Level: {river.water_level.value}{river.water_level.unit}
                                            </p>
                                        )}
                                    </div>
                                    <Badge className={`${config.bgColor} ${config.textColor} text-xs`}>
                                        {config.emoji} {river.status.toUpperCase()}
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

"use client";

import { Card } from "../ui/card";
import { Badge } from "../ui/badge";
import { Zap, AlertTriangle, CheckCircle } from "lucide-react";

interface PowerStatusProps {
    powerData?: Record<string, unknown> | null;
}

const PowerOutageStatus = ({ powerData }: PowerStatusProps) => {
    const isActive = powerData?.load_shedding_active as boolean;
    const status = (powerData?.status as string) || "unknown";
    const announcements = (powerData?.announcements as string[]) || [];
    const fetchedAt = powerData?.fetched_at as string;

    const getStatusColor = () => {
        if (status === "load_shedding") return "bg-destructive/20 text-destructive";
        if (status === "operational" || status === "no_load_shedding") return "bg-success/20 text-success";
        return "bg-muted/20 text-muted-foreground";
    };

    const getStatusLabel = () => {
        if (status === "load_shedding") return "⚡ LOAD SHEDDING";
        if (status === "operational" || status === "no_load_shedding") return "✓ NORMAL";
        return "○ CHECKING...";
    };

    return (
        <Card className="p-4 bg-card border-border">
            <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                    <div className={`p-2 rounded-lg ${isActive ? 'bg-destructive/20' : 'bg-success/20'}`}>
                        <Zap className={`w-5 h-5 ${isActive ? 'text-destructive' : 'text-success'}`} />
                    </div>
                    <div>
                        <h3 className="font-bold text-sm">⚡ POWER STATUS</h3>
                        <p className="text-xs text-muted-foreground">CEB Sri Lanka</p>
                    </div>
                </div>
                <Badge className={getStatusColor()}>
                    {getStatusLabel()}
                </Badge>
            </div>

            {isActive ? (
                <div className="p-3 rounded-lg bg-destructive/10 border border-destructive/30 mb-2">
                    <div className="flex items-center gap-2 mb-1">
                        <AlertTriangle className="w-4 h-4 text-destructive" />
                        <span className="text-sm font-semibold text-destructive">Load Shedding Active</span>
                    </div>
                    <p className="text-xs text-destructive/80">Power cuts may be in effect in various areas</p>
                </div>
            ) : (
                <div className="p-3 rounded-lg bg-success/10 border border-success/30 mb-2">
                    <div className="flex items-center gap-2">
                        <CheckCircle className="w-4 h-4 text-success" />
                        <span className="text-sm text-success">Normal power supply across the island</span>
                    </div>
                </div>
            )}

            {announcements.length > 0 && (
                <div className="mt-2">
                    {announcements.slice(0, 2).map((ann, idx) => (
                        <p key={idx} className="text-xs text-muted-foreground mb-1">• {ann}</p>
                    ))}
                </div>
            )}

            {fetchedAt && (
                <p className="text-xs text-muted-foreground mt-2">
                    Updated: {new Date(fetchedAt).toLocaleTimeString()}
                </p>
            )}
        </Card>
    );
};

export default PowerOutageStatus;

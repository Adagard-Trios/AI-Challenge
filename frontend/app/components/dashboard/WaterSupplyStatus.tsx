"use client";

import { Card } from "../ui/card";
import { Badge } from "../ui/badge";
import { Droplets, AlertTriangle, CheckCircle } from "lucide-react";

interface WaterDisruption {
    area: string;
    type: string;
    details: string;
    severity: string;
}

interface WaterSupplyStatusProps {
    waterData?: Record<string, unknown> | null;
}

const WaterSupplyStatus = ({ waterData }: WaterSupplyStatusProps) => {
    const status = (waterData?.status as string) || "unknown";
    const disruptions = (waterData?.active_disruptions as WaterDisruption[]) || [];
    const overallSupply = waterData?.overall_supply as string;
    const fetchedAt = waterData?.fetched_at as string;

    const hasDisruptions = status === "disruptions_reported" || disruptions.length > 0;

    return (
        <Card className="p-4 bg-card border-border">
            <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                    <div className={`p-2 rounded-lg ${hasDisruptions ? 'bg-warning/20' : 'bg-info/20'}`}>
                        <Droplets className={`w-5 h-5 ${hasDisruptions ? 'text-warning' : 'text-info'}`} />
                    </div>
                    <div>
                        <h3 className="font-bold text-sm">💧 WATER SUPPLY</h3>
                        <p className="text-xs text-muted-foreground">NWSDB Status</p>
                    </div>
                </div>
                <Badge className={hasDisruptions ? "bg-warning/20 text-warning" : "bg-success/20 text-success"}>
                    {hasDisruptions ? "⚠ DISRUPTIONS" : "✓ NORMAL"}
                </Badge>
            </div>

            {hasDisruptions ? (
                <div className="space-y-2">
                    {disruptions.slice(0, 3).map((d, idx) => (
                        <div key={idx} className="p-2 rounded bg-warning/10 border border-warning/30">
                            <div className="flex items-start gap-2">
                                <AlertTriangle className="w-3 h-3 text-warning mt-0.5 flex-shrink-0" />
                                <div className="flex-1">
                                    <p className="text-sm font-medium text-warning">{d.area}</p>
                                    <p className="text-xs text-warning/80">{d.type} - {d.details?.slice(0, 80)}...</p>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            ) : (
                <div className="p-3 rounded-lg bg-success/10 border border-success/30">
                    <div className="flex items-center gap-2">
                        <CheckCircle className="w-4 h-4 text-success" />
                        <span className="text-sm text-success">
                            {overallSupply || "Normal water supply across most areas"}
                        </span>
                    </div>
                </div>
            )}

            <p className="text-xs text-muted-foreground mt-3 text-center">
                Source: waterboard.lk (NWSDB)
            </p>
        </Card>
    );
};

export default WaterSupplyStatus;

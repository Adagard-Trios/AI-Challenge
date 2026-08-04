"use client";

import { Card } from "../ui/card";
import { Badge } from "../ui/badge";
import { Fuel, TrendingUp, TrendingDown, Minus } from "lucide-react";

interface FuelPrice {
    price: number;
    unit: string;
    name: string;
}

interface FuelMonitorProps {
    fuelData?: Record<string, unknown> | null;
}

const FuelPriceMonitor = ({ fuelData }: FuelMonitorProps) => {
    const prices = (fuelData?.prices as Record<string, FuelPrice>) || {};
    const lastRevision = fuelData?.last_revision as string;
    const fetchedAt = fuelData?.fetched_at as string;

    const fuelTypes = [
        { key: "petrol_92", label: "Petrol 92", icon: "⛽" },
        { key: "petrol_95", label: "Petrol 95", icon: "⛽" },
        { key: "auto_diesel", label: "Diesel", icon: "🚛" },
        { key: "kerosene", label: "Kerosene", icon: "🔥" },
    ];

    return (
        <Card className="p-4 bg-card border-border">
            <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                    <div className="p-2 rounded-lg bg-amber-500/20">
                        <Fuel className="w-5 h-5 text-amber-500" />
                    </div>
                    <div>
                        <h3 className="font-bold text-sm">⛽ FUEL PRICES</h3>
                        <p className="text-xs text-muted-foreground">CEYPETCO / LIOC</p>
                    </div>
                </div>
                <Badge className="bg-muted text-muted-foreground">
                    {lastRevision || "Latest"}
                </Badge>
            </div>

            <div className="grid grid-cols-2 gap-2">
                {fuelTypes.map(({ key, label, icon }) => {
                    const fuel = prices[key];
                    if (!fuel) return null;

                    return (
                        <div key={key} className="p-2 rounded-lg bg-muted/30 border border-border">
                            <div className="flex items-center justify-between mb-1">
                                <span className="text-xs text-muted-foreground">{icon} {label}</span>
                            </div>
                            <p className="text-lg font-bold text-foreground">
                                Rs. {fuel.price?.toFixed(0) || "-"}
                            </p>
                            <p className="text-xs text-muted-foreground">{fuel.unit || "LKR/L"}</p>
                        </div>
                    );
                })}
            </div>

            <p className="text-xs text-muted-foreground mt-3 text-center">
                Source: ceypetco.gov.lk (CEYPETCO)
            </p>
        </Card>
    );
};

export default FuelPriceMonitor;

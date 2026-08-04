"use client";

import { Card } from "../ui/card";
import { Badge } from "../ui/badge";
import { ShoppingBasket, CheckCircle, AlertCircle } from "lucide-react";

interface Commodity {
    name: string;
    price: number;
    unit: string;
    category: string;
    live?: boolean;
    markets_sampled?: number;
}

interface CommodityPricesProps {
    commodityData?: Record<string, unknown> | null;
}

const CommodityPrices = ({ commodityData }: CommodityPricesProps) => {
    const commodities = (commodityData?.commodities as Commodity[]) || [];
    const summary = (commodityData?.summary as Record<string, number>) || {};
    const dataDate = commodityData?.data_date as string;
    const scrapeStatus = commodityData?.scrape_status as string;
    const source = commodityData?.source as string;

    // Show top 8 essential items
    const essentialItems = commodities.slice(0, 8);

    // Format date nicely
    const formatDate = (dateStr: string) => {
        if (!dateStr) return "";
        try {
            const date = new Date(dateStr);
            return date.toLocaleDateString("en-LK", { month: "short", day: "numeric", year: "numeric" });
        } catch {
            return dateStr;
        }
    };

    return (
        <Card className="p-4 bg-card border-border">
            <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                    <div className="p-2 rounded-lg bg-green-500/20">
                        <ShoppingBasket className="w-5 h-5 text-green-500" />
                    </div>
                    <div>
                        <h3 className="font-bold text-sm">🛒 COMMODITIES</h3>
                        <p className="text-xs text-muted-foreground">Essential goods prices</p>
                    </div>
                </div>
                <div className="flex gap-1">
                    {scrapeStatus === "live" ? (
                        <Badge className="bg-success/20 text-success text-xs flex items-center gap-1">
                            <CheckCircle className="w-3 h-3" />
                            Live
                        </Badge>
                    ) : (
                        <Badge className="bg-warning/20 text-warning text-xs flex items-center gap-1">
                            <AlertCircle className="w-3 h-3" />
                            Baseline
                        </Badge>
                    )}
                    {summary.total_items > 0 && (
                        <Badge variant="outline" className="text-xs">
                            {summary.total_items} items
                        </Badge>
                    )}
                </div>
            </div>

            <div className="grid grid-cols-2 gap-1.5">
                {essentialItems.map((item, idx) => (
                    <div key={idx} className="p-2 rounded bg-muted/30 border border-border">
                        <div className="flex items-center justify-between">
                            <span className="text-xs text-muted-foreground truncate flex-1">{item.name}</span>
                            {item.live && (
                                <span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse"></span>
                            )}
                        </div>
                        <div className="flex items-baseline gap-1 mt-0.5">
                            <span className="text-sm font-bold">Rs.{item.price.toFixed(0)}</span>
                            <span className="text-xs text-muted-foreground">/{item.unit.split("/")[1] || "kg"}</span>
                        </div>
                    </div>
                ))}
            </div>

            <div className="mt-3 text-center">
                <p className="text-xs text-muted-foreground">
                    {source?.includes("WFP") ? "Source: UN World Food Programme" : source ? `Source: ${source}` : "Source: WFP HDX"}
                </p>
                {dataDate && (
                    <p className="text-xs text-muted-foreground/70">
                        Data: {formatDate(dataDate)}
                    </p>
                )}
            </div>
        </Card>
    );
};

export default CommodityPrices;


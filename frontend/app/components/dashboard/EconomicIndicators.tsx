"use client";

import { Card } from "../ui/card";
import { Badge } from "../ui/badge";
import { TrendingUp, TrendingDown, Minus, Landmark, DollarSign, Percent, Building2, Radio } from "lucide-react";

interface EconomicIndicatorsProps {
    economyData?: Record<string, unknown> | null;
}

const EconomicIndicators = ({ economyData }: EconomicIndicatorsProps) => {
    const indicators = (economyData?.indicators as Record<string, Record<string, unknown>>) || {};
    const inflation = indicators?.inflation || {};
    const policyRates = indicators?.policy_rates || {};
    const exchangeRate = indicators?.exchange_rate || {};
    const forexReserves = indicators?.forex_reserves || {};
    const dataAsOf = economyData?.data_as_of as string;
    const scrapeStatus = economyData?.scrape_status as string;

    const getTrendIcon = (trend: string) => {
        if (trend === "improving" || trend === "stable") return <TrendingUp className="w-3 h-3 text-success" />;
        if (trend === "declining") return <TrendingDown className="w-3 h-3 text-destructive" />;
        return <Minus className="w-3 h-3 text-muted-foreground" />;
    };

    // Get the exchange rate - prefer mid rate, fallback to sell or buy
    const usdLkr = (exchangeRate.usd_lkr as number) ||
        (exchangeRate.usd_lkr_sell as number) ||
        (exchangeRate.usd_lkr_buy as number) || 0;

    // Get policy rate - prefer overnight, fallback to SDFR
    const policyRate = (policyRates.overnight_rate as number) || (policyRates.sdfr as number) || 0;

    return (
        <Card className="p-4 bg-card border-border">
            <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                    <div className="p-2 rounded-lg bg-blue-500/20">
                        <Landmark className="w-5 h-5 text-blue-500" />
                    </div>
                    <div>
                        <h3 className="font-bold text-sm">🏛️ ECONOMY</h3>
                        <p className="text-xs text-muted-foreground">CBSL Indicators</p>
                    </div>
                </div>
                <div className="flex items-center gap-1">
                    {scrapeStatus === "live" && (
                        <Badge className="bg-success/20 text-success text-xs flex items-center gap-1">
                            <Radio className="w-2 h-2 animate-pulse" />
                            LIVE
                        </Badge>
                    )}
                    <Badge className="bg-muted text-muted-foreground">
                        {dataAsOf || "Latest"}
                    </Badge>
                </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
                {/* Inflation */}
                <div className="p-2 rounded-lg bg-muted/30 border border-border">
                    <div className="flex items-center gap-1 mb-1">
                        <Percent className="w-3 h-3 text-muted-foreground" />
                        <span className="text-xs text-muted-foreground">CCPI Inflation</span>
                    </div>
                    <div className="flex items-center gap-1">
                        <span className="text-lg font-bold">{inflation.ccpi_yoy as number || 0}%</span>
                        {getTrendIcon(inflation.trend as string)}
                    </div>
                </div>

                {/* USD/LKR */}
                <div className="p-2 rounded-lg bg-muted/30 border border-border">
                    <div className="flex items-center gap-1 mb-1">
                        <DollarSign className="w-3 h-3 text-muted-foreground" />
                        <span className="text-xs text-muted-foreground">USD/LKR</span>
                    </div>
                    <div className="flex items-center gap-1">
                        <span className="text-lg font-bold">{usdLkr.toFixed(2)}</span>
                        {getTrendIcon(exchangeRate.trend as string)}
                    </div>
                    {/* Show Buy/Sell if available */}
                    {((exchangeRate.usd_lkr_buy as number | undefined) || (exchangeRate.usd_lkr_sell as number | undefined)) && (
                        <p className="text-xs text-muted-foreground mt-0.5">
                            Buy: {((exchangeRate.usd_lkr_buy as number | undefined)?.toFixed(2)) || "—"} |
                            Sell: {((exchangeRate.usd_lkr_sell as number | undefined)?.toFixed(2)) || "—"}
                        </p>
                    )}
                </div>

                {/* Policy Rate */}
                <div className="p-2 rounded-lg bg-muted/30 border border-border">
                    <div className="flex items-center gap-1 mb-1">
                        <Landmark className="w-3 h-3 text-muted-foreground" />
                        <span className="text-xs text-muted-foreground">Policy Rate</span>
                    </div>
                    <span className="text-lg font-bold">{policyRate}%</span>
                </div>

                {/* Forex Reserves */}
                <div className="p-2 rounded-lg bg-muted/30 border border-border">
                    <div className="flex items-center gap-1 mb-1">
                        <Building2 className="w-3 h-3 text-muted-foreground" />
                        <span className="text-xs text-muted-foreground">Reserves</span>
                    </div>
                    <div className="flex items-center gap-1">
                        <span className="text-lg font-bold">${(forexReserves.value as number) || 0}B</span>
                        {getTrendIcon(forexReserves.trend as string)}
                    </div>
                </div>
            </div>

            <p className="text-xs text-muted-foreground mt-3 text-center">
                Source: cbsl.gov.lk (Central Bank of Sri Lanka)
            </p>
        </Card>
    );
};

export default EconomicIndicators;


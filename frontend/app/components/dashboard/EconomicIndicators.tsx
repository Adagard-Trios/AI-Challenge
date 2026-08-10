"use client";

import { Card } from "../ui/card";
import { TrendingUp, TrendingDown, Minus, Landmark, DollarSign, Percent, Building2 } from "lucide-react";
import DataProvenance from "./DataProvenance";
import { EMPTY } from "@/app/lib/format";

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

    // Each of these falls back to `null`, not 0.
    //
    // A currency board panel that prints "USD/LKR 0.00", "Inflation 0%" and
    // "Reserves $0B" when the scrape failed is stating four things that are
    // not true and would each be extraordinary news if they were. formatMeasure
    // and friends render null as an em-dash, which is the honest answer.
    const first = (...values: unknown[]): number | null => {
        for (const v of values) if (typeof v === "number" && !Number.isNaN(v)) return v;
        return null;
    };

    // Get the exchange rate - prefer mid rate, fallback to sell or buy
    const usdLkr = first(exchangeRate.usd_lkr, exchangeRate.usd_lkr_sell, exchangeRate.usd_lkr_buy);

    // Get policy rate - prefer overnight, fallback to SDFR
    const policyRate = first(policyRates.overnight_rate, policyRates.sdfr);

    const ccpi = first(inflation.ccpi_yoy);
    const reserves = first(forexReserves.value);

    return (
        <Card className="p-4 bg-card border-border">
            <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                    <div className="p-2 rounded-lg bg-info/20">
                        <Landmark className="w-5 h-5 text-info" />
                    </div>
                    <div>
                        <h3 className="font-bold text-base">ECONOMY</h3>
                        <p className="text-xs text-muted-foreground">CBSL Indicators</p>
                    </div>
                </div>
                {/* Was: a LIVE badge when live, and nothing otherwise -- so
                    stale data was signalled by an absent badge, and the
                    hardcoded 2.1% inflation figure looked live. */}
                <DataProvenance status={scrapeStatus} asOf={dataAsOf} />
            </div>

            <div className="grid grid-cols-2 gap-2">
                {/* Inflation */}
                <div className="p-2 rounded-lg bg-muted/30 border border-border">
                    <div className="flex items-center gap-1 mb-1">
                        <Percent className="w-3 h-3 text-muted-foreground" />
                        <span className="text-xs text-muted-foreground">CCPI Inflation</span>
                    </div>
                    <div className="flex items-center gap-1">
                        <span className={`text-xl font-bold ${ccpi === null ? "text-muted-foreground" : ""}`}>
                            {ccpi === null ? EMPTY : `${ccpi}%`}
                        </span>
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
                        <span className={`text-xl font-bold ${usdLkr === null ? "text-muted-foreground" : ""}`}>
                            {usdLkr === null ? EMPTY : usdLkr.toFixed(2)}
                        </span>
                        {getTrendIcon(exchangeRate.trend as string)}
                    </div>
                    {/* Show Buy/Sell if available */}
                    {((exchangeRate.usd_lkr_buy as number | undefined) || (exchangeRate.usd_lkr_sell as number | undefined)) && (
                        <p className="text-xs text-muted-foreground mt-0.5">
                            Buy: {((exchangeRate.usd_lkr_buy as number | undefined)?.toFixed(2)) || "n/a"} |
                            Sell: {((exchangeRate.usd_lkr_sell as number | undefined)?.toFixed(2)) || "n/a"}
                        </p>
                    )}
                </div>

                {/* Policy Rate */}
                <div className="p-2 rounded-lg bg-muted/30 border border-border">
                    <div className="flex items-center gap-1 mb-1">
                        <Landmark className="w-3 h-3 text-muted-foreground" />
                        <span className="text-xs text-muted-foreground">Policy Rate</span>
                    </div>
                    <span className={`text-xl font-bold ${policyRate === null ? "text-muted-foreground" : ""}`}>
                        {policyRate === null ? EMPTY : `${policyRate}%`}
                    </span>
                </div>

                {/* Forex Reserves */}
                <div className="p-2 rounded-lg bg-muted/30 border border-border">
                    <div className="flex items-center gap-1 mb-1">
                        <Building2 className="w-3 h-3 text-muted-foreground" />
                        <span className="text-xs text-muted-foreground">Reserves</span>
                    </div>
                    <div className="flex items-center gap-1">
                        <span className={`text-xl font-bold ${reserves === null ? "text-muted-foreground" : ""}`}>
                            {reserves === null ? EMPTY : `$${reserves}B`}
                        </span>
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


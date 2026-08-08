"use client";

import React, { useState, useEffect } from "react";
import { RefreshCw, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { API_BASE, apiFetch } from "@/app/lib/api";
import ModelStaleness, { type TrainingInfo } from "./ModelStaleness";
import ModelUnavailable from "./ModelUnavailable";

interface CurrencyPrediction {
    prediction_date: string;
    generated_at: string;
    model_version: string;
    current_rate: number;
    predicted_rate: number;
    expected_change: number;
    expected_change_pct: number;
    direction: string;
    direction_emoji: string;
    volatility_class: string;
    weekly_trend?: number;
    monthly_trend?: number;
    is_fallback?: boolean;
}


/** One day on the 7-day sparkline. Only these two fields are read. */
interface RateHistoryPoint {
    date: string;
    close: number;
}

const VOLATILITY_COLORS = {
    low: "bg-success/20 text-success border-success/50",
    medium: "bg-severity-medium/20 text-severity-medium border-severity-medium/50",
    high: "bg-destructive/20 text-destructive border-destructive/50",
};

export default function CurrencyPrediction() {
    const [prediction, setPrediction] = useState<CurrencyPrediction | null>(null);
    const [training, setTraining] = useState<TrainingInfo | null>(null);
    const [history, setHistory] = useState<RateHistoryPoint[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [unavailable, setUnavailable] = useState(false);

    useEffect(() => {
        fetchPrediction();
        fetchHistory();
        // Refresh every hour
        const interval = setInterval(() => {
            fetchPrediction();
            fetchHistory();
        }, 60 * 60 * 1000);
        return () => clearInterval(interval);
    }, []);

    const fetchPrediction = async () => {
        try {
            const res = await apiFetch(`${API_BASE}/api/currency/prediction`);
            const data = await res.json();
            setTraining(data.training ?? null);

            if (data.status === "success") {
                setPrediction(data.prediction);
                setError(null);
                setUnavailable(false);
            } else if (data.status === "unavailable") {
                // A GRU that needs TensorFlow, on a 512 MB instance. Not a fault.
                setUnavailable(true);
                setError(data.message ?? null);
            } else {
                setUnavailable(false);
                setError(data.message || "Failed to load prediction");
            }
        } catch (err) {
            setError("Failed to connect to API");
        } finally {
            setLoading(false);
        }
    };

    const fetchHistory = async () => {
        try {
            const res = await apiFetch(`${API_BASE}/api/currency/history?days=7`);
            const data = await res.json();
            if (data.status === "success") {
                setHistory(data.history.slice(-7)); // Last 7 days
            }
        } catch (err) {
            console.error("Failed to fetch history:", err);
        }
    };

    if (loading) {
        return (
            <div className="bg-card rounded-xl p-6 border border-border">
                <div className="animate-pulse space-y-4">
                    <div className="h-6 bg-muted rounded w-1/3"></div>
                    <div className="h-20 bg-muted rounded"></div>
                </div>
            </div>
        );
    }

    return (
        <div className="bg-card rounded-xl p-6 border border-border">
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h2 className="text-xl font-bold text-foreground flex items-center gap-2">
                        USD/LKR Prediction
                    </h2>
                    {prediction && (
                        <p className="text-sm text-foreground mt-1">
                            Forecast for {prediction.prediction_date}
                        </p>
                    )}
                </div>
                {/* Was an emoji with no accessible name: a screen reader read
                    it as "counterclockwise arrows button" or nothing at all. */}
                <button
                    onClick={fetchPrediction}
                    className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-lg bg-muted hover:bg-muted/80 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                    title="Refresh"
                    aria-label="Refresh USD/LKR prediction"
                >
                    <RefreshCw className="w-4 h-4" />
                </button>
            </div>

            <ModelStaleness training={training} className="mb-4" />

            {unavailable ? (
                <ModelUnavailable
                    capability="USD/LKR exchange-rate prediction"
                    serviceEnv="CURRENCY_SERVICE_URL"
                    message={error}
                />
            ) : error ? (
                <div className="text-center py-8">
                    <p className="text-destructive mb-4">{error}</p>
                    <button
                        onClick={fetchPrediction}
                        className="px-4 py-2 min-h-[44px] bg-info text-info-foreground hover:bg-info/90 rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                    >
                        Retry
                    </button>
                </div>
            ) : prediction ? (
                <>
                    {/* Main Prediction Card */}
                    <div
                        className={`p-6 rounded-xl border mb-6 ${prediction.expected_change_pct < 0
                            ? "bg-success/10 border-success/50"
                            : "bg-destructive/10 border-destructive/50"
                            }`}
                    >
                        <div className="grid grid-cols-3 gap-4 text-center">
                            <div>
                                <div className="text-foreground text-sm">Current Rate</div>
                                <div className="text-2xl font-bold text-foreground">
                                    {prediction.current_rate.toFixed(2)}
                                </div>
                                <div className="text-xs text-muted-foreground">LKR/USD</div>
                            </div>
                            <div className="flex items-center justify-center">
                                {/* direction_emoji comes from the API as a raw
                                    emoji string, which renders at whatever size
                                    and style the OS font decides and cannot take
                                    the surrounding colour. Derived from the
                                    number instead. */}
                                {prediction.expected_change_pct < 0 ? (
                                    <TrendingDown className="w-10 h-10 text-success" aria-label="Rupee strengthening" />
                                ) : prediction.expected_change_pct > 0 ? (
                                    <TrendingUp className="w-10 h-10 text-destructive" aria-label="Rupee weakening" />
                                ) : (
                                    <Minus className="w-10 h-10 text-muted-foreground" aria-label="No change" />
                                )}
                            </div>
                            <div>
                                <div className="text-foreground text-sm">Predicted</div>
                                <div className="text-2xl font-bold text-foreground">
                                    {prediction.predicted_rate.toFixed(2)}
                                </div>
                                <div className="text-xs text-muted-foreground">LKR/USD</div>
                            </div>
                        </div>

                        <div className="mt-4 pt-4 border-t border-border flex items-center justify-between">
                            <div>
                                <span className="text-foreground">Expected Change: </span>
                                <span
                                    className={`font-bold ${prediction.expected_change_pct < 0
                                        ? "text-success"
                                        : "text-destructive"
                                        }`}
                                >
                                    {prediction.expected_change_pct > 0 ? "+" : ""}
                                    {prediction.expected_change_pct.toFixed(3)}%
                                </span>
                            </div>
                            <div
                                className={`px-3 py-1 rounded-full text-sm ${VOLATILITY_COLORS[prediction.volatility_class as keyof typeof VOLATILITY_COLORS] ||
                                    VOLATILITY_COLORS.low
                                    }`}
                            >
                                {prediction.volatility_class.toUpperCase()} Volatility
                            </div>
                        </div>
                    </div>

                    {/* Trend Info */}
                    <div className="grid grid-cols-2 gap-4 mb-6">
                        {prediction.weekly_trend !== undefined && (
                            <div className="p-4 rounded-lg bg-muted">
                                <div className="text-foreground text-sm">7-Day Trend</div>
                                <div
                                    className={`text-lg font-bold ${prediction.weekly_trend < 0 ? "text-success" : "text-destructive"
                                        }`}
                                >
                                    {prediction.weekly_trend > 0 ? "+" : ""}
                                    {prediction.weekly_trend.toFixed(2)}%
                                </div>
                            </div>
                        )}
                        {prediction.monthly_trend !== undefined && (
                            <div className="p-4 rounded-lg bg-muted">
                                <div className="text-foreground text-sm">30-Day Trend</div>
                                <div
                                    className={`text-lg font-bold ${prediction.monthly_trend < 0 ? "text-success" : "text-destructive"
                                        }`}
                                >
                                    {prediction.monthly_trend > 0 ? "+" : ""}
                                    {prediction.monthly_trend.toFixed(2)}%
                                </div>
                            </div>
                        )}
                    </div>

                    {/* Mini Chart (7-day history) */}
                    {history.length > 0 && (
                        <div className="p-4 rounded-lg bg-muted">
                            <div className="text-sm text-foreground mb-2">Last 7 Days</div>
                            <div className="flex items-end justify-between h-16 gap-1">
                                {history.map((day, i) => {
                                    const minRate = Math.min(...history.map((h) => h.close));
                                    const maxRate = Math.max(...history.map((h) => h.close));
                                    const range = maxRate - minRate || 1;
                                    const height = ((day.close - minRate) / range) * 100;

                                    return (
                                        <div
                                            key={i}
                                            className="flex-1 bg-info/50 rounded-t hover:bg-info/50 transition-colors"
                                            style={{ height: `${Math.max(20, height)}%` }}
                                            title={`${day.date}: ${day.close.toFixed(2)} LKR`}
                                        />
                                    );
                                })}
                            </div>
                        </div>
                    )}


                    {/* Footer */}
                    <div className="mt-4 text-xs text-muted-foreground text-center space-y-1">
                        <div>
                            Generated: {new Date(prediction.generated_at).toLocaleString()} |
                            Model: {prediction.model_version}
                        </div>
                        <div>
                            Data: cbsl.gov.lk (CBSL) | Model: LSTM Neural Network
                        </div>
                    </div>
                </>
            ) : null}
        </div>
    );
}

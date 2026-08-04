"use client";

import React, { useState, useEffect } from "react";

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

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

const VOLATILITY_COLORS = {
    low: "bg-green-500/20 text-green-400 border-green-500/50",
    medium: "bg-yellow-500/20 text-yellow-400 border-yellow-500/50",
    high: "bg-red-500/20 text-red-400 border-red-500/50",
};

export default function CurrencyPrediction() {
    const [prediction, setPrediction] = useState<CurrencyPrediction | null>(null);
    const [history, setHistory] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

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
            const res = await fetch(`${API_BASE}/api/currency/prediction`);
            const data = await res.json();

            if (data.status === "success") {
                setPrediction(data.prediction);
                setError(null);
            } else {
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
            const res = await fetch(`${API_BASE}/api/currency/history?days=7`);
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
            <div className="bg-slate-800/50 rounded-xl p-6 border border-slate-700/50">
                <div className="animate-pulse space-y-4">
                    <div className="h-6 bg-slate-700 rounded w-1/3"></div>
                    <div className="h-20 bg-slate-700 rounded"></div>
                </div>
            </div>
        );
    }

    return (
        <div className="bg-slate-800/50 rounded-xl p-6 border border-slate-700/50">
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h2 className="text-xl font-bold text-white flex items-center gap-2">
                        💱 USD/LKR Prediction
                    </h2>
                    {prediction && (
                        <p className="text-sm text-slate-400 mt-1">
                            Forecast for {prediction.prediction_date}
                        </p>
                    )}
                </div>
                <button
                    onClick={fetchPrediction}
                    className="p-2 rounded-lg bg-slate-700 hover:bg-slate-600 transition-colors"
                    title="Refresh"
                >
                    🔄
                </button>
            </div>

            {error ? (
                <div className="text-center py-8">
                    <p className="text-red-400 mb-4">{error}</p>
                    <button
                        onClick={fetchPrediction}
                        className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg transition-colors"
                    >
                        Retry
                    </button>
                </div>
            ) : prediction ? (
                <>
                    {/* Main Prediction Card */}
                    <div
                        className={`p-6 rounded-xl border mb-6 ${prediction.expected_change_pct < 0
                            ? "bg-green-500/10 border-green-500/30"
                            : "bg-red-500/10 border-red-500/30"
                            }`}
                    >
                        <div className="grid grid-cols-3 gap-4 text-center">
                            <div>
                                <div className="text-slate-400 text-sm">Current Rate</div>
                                <div className="text-2xl font-bold text-white">
                                    {prediction.current_rate.toFixed(2)}
                                </div>
                                <div className="text-xs text-slate-500">LKR/USD</div>
                            </div>
                            <div className="flex items-center justify-center">
                                <div className="text-4xl">
                                    {prediction.direction_emoji}
                                </div>
                            </div>
                            <div>
                                <div className="text-slate-400 text-sm">Predicted</div>
                                <div className="text-2xl font-bold text-white">
                                    {prediction.predicted_rate.toFixed(2)}
                                </div>
                                <div className="text-xs text-slate-500">LKR/USD</div>
                            </div>
                        </div>

                        <div className="mt-4 pt-4 border-t border-white/10 flex items-center justify-between">
                            <div>
                                <span className="text-slate-400">Expected Change: </span>
                                <span
                                    className={`font-bold ${prediction.expected_change_pct < 0
                                        ? "text-green-400"
                                        : "text-red-400"
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
                            <div className="p-4 rounded-lg bg-slate-700/50">
                                <div className="text-slate-400 text-sm">7-Day Trend</div>
                                <div
                                    className={`text-lg font-bold ${prediction.weekly_trend < 0 ? "text-green-400" : "text-red-400"
                                        }`}
                                >
                                    {prediction.weekly_trend > 0 ? "+" : ""}
                                    {prediction.weekly_trend.toFixed(2)}%
                                </div>
                            </div>
                        )}
                        {prediction.monthly_trend !== undefined && (
                            <div className="p-4 rounded-lg bg-slate-700/50">
                                <div className="text-slate-400 text-sm">30-Day Trend</div>
                                <div
                                    className={`text-lg font-bold ${prediction.monthly_trend < 0 ? "text-green-400" : "text-red-400"
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
                        <div className="p-4 rounded-lg bg-slate-700/30">
                            <div className="text-sm text-slate-400 mb-2">Last 7 Days</div>
                            <div className="flex items-end justify-between h-16 gap-1">
                                {history.map((day, i) => {
                                    const minRate = Math.min(...history.map((h) => h.close));
                                    const maxRate = Math.max(...history.map((h) => h.close));
                                    const range = maxRate - minRate || 1;
                                    const height = ((day.close - minRate) / range) * 100;

                                    return (
                                        <div
                                            key={i}
                                            className="flex-1 bg-blue-500/50 rounded-t hover:bg-blue-400/50 transition-colors"
                                            style={{ height: `${Math.max(20, height)}%` }}
                                            title={`${day.date}: ${day.close.toFixed(2)} LKR`}
                                        />
                                    );
                                })}
                            </div>
                        </div>
                    )}


                    {/* Footer */}
                    <div className="mt-4 text-xs text-slate-500 text-center space-y-1">
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

"use client";

import React, { useState, useEffect } from "react";

interface DistrictPrediction {
    temperature: {
        high_c: number;
        low_c: number;
    };
    rainfall: {
        amount_mm: number;
        probability: number;
    };
    flood_risk: number;
    humidity_pct: number;
    severity: "normal" | "advisory" | "warning" | "critical";
    station_used: string;
    is_fallback?: boolean;
}

interface WeatherPredictions {
    status: string;
    prediction_date: string;
    generated_at: string;
    districts: Record<string, DistrictPrediction>;
    total_districts: number;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

const SEVERITY_COLORS = {
    normal: "bg-green-500/20 text-green-400 border-green-500/50",
    advisory: "bg-yellow-500/20 text-yellow-400 border-yellow-500/50",
    warning: "bg-orange-500/20 text-orange-400 border-orange-500/50",
    critical: "bg-red-500/20 text-red-400 border-red-500/50",
};

const SEVERITY_ICONS = {
    normal: "☀️",
    advisory: "🌤️",
    warning: "⛈️",
    critical: "🌊",
};

export default function WeatherPredictions() {
    const [predictions, setPredictions] = useState<WeatherPredictions | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [selectedDistrict, setSelectedDistrict] = useState<string | null>(null);
    const [filter, setFilter] = useState<string>("all");

    useEffect(() => {
        fetchPredictions();
        // Refresh every 30 minutes
        const interval = setInterval(fetchPredictions, 30 * 60 * 1000);
        return () => clearInterval(interval);
    }, []);

    const fetchPredictions = async () => {
        try {
            const res = await fetch(`${API_BASE}/api/weather/predictions`);
            const data = await res.json();

            if (data.status === "success") {
                setPredictions(data);
                setError(null);
            } else {
                setError(data.message || "Failed to load predictions");
            }
        } catch (err) {
            setError("Failed to connect to weather API");
        } finally {
            setLoading(false);
        }
    };

    const getFilteredDistricts = () => {
        if (!predictions?.districts) return [];

        const entries = Object.entries(predictions.districts);

        if (filter === "all") return entries;
        return entries.filter(([_, pred]) => pred.severity === filter);
    };

    const getSeverityCounts = () => {
        if (!predictions?.districts) return { normal: 0, advisory: 0, warning: 0, critical: 0 };

        const counts = { normal: 0, advisory: 0, warning: 0, critical: 0 };
        Object.values(predictions.districts).forEach((pred) => {
            counts[pred.severity] = (counts[pred.severity] || 0) + 1;
        });
        return counts;
    };

    if (loading) {
        return (
            <div className="bg-slate-800/50 rounded-xl p-6 border border-slate-700/50">
                <div className="animate-pulse space-y-4">
                    <div className="h-6 bg-slate-700 rounded w-1/3"></div>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        {[1, 2, 3, 4].map((i) => (
                            <div key={i} className="h-24 bg-slate-700 rounded-lg"></div>
                        ))}
                    </div>
                </div>
            </div>
        );
    }

    const sevCounts = getSeverityCounts();
    const filteredDistricts = getFilteredDistricts();

    return (
        <div className="bg-slate-800/50 rounded-xl p-6 border border-slate-700/50">
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h2 className="text-xl font-bold text-white flex items-center gap-2">
                        🌦️ Weather Predictions
                    </h2>
                    {predictions && (
                        <p className="text-sm text-slate-400 mt-1">
                            Forecast for {predictions.prediction_date}
                        </p>
                    )}
                </div>
                <button
                    onClick={fetchPredictions}
                    className="p-2 rounded-lg bg-slate-700 hover:bg-slate-600 transition-colors"
                    title="Refresh predictions"
                >
                    🔄
                </button>
            </div>

            {error ? (
                <div className="text-center py-8">
                    <p className="text-red-400 mb-4">{error}</p>
                    <button
                        onClick={fetchPredictions}
                        className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg transition-colors"
                    >
                        Retry
                    </button>
                </div>
            ) : (
                <>
                    {/* Severity Summary */}
                    <div className="grid grid-cols-4 gap-3 mb-6">
                        {(["normal", "advisory", "warning", "critical"] as const).map((sev) => (
                            <button
                                key={sev}
                                onClick={() => setFilter(filter === sev ? "all" : sev)}
                                className={`p-3 rounded-lg border transition-all ${filter === sev ? "ring-2 ring-white/30" : ""
                                    } ${SEVERITY_COLORS[sev]}`}
                            >
                                <div className="text-2xl">{SEVERITY_ICONS[sev]}</div>
                                <div className="text-lg font-bold">{sevCounts[sev]}</div>
                                <div className="text-xs capitalize">{sev}</div>
                            </button>
                        ))}
                    </div>

                    {/* District Grid */}
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 max-h-[500px] overflow-y-auto intel-scrollbar pr-2">
                        {filteredDistricts.map(([district, pred]) => (
                            <div
                                key={district}
                                className={`p-4 rounded-lg border cursor-pointer transition-all hover:scale-[1.02] ${SEVERITY_COLORS[pred.severity]
                                    } ${selectedDistrict === district ? "ring-2 ring-white/50" : ""}`}
                                onClick={() => setSelectedDistrict(selectedDistrict === district ? null : district)}
                            >
                                <div className="flex items-center justify-between mb-2">
                                    <h3 className="font-semibold text-white">{district}</h3>
                                    <span className="text-xl">{SEVERITY_ICONS[pred.severity]}</span>
                                </div>

                                <div className="grid grid-cols-2 gap-2 text-sm">
                                    <div>
                                        <span className="text-slate-400">Temp:</span>
                                        <span className="ml-1 text-white">
                                            {pred.temperature.low_c}° - {pred.temperature.high_c}°C
                                        </span>
                                    </div>
                                    <div>
                                        <span className="text-slate-400">Rain:</span>
                                        <span className="ml-1 text-white">
                                            {pred.rainfall.amount_mm}mm
                                        </span>
                                    </div>
                                </div>

                                {pred.flood_risk > 0 && (
                                    <div className="mt-2 text-sm">
                                        <span className="text-red-400">⚠️ Flood Risk: </span>
                                        <span className="text-white">{(pred.flood_risk * 100).toFixed(0)}%</span>
                                    </div>
                                )}

                                {/* Expanded details */}
                                {selectedDistrict === district && (
                                    <div className="mt-4 pt-3 border-t border-white/20 text-sm space-y-2">
                                        <div className="flex justify-between">
                                            <span className="text-slate-400">Rain Probability:</span>
                                            <span className="text-white">{(pred.rainfall.probability * 100).toFixed(0)}%</span>
                                        </div>
                                        <div className="flex justify-between">
                                            <span className="text-slate-400">Humidity:</span>
                                            <span className="text-white">{pred.humidity_pct}%</span>
                                        </div>
                                        <div className="flex justify-between">
                                            <span className="text-slate-400">Station:</span>
                                            <span className="text-white">{pred.station_used}</span>
                                        </div>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>

                    {/* Footer */}
                    {predictions && (
                        <div className="mt-4 text-xs text-slate-500 text-center space-y-1">
                            <div>
                                Generated: {new Date(predictions.generated_at).toLocaleString()} |
                                {predictions.total_districts} districts
                            </div>
                            <div>
                                Data: meteo.gov.lk (DMC) | Model: ML Weather Forecasting
                            </div>
                        </div>
                    )}
                </>
            )}
        </div>
    );
}

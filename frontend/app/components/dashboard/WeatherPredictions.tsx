"use client";

import { Sun, CloudSun, CloudLightning, Waves, RefreshCw } from "lucide-react";

import React, { useState, useEffect } from "react";
import { API_BASE, apiFetch } from "@/app/lib/api";
import ModelStaleness, { type TrainingInfo } from "./ModelStaleness";
import ModelUnavailable from "./ModelUnavailable";

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


const SEVERITY_COLORS = {
    normal: "bg-success/20 text-success border-success/50",
    advisory: "bg-severity-medium/20 text-severity-medium border-severity-medium/50",
    warning: "bg-severity-high/20 text-severity-high border-severity-high/50",
    critical: "bg-destructive/20 text-destructive border-destructive/50",
};

// lucide rather than emoji: these inherit currentColor, so they take the
// severity tone, and they scale with the type ramp instead of rendering at
// whatever size the platform's emoji font decides.
const SEVERITY_ICONS = {
    normal: Sun,
    advisory: CloudSun,
    warning: CloudLightning,
    critical: Waves,
};

export default function WeatherPredictions() {
    const [predictions, setPredictions] = useState<WeatherPredictions | null>(null);
    const [training, setTraining] = useState<TrainingInfo | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [unavailable, setUnavailable] = useState(false);
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
            const res = await apiFetch(`${API_BASE}/api/weather/predictions`);
            const data = await res.json();
            setTraining(data.training ?? null);

            if (data.status === "success") {
                setPredictions(data);
                setError(null);
                setUnavailable(false);
            } else if (data.status === "unavailable") {
                // Not an error. The model is a TensorFlow build that does not
                // fit on the deployed instance, and saying "Failed to load"
                // describes a broken product rather than an unpaid-for one.
                setUnavailable(true);
                setError(data.message ?? null);
            } else {
                setUnavailable(false);
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
            <div className="bg-card rounded-xl p-6 border border-border">
                <div className="animate-pulse space-y-4">
                    <div className="h-6 bg-muted rounded w-1/3"></div>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        {[1, 2, 3, 4].map((i) => (
                            <div key={i} className="h-24 bg-muted rounded-lg"></div>
                        ))}
                    </div>
                </div>
            </div>
        );
    }

    const sevCounts = getSeverityCounts();
    const filteredDistricts = getFilteredDistricts();

    return (
        <div className="bg-card rounded-xl p-6 border border-border">
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h2 className="text-xl font-bold text-foreground flex items-center gap-2">
                        Weather Predictions
                    </h2>
                    {predictions && (
                        <p className="text-sm text-foreground mt-1">
                            Forecast for {predictions.prediction_date}
                        </p>
                    )}
                </div>
                <button
                    onClick={fetchPredictions}
                    className="p-2 rounded-lg bg-muted hover:bg-muted/80 transition-colors"
                    title="Refresh predictions"
                >
                    
                </button>
            </div>

            <ModelStaleness training={training} className="mb-4" />

            {unavailable ? (
                <ModelUnavailable
                    capability="District weather and flood-risk prediction"
                    serviceEnv="WEATHER_SERVICE_URL"
                    message={error}
                />
            ) : error ? (
                <div className="text-center py-8">
                    <p className="text-destructive mb-4">{error}</p>
                    <button
                        onClick={fetchPredictions}
                        className="px-4 py-2 bg-info hover:bg-info/90 rounded-lg transition-colors"
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
                                {(() => { const I = SEVERITY_ICONS[sev]; return <I className="w-6 h-6" aria-hidden="true" />; })()}
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
                                    <h3 className="font-semibold text-foreground">{district}</h3>
                                    {(() => { const I = SEVERITY_ICONS[pred.severity]; return <I className="w-5 h-5 shrink-0" aria-hidden="true" />; })()}
                                </div>

                                <div className="grid grid-cols-2 gap-2 text-sm">
                                    <div>
                                        <span className="text-foreground">Temp:</span>
                                        <span className="ml-1 text-foreground">
                                            {pred.temperature.low_c}° - {pred.temperature.high_c}°C
                                        </span>
                                    </div>
                                    <div>
                                        <span className="text-foreground">Rain:</span>
                                        <span className="ml-1 text-foreground">
                                            {pred.rainfall.amount_mm}mm
                                        </span>
                                    </div>
                                </div>

                                {pred.flood_risk > 0 && (
                                    <div className="mt-2 text-sm">
                                        <span className="text-destructive">Flood Risk: </span>
                                        <span className="text-foreground">{(pred.flood_risk * 100).toFixed(0)}%</span>
                                    </div>
                                )}

                                {/* Expanded details */}
                                {selectedDistrict === district && (
                                    <div className="mt-4 pt-3 border-t border-border text-sm space-y-2">
                                        <div className="flex justify-between">
                                            <span className="text-foreground">Rain Probability:</span>
                                            <span className="text-foreground">{(pred.rainfall.probability * 100).toFixed(0)}%</span>
                                        </div>
                                        <div className="flex justify-between">
                                            <span className="text-foreground">Humidity:</span>
                                            <span className="text-foreground">{pred.humidity_pct}%</span>
                                        </div>
                                        <div className="flex justify-between">
                                            <span className="text-foreground">Station:</span>
                                            <span className="text-foreground">{pred.station_used}</span>
                                        </div>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>

                    {/* Footer */}
                    {predictions && (
                        <div className="mt-4 text-xs text-muted-foreground text-center space-y-1">
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

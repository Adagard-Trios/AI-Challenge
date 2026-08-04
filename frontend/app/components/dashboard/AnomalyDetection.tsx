'use client'

import { Card } from "../ui/card";
import { Badge } from "../ui/badge";
import { Separator } from "../ui/separator";
import { Brain, AlertTriangle, TrendingUp, RefreshCw, Zap, Database } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useState, useEffect } from "react";

interface AnomalyEvent {
    event_id: string;
    summary: string;
    domain: string;
    severity: string;
    impact_type: string;
    anomaly_score: number;
    is_anomaly: boolean;
    language?: string;
    timestamp?: string;
}

interface ModelStatus {
    model_loaded: boolean;
    models_available: string[];
    vectorizer_loaded: boolean;
    batch_threshold: number;
}

// Use environment variable for API base URL
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

const AnomalyDetection = () => {
    const [anomalies, setAnomalies] = useState<AnomalyEvent[]>([]);
    const [modelStatus, setModelStatus] = useState<ModelStatus | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchAnomalies = async () => {
        try {
            setLoading(true);
            const [anomalyRes, statusRes] = await Promise.all([
                fetch(`${API_BASE}/api/anomalies?limit=20`),
                fetch(`${API_BASE}/api/model/status`)
            ]);

            const anomalyData = await anomalyRes.json();
            const statusData = await statusRes.json();

            setAnomalies(anomalyData.anomalies || []);
            setModelStatus(statusData);
            setError(null);
        } catch (err) {
            setError('Failed to fetch anomalies');
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchAnomalies();
        // Refresh every 30 seconds
        const interval = setInterval(fetchAnomalies, 30000);
        return () => clearInterval(interval);
    }, []);

    const getScoreColor = (score: number) => {
        if (score >= 0.8) return "text-destructive";
        if (score >= 0.6) return "text-warning";
        if (score >= 0.4) return "text-primary";
        return "text-muted-foreground";
    };

    const getScoreBg = (score: number) => {
        if (score >= 0.8) return "bg-destructive/20";
        if (score >= 0.6) return "bg-warning/20";
        if (score >= 0.4) return "bg-primary/20";
        return "bg-muted/20";
    };

    return (
        <Card className="p-6 bg-card border-border">
            {/* Header */}
            <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                    <div className="p-2 rounded-lg bg-primary/20">
                        <Brain className="w-6 h-6 text-primary" />
                    </div>
                    <div>
                        <h2 className="text-lg font-bold">ML ANOMALY DETECTION</h2>
                        <p className="text-xs text-muted-foreground font-mono">
                            Powered by BERT + Isolation Forest
                        </p>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={fetchAnomalies}
                        disabled={loading}
                        className="p-2 rounded-lg hover:bg-muted/50 transition-colors disabled:opacity-50"
                    >
                        <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                    </button>
                    {modelStatus && (
                        <Badge className={modelStatus.model_loaded ? "bg-success/20 text-success" : "bg-warning/20 text-warning"}>
                            {modelStatus.model_loaded ? "Model Active" : "Model Training..."}
                        </Badge>
                    )}
                </div>
            </div>

            {/* Model Status Bar */}
            {modelStatus && (
                <div className="mb-4 p-3 rounded-lg bg-muted/30 flex items-center gap-4 text-xs">
                    <div className="flex items-center gap-2">
                        <Database className="w-4 h-4 text-muted-foreground" />
                        <span>Batch Threshold: <strong>{modelStatus.batch_threshold}</strong> records</span>
                    </div>
                    <Separator orientation="vertical" className="h-4" />
                    <div className="flex items-center gap-2">
                        <Zap className="w-4 h-4 text-muted-foreground" />
                        <span>Models: <strong>{modelStatus.models_available?.length || 0}</strong> trained</span>
                    </div>
                    {modelStatus.models_available?.length > 0 && (
                        <>
                            <Separator orientation="vertical" className="h-4" />
                            <span className="text-muted-foreground">
                                {modelStatus.models_available.join(', ')}
                            </span>
                        </>
                    )}
                </div>
            )}

            <Separator className="mb-4" />

            {/* Anomalies List */}
            <div className="space-y-3 max-h-[500px] overflow-y-auto intel-scrollbar pr-2">
                {loading && anomalies.length === 0 ? (
                    <div className="text-center py-8">
                        <RefreshCw className="w-8 h-8 mx-auto animate-spin text-primary mb-3" />
                        <p className="text-sm text-muted-foreground">Loading anomalies...</p>
                    </div>
                ) : error ? (
                    <div className="text-center py-8">
                        <AlertTriangle className="w-8 h-8 mx-auto text-destructive mb-3" />
                        <p className="text-sm text-destructive">{error}</p>
                    </div>
                ) : anomalies.length === 0 ? (
                    <div className="text-center py-8">
                        <TrendingUp className="w-8 h-8 mx-auto text-success mb-3" />
                        <p className="text-sm text-muted-foreground">No anomalies detected</p>
                        <p className="text-xs text-muted-foreground mt-1">System operating normally</p>
                    </div>
                ) : (
                    <AnimatePresence>
                        {anomalies.map((anomaly, idx) => (
                            <motion.div
                                key={anomaly.event_id || idx}
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                                exit={{ opacity: 0, y: -20 }}
                                transition={{ delay: idx * 0.05 }}
                            >
                                <Card className={`p-4 border-l-4 ${anomaly.is_anomaly ? 'border-l-destructive' : 'border-l-warning'} ${getScoreBg(anomaly.anomaly_score)}`}>
                                    <div className="flex items-start justify-between gap-4">
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2 mb-2 flex-wrap">
                                                <Badge className="bg-destructive/20 text-destructive text-xs">
                                                    ⚠️ ANOMALY
                                                </Badge>
                                                <Badge className="border border-border text-xs">
                                                    {anomaly.domain}
                                                </Badge>
                                                {anomaly.language && anomaly.language !== 'english' && (
                                                    <Badge className="bg-info/20 text-info text-xs">
                                                        {anomaly.language.toUpperCase()}
                                                    </Badge>
                                                )}
                                            </div>
                                            <p className="text-sm font-medium mb-2 leading-relaxed">
                                                {anomaly.summary}
                                            </p>
                                            <div className="flex items-center gap-3 text-xs text-muted-foreground">
                                                <span>Severity: <strong className="text-foreground">{anomaly.severity}</strong></span>
                                                {anomaly.timestamp && (
                                                    <span className="font-mono">
                                                        {new Date(anomaly.timestamp).toLocaleString()}
                                                    </span>
                                                )}
                                            </div>
                                        </div>
                                        <div className="text-right shrink-0">
                                            <div className={`text-2xl font-bold ${getScoreColor(anomaly.anomaly_score)}`}>
                                                {Math.round(anomaly.anomaly_score * 100)}%
                                            </div>
                                            <div className="text-xs text-muted-foreground">
                                                Anomaly Score
                                            </div>
                                        </div>
                                    </div>
                                </Card>
                            </motion.div>
                        ))}
                    </AnimatePresence>
                )}
            </div>

            {/* Footer */}
            <div className="mt-4 pt-4 border-t border-border">
                {anomalies.length > 0 && (
                    <div className="flex items-center justify-between text-xs text-muted-foreground mb-2">
                        <span>Showing {anomalies.length} anomalous events</span>
                        <span className="font-mono">Auto-refresh: 30s</span>
                    </div>
                )}
                <p className="text-xs text-muted-foreground text-center">
                    Data: Live news feeds | Model: Isolation Forest + BERT Embeddings
                </p>
            </div>
        </Card>
    );
};

export default AnomalyDetection;

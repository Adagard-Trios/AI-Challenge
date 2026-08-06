'use client'

import { Card } from "../ui/card";
import { Badge } from "../ui/badge";
import { Separator } from "../ui/separator";
import { Brain, AlertTriangle, TrendingUp, RefreshCw, Zap, Database } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useState, useEffect } from "react";
import { API_BASE, apiFetch } from "@/app/lib/api";

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
    /** "minilm" in production, "bert" locally, null when nothing loaded. */
    embedding?: string | null;
    inference?: string;
    training_card?: {
        embedder?: string;
        dimensions?: number;
        training_documents?: number;
        contamination?: number;
        trained_at?: string;
    } | null;
}

/**
 * What /api/anomalies says about its own answer.
 *
 * `is_ml` is the field that matters. Without it the card cannot tell a real
 * isolation-forest prediction from the severity+keyword fallback, and it used
 * to present both under a heading that said "ML ANOMALY DETECTION" — which was
 * true half the time and misleading the other half.
 */
interface AnomalyResponse {
    anomalies?: AnomalyEvent[];
    is_ml?: boolean;
    model_status?: string;
    embedding?: string | null;
    scored?: number;
    message?: string;
}

// Use environment variable for API base URL

const AnomalyDetection = () => {
    const [anomalies, setAnomalies] = useState<AnomalyEvent[]>([]);
    const [modelStatus, setModelStatus] = useState<ModelStatus | null>(null);
    const [detection, setDetection] = useState<AnomalyResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchAnomalies = async () => {
        try {
            setLoading(true);
            const [anomalyRes, statusRes] = await Promise.all([
                apiFetch(`${API_BASE}/api/anomalies?limit=20`),
                apiFetch(`${API_BASE}/api/model/status`)
            ]);

            const anomalyData: AnomalyResponse = await anomalyRes.json();
            const statusData = await statusRes.json();

            setAnomalies(anomalyData.anomalies || []);
            setDetection(anomalyData);
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

    // Whether a model actually scored these events. Falls back to the model
    // status only when the detection response predates the is_ml field.
    const isMl = detection?.is_ml ?? Boolean(modelStatus?.model_loaded);
    const card = modelStatus?.training_card ?? null;

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
                        <h2 className="text-lg font-bold">ANOMALY DETECTION</h2>
                        <p className="text-xs text-muted-foreground font-mono">
                            {/* The old subtitle said "BERT + Isolation Forest"
                                unconditionally, including when no model was
                                loaded at all. It now describes what actually
                                answered this request. */}
                            {isMl
                                ? `Isolation Forest on ${card?.dimensions ?? 384}-dim sentence embeddings`
                                : "Severity + keyword heuristic — no model loaded"}
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
                    {detection && (
                        <Badge
                            className={isMl ? "bg-success/20 text-success" : "bg-warning/20 text-warning"}
                            title={
                                isMl
                                    ? "A trained model scored these events."
                                    : "No model is loaded. These scores come from severity weighting and keyword matches — useful, but not machine learning."
                            }
                        >
                            {isMl ? "ML INFERENCE" : "HEURISTIC"}
                        </Badge>
                    )}
                </div>
            </div>

            {/* What produced these numbers. A score with no provenance invites
                exactly the over-trust this card should not earn. */}
            {detection && (
                <div className="mb-4 p-3 rounded-lg bg-muted/30 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
                    <div className="flex items-center gap-2">
                        <Zap className="w-4 h-4 text-muted-foreground" />
                        <span>
                            Method:{" "}
                            <strong>
                                {isMl ? "Isolation Forest" : "severity + keyword"}
                            </strong>
                        </span>
                    </div>

                    {isMl && card?.embedder && (
                        <>
                            <Separator orientation="vertical" className="h-4" />
                            <div className="flex items-center gap-2">
                                <Database className="w-4 h-4 text-muted-foreground" />
                                <span title="Embeddings are computed in this container — no external inference service">
                                    Embedding: <strong>{card.embedder}</strong>
                                </span>
                            </div>
                        </>
                    )}

                    {isMl && card?.training_documents != null && (
                        <>
                            <Separator orientation="vertical" className="h-4" />
                            <span
                                className="text-muted-foreground"
                                title="Corpus the model was fitted on. A small corpus is worth knowing about."
                            >
                                Fitted on <strong>{card.training_documents}</strong> events
                                {card.contamination != null &&
                                    ` · expects ${Math.round(card.contamination * 100)}% anomalous`}
                            </span>
                        </>
                    )}

                    {detection.scored != null && (
                        <>
                            <Separator orientation="vertical" className="h-4" />
                            <span className="text-muted-foreground">
                                Scored <strong>{detection.scored}</strong> events
                            </span>
                        </>
                    )}
                </div>
            )}

            {/* The fallback is legitimate; presenting it as ML is not. */}
            {detection && !isMl && detection.message && (
                <div className="mb-4 flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/10 p-3 text-xs text-warning">
                    <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
                    <span>{detection.message}</span>
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

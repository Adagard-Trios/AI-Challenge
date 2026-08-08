"use client";

import { Card } from "../ui/card";
import { Badge } from "../ui/badge";
import { TrendingUp, TrendingDown, Activity, AlertCircle, RefreshCw } from "lucide-react";
import { motion } from "framer-motion";
import { useRogerData } from "../../hooks/use-roger-data";
import { useState, useEffect } from "react";
import ModelStaleness, { type TrainingInfo } from "./ModelStaleness";
import ModelUnavailable from "./ModelUnavailable";
import { API_BASE, apiFetch } from "@/app/lib/api";
import { formatTime } from "@/app/lib/format";


interface StockPrediction {
  symbol: string;
  name: string;
  sector: string;
  current_price: number;
  predicted_price: number;
  expected_change_pct: number;
  trend: string;
  trend_emoji: string;
  confidence: number;
  is_fallback: boolean;
}

interface PredictionsData {
  prediction_date: string;
  generated_at: string;
  stocks: Record<string, StockPrediction>;
  summary: {
    total_stocks: number;
    bullish: number;
    bearish: number;
    neutral: number;
  };
}

const StockPredictions = () => {
  const { events, isConnected } = useRogerData();
  const [predictions, setPredictions] = useState<PredictionsData | null>(null);
  const [training, setTraining] = useState<TrainingInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  // Fetch stock predictions from API
  const fetchPredictions = async () => {
    setLoading(true);
    try {
      const res = await apiFetch(`${API_BASE}/api/stocks/predictions`);
      const data = await res.json();

      // The predictions endpoint carries its model's training cutoff, so
      // the staleness warning costs no extra request.
      setTraining(data.training ?? null);

      if (data.status === "success") {
        setPredictions(data.predictions);
        setError(null);
        setUnavailable(false);
      } else if (data.status === "unavailable") {
        // TensorFlow models on a 512 MB instance. Say so rather than showing
        // a red error that reads as a broken integration.
        setUnavailable(true);
        setError(data.message ?? null);
      } else {
        setUnavailable(false);
        setError(data.message || "Failed to load predictions");
      }
    } catch (err) {
      setError("Failed to connect to stock prediction API");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPredictions();
    // Refresh every 5 minutes
    const interval = setInterval(fetchPredictions, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  // Filter for economic/market events from WebSocket
  const marketEvents = events.filter(e =>
    e.domain === 'economical' || e.domain === 'market'
  );

  const getTrendColor = (trend: string) => {
    switch (trend) {
      case 'bullish': return 'bg-success/20 text-success border-success/50';
      case 'bearish': return 'bg-destructive/20 text-destructive border-destructive/50';
      default: return 'bg-muted text-foreground border-border';
    }
  };

  const stocks = predictions?.stocks ? Object.values(predictions.stocks) : [];

  return (
    <div className="space-y-6">
      {/* Stock Predictions Card */}
      <Card className="p-6 bg-card border-border">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Activity className="w-5 h-5 text-success" />
            <h2 className="text-lg font-bold">CSE STOCK PREDICTIONS 🇱🇰</h2>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={fetchPredictions}
              className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-lg bg-muted/20 hover:bg-muted/40 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
              title="Refresh predictions"
              aria-label="Refresh stock predictions"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
            <div className={`w-2 h-2 rounded-full ${predictions ? 'bg-success animate-pulse' : 'bg-warning'}`} />
            <Badge className="font-mono text-xs border">
              {loading ? 'LOADING...' : predictions ? 'LIVE' : 'OFFLINE'}
            </Badge>
          </div>
        </div>

        {/* Above the numbers, not below them: the reader needs the caveat
            before the figure, not after they have already acted on it. */}
        <ModelStaleness training={training} className="mb-4" />

        {/* Summary Stats */}
        {predictions?.summary && (
          <div className="grid grid-cols-4 gap-2 mb-4">
            <div className="p-2 rounded-lg bg-muted/20 text-center">
              <div className="text-lg font-bold">{predictions.summary.total_stocks}</div>
              <div className="text-xs text-muted-foreground">Total</div>
            </div>
            <div className="p-2 rounded-lg bg-success/10 text-center">
              <div className="text-lg font-bold text-success">{predictions.summary.bullish}</div>
              <div className="text-xs text-success">Bullish 📈</div>
            </div>
            <div className="p-2 rounded-lg bg-destructive/10 text-center">
              <div className="text-lg font-bold text-destructive">{predictions.summary.bearish}</div>
              <div className="text-xs text-destructive">Bearish 📉</div>
            </div>
            <div className="p-2 rounded-lg bg-muted text-center">
              <div className="text-lg font-bold text-foreground">{predictions.summary.neutral}</div>
              <div className="text-xs text-foreground">Neutral ➡️</div>
            </div>
          </div>
        )}

        {/* Stock Predictions List */}
        {loading ? (
          <div className="flex flex-col items-center justify-center py-12">
            <RefreshCw className="w-8 h-8 animate-spin text-muted-foreground mb-4" />
            <p className="text-muted-foreground">Loading predictions...</p>
          </div>
        ) : unavailable ? (
          <ModelUnavailable
            capability="CSE stock-price prediction"
            serviceEnv="STOCK_SERVICE_URL"
            message={error}
          />
        ) : error ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <AlertCircle className="w-12 h-12 text-destructive mb-4" />
            <p className="text-destructive">{error}</p>
            <button
              onClick={fetchPredictions}
              className="mt-4 px-4 py-2 min-h-[44px] bg-muted rounded-lg hover:bg-muted/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              Retry
            </button>
          </div>
        ) : stocks.length > 0 ? (
          <div className="space-y-2 max-h-[400px] overflow-y-auto intel-scrollbar pr-2">
            {stocks.map((stock, idx) => (
              <motion.div
                key={stock.symbol}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: idx * 0.05 }}
                className={`p-4 rounded-lg border ${getTrendColor(stock.trend)}`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="text-2xl">{stock.trend_emoji}</span>
                    <div>
                      <div className="font-bold text-lg">{stock.symbol}</div>
                      <div className="text-xs text-muted-foreground">{stock.name}</div>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="font-mono text-lg">
                      LKR {stock.predicted_price?.toFixed(2) || '---'}
                    </div>
                    <div className={`text-sm font-mono ${stock.expected_change_pct >= 0 ? 'text-success' : 'text-destructive'}`}>
                      {stock.expected_change_pct >= 0 ? '+' : ''}{stock.expected_change_pct?.toFixed(2) || '0.00'}%
                    </div>
                  </div>
                </div>
                <div className="flex items-center justify-between mt-2 text-xs">
                  <span className="text-muted-foreground">{stock.sector}</span>
                  <span className="text-muted-foreground">
                    {Math.round(stock.confidence * 100)}% confidence
                  </span>
                </div>
              </motion.div>
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <AlertCircle className="w-12 h-12 text-muted-foreground mb-4" />
            <p className="text-muted-foreground">No predictions available</p>
          </div>
        )}

        {/* Timestamp and Disclaimer */}
        {predictions && (
          <div className="mt-4 text-xs text-muted-foreground flex justify-between">
            <span>Prediction for: {predictions.prediction_date}</span>
            <span>Generated: {formatTime(predictions.generated_at)}</span>
          </div>
        )}

        <div className="mt-4 p-3 bg-muted/20 rounded border border-border">
          <p className="text-xs text-muted-foreground font-mono">
            <span className="text-warning font-bold">⚠ DISCLAIMER:</span> AI-generated predictions using BiLSTM models. Not financial advice.
          </p>
        </div>
      </Card>

      {/* Live Market Events (from WebSocket) */}
      <Card className="p-6 bg-card border-border">
        <div className="flex items-center gap-2 mb-4">
          <Activity className="w-5 h-5 text-primary" />
          <h3 className="font-bold">LIVE MARKET EVENTS</h3>
          <div className={`ml-auto w-2 h-2 rounded-full ${isConnected ? 'bg-success animate-pulse' : 'bg-destructive'}`} />
        </div>

        {marketEvents.length > 0 ? (
          <div className="space-y-2 max-h-[200px] overflow-y-auto intel-scrollbar pr-2">
            {marketEvents.slice(0, 5).map((event, idx) => (
              <motion.div
                key={event.event_id || idx}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="p-3 rounded-lg bg-muted/20 border border-border"
              >
                <p className="text-sm">{event.summary}</p>
                <div className="flex justify-between mt-2 text-xs text-muted-foreground">
                  <span>{event.domain}</span>
                  <span>{new Date(event.timestamp).toLocaleTimeString()}</span>
                </div>
              </motion.div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Waiting for market events from AI agents...
          </p>
        )}
      </Card>
    </div>
  );
};

export default StockPredictions;

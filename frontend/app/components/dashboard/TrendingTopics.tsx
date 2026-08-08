/**
 * TrendingTopics.tsx
 * Dashboard component for displaying trending topics and spike alerts
 */

import React, { useEffect, useState } from 'react';
import { Flame, TrendingUp, AlertTriangle } from 'lucide-react';
import { API_BASE, apiFetch } from "@/app/lib/api";

interface RelatedFeed {
    summary: string;
    domain: string;
    timestamp: string;
    source: string;
}

interface TrendingTopic {
    topic: string;
    momentum: number;
    is_spike: boolean;
    count_current_hour?: number;
    avg_count?: number;
    related_feeds?: RelatedFeed[];
}

interface TrendingData {
    status: string;
    trending_topics: TrendingTopic[];
    spike_alerts: TrendingTopic[];
    total_trending: number;
    total_spikes: number;
}

export const TrendingTopics: React.FC = () => {
    const [data, setData] = useState<TrendingData | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);


    useEffect(() => {
        const fetchTrending = async () => {
            try {
                const response = await apiFetch(`${API_BASE}/api/trending`);
                const result = await response.json();

                // Validate the shape before storing it.
                //
                // This used to be a bare `setData(result)`, and the render then
                // read `data.spike_alerts.length` and `data.trending_topics.length`
                // unguarded. Any 200 response whose body was not the expected
                // object -- notably `{status: "unavailable"}`, which this backend
                // genuinely returns for capabilities that are not running --
                // threw during render and, with no error boundary above it, took
                // the ENTIRE dashboard down to Next's white "Application error"
                // page. Reproduced in a production build.
                if (
                    !result ||
                    !Array.isArray(result.trending_topics) ||
                    !Array.isArray(result.spike_alerts)
                ) {
                    setData(null);
                    setError('Trending data is unavailable');
                    return;
                }

                setData(result);
                setError(null);
            } catch (err) {
                setError('Failed to fetch trending data');
                console.error('Trending fetch error:', err);
            } finally {
                setLoading(false);
            }
        };

        fetchTrending();
        const interval = setInterval(fetchTrending, 30000);
        return () => clearInterval(interval);
    }, []);

    const getMomentumColor = (momentum: number) => {
        if (momentum >= 10) return 'text-destructive';
        if (momentum >= 5) return 'text-severity-high';
        if (momentum >= 2) return 'text-severity-medium';
        return 'text-foreground';
    };

    const getMomentumBg = (momentum: number) => {
        if (momentum >= 10) return 'bg-destructive/20';
        if (momentum >= 5) return 'bg-severity-high/20';
        if (momentum >= 2) return 'bg-severity-medium/20';
        return 'bg-muted';
    };

    if (loading) {
        return (
            <div className="bg-card rounded-lg p-6 border border-border">
                <div className="flex items-center gap-3 mb-4">
                    <div className="w-10 h-10 rounded-lg bg-primary/20 flex items-center justify-center">
                        <TrendingUp className="w-5 h-5 text-primary animate-pulse" aria-hidden="true" />
                    </div>
                    <div>
                        <h3 className="text-lg font-bold text-foreground">Trending Topics</h3>
                        <p className="text-xs text-muted-foreground">Loading...</p>
                    </div>
                </div>
                <div className="animate-pulse space-y-3">
                    {[1, 2, 3].map((i) => (
                        <div key={i} className="h-10 bg-muted rounded-lg"></div>
                    ))}
                </div>
            </div>
        );
    }

    if (error || !data) {
        return (
            <div className="bg-card rounded-lg p-6 border border-destructive/50">
                <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-destructive/20 flex items-center justify-center">
                        <AlertTriangle className="w-5 h-5 text-destructive" aria-hidden="true" />
                    </div>
                    <div>
                        <h3 className="text-lg font-bold text-foreground">Trending Topics</h3>
                        <p className="text-xs text-destructive">{error || 'No data available'}</p>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="bg-card rounded-lg p-6 border border-border">
            {/* Header */}
            <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-primary/20 flex items-center justify-center">
                        <TrendingUp className="w-5 h-5 text-primary" aria-hidden="true" />
                    </div>
                    <div>
                        <h3 className="text-lg font-bold text-foreground">Trending Topics</h3>
                        <p className="text-xs text-muted-foreground">{data.total_trending} trending • {data.total_spikes} spikes</p>
                    </div>
                </div>
                {data.total_spikes > 0 && (
                    <span className="px-2 py-1 bg-destructive/20 text-destructive text-xs font-medium rounded-lg animate-pulse">
                        <Flame className="w-3 h-3 inline mr-1" aria-hidden="true" />{data.total_spikes} SPIKE{data.total_spikes > 1 ? 'S' : ''}
                    </span>
                )}
            </div>

            {/* Spike Alerts */}
            {data.spike_alerts.length > 0 && (
                <div className="mb-4 p-3 bg-destructive/10 rounded-xl border border-destructive/50">
                    <h4 className="text-sm font-semibold text-destructive mb-2 flex items-center gap-2">
                        <Flame className="w-4 h-4" aria-hidden="true" /> SPIKE ALERTS
                    </h4>
                    <div className="flex flex-wrap gap-2">
                        {data.spike_alerts.slice(0, 5).map((spike, idx) => (
                            <span
                                key={idx}
                                className="px-3 py-1 bg-destructive/20 text-destructive text-sm font-medium rounded-full border border-destructive/50"
                            >
                                {spike.topic} <span className="text-destructive font-bold">{spike.momentum.toFixed(0)}x</span>
                            </span>
                        ))}
                    </div>
                </div>
            )}

            {/* Trending Topics List */}
            <div className="space-y-2">
                {data.trending_topics.length === 0 ? (
                    <div className="text-center py-8 text-muted-foreground">
                        <TrendingUp className="w-12 h-12 mx-auto mb-2 opacity-50" aria-hidden="true" />
                        <p>No trending topics yet</p>
                        <p className="text-xs mt-1">Topics will appear as data flows in</p>
                    </div>
                ) : (
                    data.trending_topics.slice(0, 8).map((topic, idx) => (
                        <div
                            key={idx}
                            className={`flex flex-col p-3 rounded-xl ${getMomentumBg(topic.momentum)} border border-border transition-all hover:scale-[1.02]`}
                        >
                            <div className="flex items-center justify-between w-full">
                                <div className="flex items-center gap-3">
                                    <span className="text-lg font-bold text-muted-foreground">#{idx + 1}</span>
                                    <div>
                                        <p className="font-semibold text-foreground capitalize">{topic.topic}</p>
                                        <p className="text-xs text-muted-foreground">
                                            {topic.is_spike ? 'Spiking' : 'Trending'}
                                        </p>
                                    </div>
                                </div>
                                <div className="text-right">
                                    <p className={`text-lg font-bold ${getMomentumColor(topic.momentum)}`}>
                                        {topic.momentum.toFixed(0)}x
                                    </p>
                                    <p className="text-xs text-muted-foreground">momentum</p>
                                </div>
                            </div>

                            {/* Related Feeds Context */}
                            {topic.related_feeds && topic.related_feeds.length > 0 && (
                                <div className="mt-3 pl-3 border-l-2 border-border space-y-2">
                                    {topic.related_feeds.map((feed, fIdx) => (
                                        <div key={fIdx} className="text-xs text-foreground/80 leading-relaxed">
                                            <span className="text-muted-foreground font-medium text-xs uppercase tracking-wider mr-2">[{feed.domain}]</span>
                                            {feed.summary.length > 100 ? feed.summary.substring(0, 100) + '...' : feed.summary}
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    ))
                )}
            </div>

            {/* Footer */}
            <div className="mt-4 pt-4 border-t border-border">
                <p className="text-xs text-muted-foreground text-center">
                    Momentum = current hour mentions / avg last 6 hours
                </p>
            </div>
        </div>
    );
};

export default TrendingTopics;

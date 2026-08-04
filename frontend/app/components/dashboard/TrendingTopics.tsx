/**
 * TrendingTopics.tsx
 * Dashboard component for displaying trending topics and spike alerts
 */

import React, { useEffect, useState } from 'react';

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

    const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

    useEffect(() => {
        const fetchTrending = async () => {
            try {
                const response = await fetch(`${API_BASE}/api/trending`);
                const result = await response.json();
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
        if (momentum >= 10) return 'text-red-500';
        if (momentum >= 5) return 'text-orange-500';
        if (momentum >= 2) return 'text-yellow-500';
        return 'text-gray-400';
    };

    const getMomentumBg = (momentum: number) => {
        if (momentum >= 10) return 'bg-red-500/20';
        if (momentum >= 5) return 'bg-orange-500/20';
        if (momentum >= 2) return 'bg-yellow-500/20';
        return 'bg-gray-500/10';
    };

    if (loading) {
        return (
            <div className="bg-gradient-to-br from-gray-900/90 to-gray-800/90 backdrop-blur-lg rounded-2xl p-6 border border-gray-700/50 shadow-xl">
                <div className="flex items-center gap-3 mb-4">
                    <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center">
                        <svg className="w-5 h-5 text-white animate-pulse" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
                        </svg>
                    </div>
                    <div>
                        <h3 className="text-lg font-bold text-white">Trending Topics</h3>
                        <p className="text-xs text-gray-400">Loading...</p>
                    </div>
                </div>
                <div className="animate-pulse space-y-3">
                    {[1, 2, 3].map((i) => (
                        <div key={i} className="h-10 bg-gray-700/50 rounded-lg"></div>
                    ))}
                </div>
            </div>
        );
    }

    if (error || !data) {
        return (
            <div className="bg-gradient-to-br from-gray-900/90 to-gray-800/90 backdrop-blur-lg rounded-2xl p-6 border border-red-700/50 shadow-xl">
                <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-red-500/20 flex items-center justify-center">
                        <svg className="w-5 h-5 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                        </svg>
                    </div>
                    <div>
                        <h3 className="text-lg font-bold text-white">Trending Topics</h3>
                        <p className="text-xs text-red-400">{error || 'No data available'}</p>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="bg-gradient-to-br from-gray-900/90 to-gray-800/90 backdrop-blur-lg rounded-2xl p-6 border border-gray-700/50 shadow-xl">
            {/* Header */}
            <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center">
                        <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
                        </svg>
                    </div>
                    <div>
                        <h3 className="text-lg font-bold text-white">Trending Topics</h3>
                        <p className="text-xs text-gray-400">{data.total_trending} trending • {data.total_spikes} spikes</p>
                    </div>
                </div>
                {data.total_spikes > 0 && (
                    <span className="px-2 py-1 bg-red-500/20 text-red-400 text-xs font-medium rounded-lg animate-pulse">
                        🔥 {data.total_spikes} SPIKE{data.total_spikes > 1 ? 'S' : ''}
                    </span>
                )}
            </div>

            {/* Spike Alerts */}
            {data.spike_alerts.length > 0 && (
                <div className="mb-4 p-3 bg-red-500/10 rounded-xl border border-red-500/30">
                    <h4 className="text-sm font-semibold text-red-400 mb-2 flex items-center gap-2">
                        <span>🔥</span> SPIKE ALERTS
                    </h4>
                    <div className="flex flex-wrap gap-2">
                        {data.spike_alerts.slice(0, 5).map((spike, idx) => (
                            <span
                                key={idx}
                                className="px-3 py-1 bg-red-500/20 text-red-300 text-sm font-medium rounded-full border border-red-500/30"
                            >
                                {spike.topic} <span className="text-red-400 font-bold">{spike.momentum.toFixed(0)}x</span>
                            </span>
                        ))}
                    </div>
                </div>
            )}

            {/* Trending Topics List */}
            <div className="space-y-2">
                {data.trending_topics.length === 0 ? (
                    <div className="text-center py-8 text-gray-500">
                        <svg className="w-12 h-12 mx-auto mb-2 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
                        </svg>
                        <p>No trending topics yet</p>
                        <p className="text-xs mt-1">Topics will appear as data flows in</p>
                    </div>
                ) : (
                    data.trending_topics.slice(0, 8).map((topic, idx) => (
                        <div
                            key={idx}
                            className={`flex flex-col p-3 rounded-xl ${getMomentumBg(topic.momentum)} border border-gray-700/30 transition-all hover:scale-[1.02]`}
                        >
                            <div className="flex items-center justify-between w-full">
                                <div className="flex items-center gap-3">
                                    <span className="text-lg font-bold text-gray-500">#{idx + 1}</span>
                                    <div>
                                        <p className="font-semibold text-white capitalize">{topic.topic}</p>
                                        <p className="text-xs text-gray-400">
                                            {topic.is_spike ? '🔥 Spiking' : 'Trending'}
                                        </p>
                                    </div>
                                </div>
                                <div className="text-right">
                                    <p className={`text-lg font-bold ${getMomentumColor(topic.momentum)}`}>
                                        {topic.momentum.toFixed(0)}x
                                    </p>
                                    <p className="text-xs text-gray-500">momentum</p>
                                </div>
                            </div>

                            {/* Related Feeds Context */}
                            {topic.related_feeds && topic.related_feeds.length > 0 && (
                                <div className="mt-3 pl-3 border-l-2 border-gray-600/30 space-y-2">
                                    {topic.related_feeds.map((feed, fIdx) => (
                                        <div key={fIdx} className="text-xs text-gray-300/80 leading-relaxed">
                                            <span className="text-gray-500 font-medium text-[10px] uppercase tracking-wider mr-2">[{feed.domain}]</span>
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
            <div className="mt-4 pt-4 border-t border-gray-700/50">
                <p className="text-xs text-gray-500 text-center">
                    Momentum = current hour mentions / avg last 6 hours
                </p>
            </div>
        </div>
    );
};

export default TrendingTopics;

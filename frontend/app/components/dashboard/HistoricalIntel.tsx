'use client';

import { useState, useEffect } from 'react';
import { Card } from '../ui/card';
import { Badge } from '../ui/badge';
import { History, TrendingUp, CloudRain, AlertTriangle, Calendar, Droplets } from 'lucide-react';
import { motion } from 'framer-motion';

interface HistoricalData {
    source: string;
    period: string;
    fetched_at: string;
    statistics: {
        avg_annual_rainfall_mm: number;
        max_daily_rainfall_mm: number;
        heavy_rain_days_50mm: number;
        extreme_rain_days_100mm: number;
        avg_flood_events_per_year: number;
    };
    decadal_analysis: {
        period: string;
        avg_rainfall_mm: number;
        extreme_days: number;
        max_daily_mm: number;
        major_flood_events: number;
    }[];
    key_findings: string[];
    high_risk_periods: {
        months: string;
        type: string;
        risk: string;
    }[];
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function HistoricalIntel() {
    const [data, setData] = useState<HistoricalData | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchData = async () => {
            try {
                const res = await fetch(`${API_BASE}/api/weather/historical`);
                const result = await res.json();
                if (result.status === 'success') {
                    setData(result.data);
                } else {
                    setError(result.error || 'Failed to load data');
                }
            } catch (err) {
                setError('Failed to connect to API');
            } finally {
                setLoading(false);
            }
        };
        fetchData();
    }, []);

    if (loading) {
        return (
            <Card className="p-6 bg-card border-border">
                <div className="flex items-center gap-3 mb-4">
                    <History className="w-6 h-6 text-info animate-pulse" />
                    <h3 className="font-bold">Loading Historical Data...</h3>
                </div>
            </Card>
        );
    }

    if (error || !data) {
        return (
            <Card className="p-6 bg-card border-border">
                <div className="flex items-center gap-3 mb-4">
                    <AlertTriangle className="w-6 h-6 text-warning" />
                    <h3 className="font-bold">Historical Data Unavailable</h3>
                </div>
                <p className="text-sm text-muted-foreground">{error}</p>
            </Card>
        );
    }

    const stats = data.statistics;

    return (
        <div className="space-y-4">
            {/* Header */}
            <Card className="p-4 sm:p-6 bg-card border-border">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
                    <div className="flex items-center gap-3">
                        <div className="p-2 rounded-lg bg-info/20">
                            <History className="w-5 h-5 text-info" />
                        </div>
                        <div>
                            <h3 className="font-bold text-base sm:text-lg">Historical Flood Pattern Analysis</h3>
                            <p className="text-xs text-muted-foreground">{data.period}</p>
                        </div>
                    </div>
                    <Badge className="bg-info/20 text-info w-fit">
                        <Calendar className="w-3 h-3 mr-1" />
                        30-Year Data
                    </Badge>
                </div>

                {/* Quick Stats */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 sm:gap-4">
                    <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.1 }}
                        className="p-3 sm:p-4 bg-muted/30 rounded-lg"
                    >
                        <div className="flex items-center gap-2 mb-1">
                            <Droplets className="w-4 h-4 text-info" />
                            <span className="text-xs text-muted-foreground">Avg Annual</span>
                        </div>
                        <p className="text-lg sm:text-xl font-bold">{stats.avg_annual_rainfall_mm}</p>
                        <p className="text-xs text-muted-foreground">mm rainfall</p>
                    </motion.div>

                    <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.2 }}
                        className="p-3 sm:p-4 bg-muted/30 rounded-lg"
                    >
                        <div className="flex items-center gap-2 mb-1">
                            <CloudRain className="w-4 h-4 text-warning" />
                            <span className="text-xs text-muted-foreground">Max Daily</span>
                        </div>
                        <p className="text-lg sm:text-xl font-bold">{stats.max_daily_rainfall_mm}</p>
                        <p className="text-xs text-muted-foreground">mm recorded</p>
                    </motion.div>

                    <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.3 }}
                        className="p-3 sm:p-4 bg-muted/30 rounded-lg"
                    >
                        <div className="flex items-center gap-2 mb-1">
                            <TrendingUp className="w-4 h-4 text-success" />
                            <span className="text-xs text-muted-foreground">Heavy Days</span>
                        </div>
                        <p className="text-lg sm:text-xl font-bold">{stats.heavy_rain_days_50mm}</p>
                        <p className="text-xs text-muted-foreground">&gt;50mm days</p>
                    </motion.div>

                    <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.4 }}
                        className="p-3 sm:p-4 bg-destructive/10 rounded-lg"
                    >
                        <div className="flex items-center gap-2 mb-1">
                            <AlertTriangle className="w-4 h-4 text-destructive" />
                            <span className="text-xs text-muted-foreground">Extreme</span>
                        </div>
                        <p className="text-lg sm:text-xl font-bold">{stats.extreme_rain_days_100mm}</p>
                        <p className="text-xs text-muted-foreground">&gt;100mm days</p>
                    </motion.div>
                </div>
            </Card>

            {/* Climate Change Comparison */}
            <Card className="p-4 sm:p-6 bg-card border-border">
                <h4 className="font-bold mb-4 flex items-center gap-2">
                    <TrendingUp className="w-5 h-5 text-warning" />
                    How Climate Has Changed
                </h4>

                <div className="overflow-x-auto intel-scrollbar">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="border-b border-border">
                                <th className="text-left py-2 px-2 text-muted-foreground font-medium">Period</th>
                                <th className="text-right py-2 px-2 text-muted-foreground font-medium">Avg Rainfall</th>
                                <th className="text-right py-2 px-2 text-muted-foreground font-medium">Extreme Days</th>
                                <th className="text-right py-2 px-2 text-muted-foreground font-medium">Max Daily</th>
                            </tr>
                        </thead>
                        <tbody>
                            {data.decadal_analysis.map((decade, idx) => (
                                <motion.tr
                                    key={decade.period}
                                    initial={{ opacity: 0, x: -10 }}
                                    animate={{ opacity: 1, x: 0 }}
                                    transition={{ delay: 0.1 * idx }}
                                    className="border-b border-border/50 hover:bg-muted/30"
                                >
                                    <td className="py-3 px-2 font-medium">{decade.period}</td>
                                    <td className="py-3 px-2 text-right">{decade.avg_rainfall_mm} mm</td>
                                    <td className="py-3 px-2 text-right">
                                        <Badge className={idx === 2 ? 'bg-destructive/20 text-destructive' : 'bg-muted'}>
                                            {decade.extreme_days}
                                        </Badge>
                                    </td>
                                    <td className="py-3 px-2 text-right">{decade.max_daily_mm} mm</td>
                                </motion.tr>
                            ))}
                        </tbody>
                    </table>
                </div>

                {/* Key Findings */}
                <div className="mt-4 p-3 bg-warning/10 border border-warning/30 rounded-lg">
                    <p className="text-sm font-medium text-warning mb-2">📊 Key Finding</p>
                    <p className="text-sm">{data.key_findings[0]}</p>
                </div>
            </Card>

            {/* High Risk Periods */}
            <Card className="p-4 sm:p-6 bg-card border-border">
                <h4 className="font-bold mb-4 flex items-center gap-2">
                    <Calendar className="w-5 h-5 text-primary" />
                    High Risk Periods
                </h4>
                <div className="flex flex-wrap gap-2">
                    {data.high_risk_periods.map((period, idx) => (
                        <Badge
                            key={idx}
                            className={`${period.risk === 'high'
                                ? 'bg-destructive/20 text-destructive'
                                : 'bg-warning/20 text-warning'
                                }`}
                        >
                            {period.months}: {period.type}
                        </Badge>
                    ))}
                </div>
            </Card>
        </div>
    );
}

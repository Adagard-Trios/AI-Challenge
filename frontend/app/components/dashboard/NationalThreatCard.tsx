'use client';

import { useState, useEffect } from 'react';
import { Card } from '../ui/card';
import { Badge } from '../ui/badge';
import { Shield, AlertTriangle, TrendingUp, CloudRain, Waves, Activity } from 'lucide-react';
import { motion } from 'framer-motion';

interface ThreatData {
    status: string;
    national_threat_score: number;
    threat_level: string;
    color: string;
    breakdown: {
        river_contribution: number;
        alert_contribution: number;
        seasonal_contribution: number;
    };
    risk_summary: {
        critical_count: number;
        high_count: number;
        medium_count: number;
        critical_districts: string[];
        high_risk_districts: string[];
        medium_risk_districts: string[];
    };
    calculated_at: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function NationalThreatCard() {
    const [data, setData] = useState<ThreatData | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchData = async () => {
        try {
            const res = await fetch(`${API_BASE}/api/weather/threat`);
            const result = await res.json();
            if (result.status === 'success') {
                setData(result);
                setError(null);
            } else {
                setError(result.error || 'Failed to load data');
            }
        } catch (err) {
            setError('Failed to connect to API');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchData();
        // Refresh every 5 minutes
        const interval = setInterval(fetchData, 5 * 60 * 1000);
        return () => clearInterval(interval);
    }, []);

    const getThreatConfig = (level: string) => {
        switch (level) {
            case 'CRITICAL':
                return {
                    bgColor: 'bg-destructive/20',
                    borderColor: 'border-destructive',
                    textColor: 'text-destructive',
                    icon: AlertTriangle,
                    gradient: 'from-destructive to-red-700',
                    pulse: true
                };
            case 'HIGH':
                return {
                    bgColor: 'bg-warning/20',
                    borderColor: 'border-warning',
                    textColor: 'text-warning',
                    icon: TrendingUp,
                    gradient: 'from-warning to-orange-600',
                    pulse: true
                };
            case 'MODERATE':
                return {
                    bgColor: 'bg-yellow-500/20',
                    borderColor: 'border-yellow-500',
                    textColor: 'text-yellow-500',
                    icon: Activity,
                    gradient: 'from-yellow-500 to-amber-600',
                    pulse: false
                };
            default:
                return {
                    bgColor: 'bg-success/20',
                    borderColor: 'border-success',
                    textColor: 'text-success',
                    icon: Shield,
                    gradient: 'from-success to-green-600',
                    pulse: false
                };
        }
    };

    if (loading) {
        return (
            <Card className="p-6 bg-card border-border">
                <div className="flex items-center gap-3">
                    <Shield className="w-6 h-6 text-muted-foreground animate-pulse" />
                    <span className="text-muted-foreground">Calculating threat level...</span>
                </div>
            </Card>
        );
    }

    if (error || !data) {
        return (
            <Card className="p-6 bg-card border-border">
                <div className="flex items-center gap-3">
                    <AlertTriangle className="w-6 h-6 text-warning" />
                    <span className="text-warning">Threat assessment unavailable</span>
                </div>
            </Card>
        );
    }

    const config = getThreatConfig(data.threat_level);
    const ThreatIcon = config.icon;
    const { breakdown, risk_summary } = data;

    return (
        <Card className={`p-4 sm:p-6 ${config.bgColor} border-l-4 ${config.borderColor}`}>
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                {/* Left: Threat Score */}
                <div className="flex items-center gap-4">
                    <motion.div
                        initial={{ scale: 0.8, opacity: 0 }}
                        animate={{ scale: 1, opacity: 1 }}
                        className={`relative p-3 sm:p-4 rounded-full bg-gradient-to-br ${config.gradient}`}
                    >
                        <ThreatIcon className="w-6 h-6 sm:w-8 sm:h-8 text-white" />
                        {config.pulse && (
                            <span className="absolute inset-0 rounded-full animate-ping bg-current opacity-20" />
                        )}
                    </motion.div>

                    <div>
                        <p className="text-xs sm:text-sm text-muted-foreground uppercase tracking-wide">National Threat</p>
                        <div className="flex items-baseline gap-2">
                            <motion.span
                                initial={{ opacity: 0, y: 10 }}
                                animate={{ opacity: 1, y: 0 }}
                                className="text-3xl sm:text-4xl font-bold"
                            >
                                {data.national_threat_score}
                            </motion.span>
                            <span className="text-lg text-muted-foreground">/100</span>
                        </div>
                        <Badge className={`${config.bgColor} ${config.textColor} mt-1`}>
                            {data.threat_level}
                        </Badge>
                    </div>
                </div>

                {/* Right: Breakdown */}
                <div className="grid grid-cols-3 gap-2 sm:gap-4 text-center">
                    <div className="p-2 sm:p-3 bg-background/50 rounded-lg">
                        <Waves className="w-4 h-4 mx-auto mb-1 text-info" />
                        <p className="text-xs text-muted-foreground">Rivers</p>
                        <p className="font-bold">{breakdown.river_contribution}</p>
                    </div>
                    <div className="p-2 sm:p-3 bg-background/50 rounded-lg">
                        <AlertTriangle className="w-4 h-4 mx-auto mb-1 text-warning" />
                        <p className="text-xs text-muted-foreground">Alerts</p>
                        <p className="font-bold">{breakdown.alert_contribution}</p>
                    </div>
                    <div className="p-2 sm:p-3 bg-background/50 rounded-lg">
                        <CloudRain className="w-4 h-4 mx-auto mb-1 text-primary" />
                        <p className="text-xs text-muted-foreground">Season</p>
                        <p className="font-bold">{breakdown.seasonal_contribution}</p>
                    </div>
                </div>
            </div>

            {/* Risk Districts */}
            {(risk_summary.critical_count > 0 || risk_summary.high_count > 0) && (
                <div className="mt-4 pt-4 border-t border-border/50">
                    <p className="text-xs text-muted-foreground mb-2">At-Risk Districts</p>
                    <div className="flex flex-wrap gap-2">
                        {risk_summary.critical_districts.map((d) => (
                            <Badge key={d} className="bg-destructive/20 text-destructive text-xs">
                                {d}
                            </Badge>
                        ))}
                        {risk_summary.high_risk_districts.map((d) => (
                            <Badge key={d} className="bg-warning/20 text-warning text-xs">
                                {d}
                            </Badge>
                        ))}
                    </div>
                </div>
            )}
        </Card>
    );
}

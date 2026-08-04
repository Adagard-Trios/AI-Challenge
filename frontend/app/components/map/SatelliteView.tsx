'use client';

import { useState } from 'react';
import { Card } from '../ui/card';
import { Badge } from '../ui/badge';
import { Satellite, Cloud, Wind, Thermometer, Droplets, Gauge, Waves, ExternalLink, RefreshCw, Maximize2 } from 'lucide-react';

type LayerType = 'wind' | 'rain' | 'temp' | 'clouds' | 'waves' | 'pressure';

interface LayerConfig {
    id: LayerType;
    label: string;
    icon: React.ComponentType<{ className?: string }>;
    overlay: string;  // Windy overlay parameter
    description: string;
}

const LAYERS: LayerConfig[] = [
    {
        id: 'wind',
        label: 'Wind',
        icon: Wind,
        overlay: 'wind',
        description: 'Wind speed and direction'
    },
    {
        id: 'rain',
        label: 'Rain',
        icon: Cloud,
        overlay: 'rain',
        description: 'Precipitation forecast'
    },
    {
        id: 'temp',
        label: 'Temperature',
        icon: Thermometer,
        overlay: 'temp',
        description: 'Air temperature'
    },
    {
        id: 'clouds',
        label: 'Clouds',
        icon: Satellite,
        overlay: 'clouds',
        description: 'Cloud cover'
    },
    {
        id: 'waves',
        label: 'Waves',
        icon: Waves,
        overlay: 'waves',
        description: 'Ocean wave height'
    },
    {
        id: 'pressure',
        label: 'Pressure',
        icon: Gauge,
        overlay: 'pressure',
        description: 'Atmospheric pressure'
    }
];

// Sri Lanka coordinates
const SRI_LANKA = {
    lat: 7.87,
    lon: 80.77,
    zoom: 7
};

export default function SatelliteView() {
    const [activeLayer, setActiveLayer] = useState<LayerType>('wind');
    const [isFullscreen, setIsFullscreen] = useState(false);
    const [key, setKey] = useState(0);

    const activeConfig = LAYERS.find(l => l.id === activeLayer) || LAYERS[0];

    // Windy.com embed URL - officially supported!
    const iframeSrc = `https://embed.windy.com/embed.html?type=map&location=coordinates&metricRain=mm&metricTemp=°C&metricWind=km/h&zoom=${SRI_LANKA.zoom}&overlay=${activeConfig.overlay}&product=ecmwf&level=surface&lat=${SRI_LANKA.lat}&lon=${SRI_LANKA.lon}&detailLat=${SRI_LANKA.lat}&detailLon=${SRI_LANKA.lon}&marker=true&message=true`;

    const handleRefresh = () => {
        setKey(prev => prev + 1);
    };

    const handleFullscreen = () => {
        setIsFullscreen(!isFullscreen);
    };

    const handleOpenExternal = () => {
        window.open(`https://www.windy.com/?${SRI_LANKA.lat},${SRI_LANKA.lon},${SRI_LANKA.zoom}`, '_blank');
    };

    return (
        <div className={`space-y-4 ${isFullscreen ? 'fixed inset-0 z-50 bg-background p-4' : ''}`}>
            {/* Header */}
            <Card className="p-4 bg-card border-border">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                    <div className="flex items-center gap-3">
                        <div className="p-2 rounded-lg bg-primary/20">
                            <Satellite className="w-5 h-5 text-primary" />
                        </div>
                        <div>
                            <h2 className="font-bold text-lg">Live Weather Map</h2>
                            <p className="text-xs text-muted-foreground">
                                Powered by Windy.com • ECMWF Model • Real-time data
                            </p>
                        </div>
                    </div>

                    <div className="flex items-center gap-2">
                        <button
                            onClick={handleRefresh}
                            className="p-2 rounded-lg bg-muted hover:bg-muted/80 transition-colors"
                            title="Refresh"
                        >
                            <RefreshCw className="w-4 h-4" />
                        </button>
                        <button
                            onClick={handleFullscreen}
                            className="p-2 rounded-lg bg-muted hover:bg-muted/80 transition-colors"
                            title={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
                        >
                            <Maximize2 className="w-4 h-4" />
                        </button>
                        <button
                            onClick={handleOpenExternal}
                            className="p-2 rounded-lg bg-muted hover:bg-muted/80 transition-colors"
                            title="Open in Windy.com"
                        >
                            <ExternalLink className="w-4 h-4" />
                        </button>
                    </div>
                </div>

                {/* Layer Selector */}
                <div className="mt-4 flex flex-wrap gap-2">
                    {LAYERS.map((layer) => {
                        const Icon = layer.icon;
                        const isActive = activeLayer === layer.id;
                        return (
                            <button
                                key={layer.id}
                                onClick={() => setActiveLayer(layer.id)}
                                className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-all ${isActive
                                        ? 'bg-primary text-primary-foreground'
                                        : 'bg-muted hover:bg-muted/80 text-muted-foreground'
                                    }`}
                                title={layer.description}
                            >
                                <Icon className="w-4 h-4" />
                                <span className="hidden sm:inline">{layer.label}</span>
                            </button>
                        );
                    })}
                </div>

                {/* Active Layer Info */}
                <div className="mt-3 flex items-center gap-2">
                    <Badge className="bg-primary/20 text-primary">
                        {activeConfig.label}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                        {activeConfig.description}
                    </span>
                </div>
            </Card>

            {/* Map Container */}
            <Card className={`overflow-hidden bg-card border-border ${isFullscreen ? 'flex-1' : ''}`}>
                <div className={`relative ${isFullscreen ? 'h-[calc(100vh-200px)]' : 'h-[500px] sm:h-[600px]'}`}>
                    <iframe
                        key={key}
                        src={iframeSrc}
                        className="w-full h-full border-0"
                        title="Windy Weather Map - Sri Lanka"
                        loading="lazy"
                        allowFullScreen
                    />
                </div>
            </Card>

            {/* Data Attribution */}
            <div className="text-xs text-muted-foreground text-center">
                Data: ECMWF • GFS • ICON • NAM Models
                <span className="mx-2">•</span>
                Powered by{' '}
                <a
                    href="https://www.windy.com"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary hover:underline"
                >
                    Windy.com
                </a>
            </div>
        </div>
    );
}

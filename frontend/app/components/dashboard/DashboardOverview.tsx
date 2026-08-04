import { Card } from "../ui/card";
import { AlertTriangle, TrendingUp, Cloud, Zap, Users, Building, Wifi, WifiOff, Waves } from "lucide-react";
import { Badge } from "../ui/badge";
import { useRogerData } from "../../hooks/use-roger-data";
import { motion } from "framer-motion";
import RiverNetStatus from "./RiverNetStatus";
import PowerOutageStatus from "./PowerOutageStatus";
import FuelPriceMonitor from "./FuelPriceMonitor";
import EconomicIndicators from "./EconomicIndicators";
import HealthAlerts from "./HealthAlerts";
import CommodityPrices from "./CommodityPrices";
import WaterSupplyStatus from "./WaterSupplyStatus";

const DashboardOverview = () => {
  // Get data from hook (fetched via various /api/ endpoints)
  const {
    dashboard,
    events,
    isConnected,
    status,
    riverData,
    powerData,
    fuelData,
    economyData,
    healthData,
    commodityData,
    waterData,
  } = useRogerData();

  // Safety check: ensure events is always an array
  const safeEvents = events || [];

  // Sort events by timestamp descending (latest first)
  const sortedEvents = [...safeEvents].sort((a, b) => {
    const dateA = new Date(a.timestamp).getTime();
    const dateB = new Date(b.timestamp).getTime();
    return dateB - dateA; // Descending order (newest first)
  });

  // Calculate domain-specific metrics from sorted events
  const domainCounts = sortedEvents.reduce((acc, event) => {
    acc[event.domain] = (acc[event.domain] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  const riskEvents = sortedEvents.filter(e => e.impact_type === 'risk');
  const opportunityEvents = sortedEvents.filter(e => e.impact_type === 'opportunity');
  const criticalEvents = sortedEvents.filter(e => e.severity === 'critical' || e.severity === 'high');

  // Count flood-related events
  const floodEvents = sortedEvents.filter(e =>
    e.category === 'flood_monitoring' ||
    e.category === 'flood_alert' ||
    (e.summary && e.summary.toLowerCase().includes('flood'))
  );

  const metrics = [
    {
      label: "Risk Events",
      value: riskEvents.length.toString(),
      change: criticalEvents.length > 0 ? `${criticalEvents.length} critical` : "—",
      icon: AlertTriangle,
      status: criticalEvents.length > 3 ? "warning" : "success"
    },
    {
      label: "Opportunities",
      value: opportunityEvents.length.toString(),
      change: "+Growth",
      icon: TrendingUp,
      status: "success"
    },
    {
      label: "Data Sources",
      value: Object.keys(domainCounts).length.toString(),
      change: "Active",
      icon: Zap,
      status: "info"
    },
    {
      label: "Flood Alerts",
      value: floodEvents.length.toString(),
      change: riverData ? "Monitoring" : "Offline",
      icon: Waves,
      status: floodEvents.length > 0 ? "warning" : "success"
    },
  ];

  return (
    <div className="space-y-6">
      {/* Connection Status Banner */}
      <Card className={`p-4 ${isConnected ? 'bg-success/10 border-success/50' : 'bg-warning/10 border-warning/50'}`}>
        <div className="flex items-center gap-3">
          {isConnected ? (
            <>
              <Wifi className="w-5 h-5 text-success" />
              <div className="flex-1">
                <h3 className="font-bold text-success">SYSTEM OPERATIONAL</h3>
                <p className="text-xs text-muted-foreground">Real-time intelligence streaming • Run #{dashboard.total_events}</p>
              </div>
            </>
          ) : (
            <>
              <WifiOff className="w-5 h-5 text-warning" />
              <div className="flex-1">
                <h3 className="font-bold text-warning">RECONNECTING...</h3>
                <p className="text-xs text-muted-foreground">Attempting to restore live feed</p>
              </div>
            </>
          )}
          <Badge className="font-mono text-xs">
            {new Date(dashboard.last_updated).toLocaleTimeString()}
          </Badge>
        </div>
      </Card>

      {/* Metrics Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {metrics.map((metric, idx) => {
          const Icon = metric.icon;
          return (
            <motion.div
              key={idx}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: idx * 0.1 }}
            >
              <Card className="p-4 bg-card border-border hover:border-primary/50 transition-all">
                <div className="flex items-start justify-between mb-2">
                  <div className={`p-2 rounded bg-${metric.status}/20`}>
                    <Icon className={`w-5 h-5 text-${metric.status}`} />
                  </div>
                  <span className="text-xs font-mono text-success">{metric.change}</span>
                </div>
                <div>
                  <p className="text-2xl font-bold">{metric.value}</p>
                  <p className="text-xs text-muted-foreground uppercase tracking-wide">{metric.label}</p>
                </div>
              </Card>
            </motion.div>
          );
        })}
      </div>

      {/* RiverNet Flood Monitoring */}
      <RiverNetStatus riverData={riverData} compact={false} />

      {/* Situational Awareness Grid - NEW */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <PowerOutageStatus powerData={powerData} />
        <FuelPriceMonitor fuelData={fuelData} />
        <EconomicIndicators economyData={economyData} />
        <HealthAlerts healthData={healthData} />
        <CommodityPrices commodityData={commodityData} />
        <WaterSupplyStatus waterData={waterData} />
      </div>



      {/* Live Intelligence Feed - SORTED BY LATEST FIRST */}
      <Card className="p-6 bg-card border-border">
        <h3 className="font-bold mb-4 flex items-center gap-2">
          <Zap className="w-5 h-5 text-primary" />
          LIVE INTELLIGENCE FEED
          <span className="text-xs text-muted-foreground ml-2">(Latest First)</span>
          <Badge className="ml-auto">{sortedEvents.length} Events</Badge>
        </h3>
        <div className="space-y-3 max-h-[500px] overflow-y-auto intel-scrollbar pr-2">
          {sortedEvents.slice(0, 10).map((event, idx) => {
            const isRisk = event.impact_type === 'risk';
            const isFlood = event.category === 'flood_monitoring' || event.category === 'flood_alert';
            const severityColor = {
              critical: 'destructive',
              high: 'warning',
              medium: 'primary',
              low: 'secondary'
            }[event.severity] || 'secondary';

            return (
              <motion.div
                key={event.event_id}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: idx * 0.05 }}
              >
                <Card className={`p-4 bg-muted/30 border-l-4 border-l-${severityColor} hover:bg-muted/50 transition-colors`}>
                  <div className="flex items-start justify-between mb-2">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1 flex-wrap">
                        <Badge className={`bg-${severityColor} text-${severityColor}-foreground`}>
                          {event.severity.toUpperCase()}
                        </Badge>
                        <Badge className={isRisk ? "bg-destructive/20 text-destructive" : "bg-success/20 text-success"}>
                          {isRisk ? "⚠️ RISK" : "✨ OPPORTUNITY"}
                        </Badge>
                        <Badge className="border border-border">{event.domain}</Badge>
                        {isFlood && (
                          <Badge className="bg-info/20 text-info">🌊 FLOOD</Badge>
                        )}
                      </div>
                      <p className="font-semibold text-sm mb-1">{event.summary}</p>
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <span>Confidence: {Math.round(event.confidence * 100)}%</span>
                        <span>•</span>
                        <span className="font-mono">{new Date(event.timestamp).toLocaleTimeString()}</span>
                        <span>•</span>
                        <span className="font-mono">{new Date(event.timestamp).toLocaleDateString()}</span>
                      </div>
                    </div>
                  </div>
                </Card>
              </motion.div>
            );
          })}
          {sortedEvents.length === 0 && (
            <div className="text-center text-muted-foreground py-8">
              <AlertTriangle className="w-12 h-12 mx-auto mb-3 opacity-50" />
              <p className="text-sm font-mono">Initializing intelligence gathering...</p>
            </div>
          )}
        </div>
      </Card>

      {/* Operational Risk Indicators - Computed from Events */}
      {sortedEvents.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <Card className="p-6 bg-card border-border">
            <Cloud className="w-8 h-8 text-warning mb-3" />
            <p className="text-2xl font-bold">
              {Math.min(100, Math.round(
                (sortedEvents.filter(e => e.domain === 'meteorological' || e.summary?.toLowerCase().includes('weather')).length / Math.max(sortedEvents.length, 1)) * 100 * 3
              ))}%
            </p>
            <p className="text-xs text-muted-foreground uppercase">Weather Impact</p>
          </Card>
          <Card className="p-6 bg-card border-border">
            <AlertTriangle className="w-8 h-8 text-destructive mb-3" />
            <p className="text-2xl font-bold">
              {Math.round((criticalEvents.length / Math.max(sortedEvents.length, 1)) * 100)}%
            </p>
            <p className="text-xs text-muted-foreground uppercase">Critical Risk Level</p>
          </Card>
          <Card className="p-6 bg-card border-border">
            <TrendingUp className="w-8 h-8 text-info mb-3" />
            <p className="text-2xl font-bold">
              {Math.min(100, Math.round(
                (sortedEvents.filter(e => e.domain === 'economical' || e.domain === 'market').length / Math.max(sortedEvents.length, 1)) * 100 * 3
              ))}%
            </p>
            <p className="text-xs text-muted-foreground uppercase">Market Activity</p>
          </Card>
          <Card className="p-6 bg-card border-border">
            <Building className="w-8 h-8 text-success mb-3" />
            <p className="text-2xl font-bold">
              {Math.round((opportunityEvents.length / Math.max(sortedEvents.length, 1)) * 100)}%
            </p>
            <p className="text-xs text-muted-foreground uppercase">Opportunity Index</p>
          </Card>
        </div>
      )}
    </div>
  );
};

export default DashboardOverview;

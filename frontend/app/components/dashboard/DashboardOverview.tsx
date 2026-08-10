import { Card } from "../ui/card";
import { AlertTriangle, TrendingUp, Zap, Wifi, WifiOff, Waves } from "lucide-react";
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
import { formatTime } from "@/app/lib/format";
import { severityStyle } from "@/app/lib/severity";
import { formatSummary } from "@/app/lib/summary";

const DashboardOverview = () => {
  // Get data from hook (fetched via various /api/ endpoints)
  const {
    dashboard,
    events,
    isConnected,
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

  // Tone -> literal class strings.
  //
  // These were built at runtime as `bg-${metric.status}/20` and
  // `text-${metric.status}`. Tailwind's scanner cannot see an interpolated
  // class name, so those only rendered because the same literals happened to
  // appear in other files -- delete an unrelated component that uses
  // `bg-info/20` and this card silently loses its colour, with no error
  // anywhere. Written out, they are scannable and cannot rot.
  const TONE = {
    success: { bg: "bg-success/20", fg: "text-success" },
    warning: { bg: "bg-warning/20", fg: "text-warning" },
    info: { bg: "bg-info/20", fg: "text-info" },
  } as const;

  const metrics: Array<{
    label: string;
    value: string;
    change: string;
    icon: typeof AlertTriangle;
    status: keyof typeof TONE;
  }> = [
    {
      label: "Risk Events",
      value: riskEvents.length.toString(),
      change: criticalEvents.length > 0 ? `${criticalEvents.length} critical` : "n/a",
      icon: AlertTriangle,
      status: criticalEvents.length > 3 ? "warning" : "success"
    },
    {
      label: "Opportunities",
      // "+Growth" used to sit here. It was a hardcoded string dressed as a
      // delta -- it never varied, and there is no previous cycle stored to
      // compute a real one against.
      value: opportunityEvents.length.toString(),
      change: opportunityEvents.length > 0 ? "this cycle" : "n/a",
      icon: TrendingUp,
      status: "success"
    },
    {
      // Labelled "Data Sources" while counting Object.keys(domainCounts) --
      // the number of DOMAINS present in the current feed, which is at most 6.
      // The platform has 25 sources, so the card read as "19 of your 25
      // sources are down". It is a domain count; say so.
      label: "Active Domains",
      value: Object.keys(domainCounts).length.toString(),
      change: `${sortedEvents.length} events`,
      icon: Zap,
      status: "info"
    },
    {
      label: "Flood Alerts",
      value: floodEvents.length.toString(),
      change: riverData ? "Monitoring" : "No river data",
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
                <h3 className="font-bold text-success">Live</h3>
                <p className="text-sm text-muted-foreground">Receiving updates as they arrive • {dashboard.total_events} events this cycle</p>
              </div>
            </>
          ) : (
            <>
              <WifiOff className="w-5 h-5 text-warning" />
              <div className="flex-1">
                <h3 className="font-bold text-warning">Reconnecting</h3>
                <p className="text-sm text-muted-foreground">Showing the last data received; retrying in the background</p>
              </div>
            </>
          )}
          <Badge className="font-mono text-xs">
            {formatTime(dashboard.last_updated)}
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
                  <div className={`p-2 rounded ${TONE[metric.status].bg}`}>
                    <Icon className={`w-5 h-5 ${TONE[metric.status].fg}`} />
                  </div>
                  {/* Was hardcoded text-success, which painted "No river data"
                      and "n/a" green as if they were good news. */}
                  <span className="text-xs font-mono text-muted-foreground">{metric.change}</span>
                </div>
                <div>
                  <p className="text-3xl font-bold tracking-tight">{metric.value}</p>
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
            // Shared warning ladder. The map this replaces also sent `medium`
            // to `primary` (green), and built its classes by interpolation so
            // Tailwind could not see them.
            const tone = severityStyle(event.severity);

            return (
              <motion.div
                key={event.event_id}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: idx * 0.05 }}
              >
                <Card className={`p-4 bg-muted/30 hover:bg-muted/50 transition-colors ${tone.border}`}>
                  <div className="flex items-start justify-between mb-2">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1 flex-wrap">
                        <Badge className={tone.badge} title={tone.label}>
                          {event.severity.toUpperCase()}
                        </Badge>
                        {/* The sparkle that used to sit here shared a row with landslide
                            and flood alerts. The distinction still matters; the
                            decoration did not. */}
                        <Badge className={isRisk ? "bg-destructive/20 text-destructive" : "bg-success/20 text-success"}>
                          {isRisk ? "RISK" : "OPPORTUNITY"}
                        </Badge>
                        <Badge className="border border-border">{event.domain}</Badge>
                        {isFlood && (
                          <Badge className="bg-info/20 text-info">FLOOD</Badge>
                        )}
                      </div>
                      <p className="font-semibold text-sm mb-1">{formatSummary(event.summary)}</p>
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

      {/*
        REMOVED: four "Operational Risk Indicators" cards.

        They rendered "Weather Impact", "Critical Risk Level", "Market
        Activity" and "Opportunity Index" as large percentages, immediately
        above <RiskIndices />, which renders genuinely calibrated indices under
        overlapping names. On one screen, roughly 40px apart, the dashboard
        showed:

          Opportunity Index  21%   (this block, opportunityEvents / total)
          Opportunity index  33%   (RiskIndices, from the aggregator)

        Same label, same screen, two numbers, no indication they measured
        different things. A reader who notices that stops trusting every other
        figure on the page -- including the correct ones.

        Two of the four were not metrics at all:

          Math.min(100, Math.round((matching / total) * 100 * 3))

        A proportion multiplied by three and clamped. That is what produced
        "MARKET ACTIVITY 100%" from 6 economic events out of 24.

        RiskIndices already does this job properly: real aggregator values,
        an explanation per index, and a drill-down to the events behind it.
        Nothing is lost by deleting this block, and the contradiction goes
        with it.
      */}
    </div>
  );
};

export default DashboardOverview;

import { Card } from "../ui/card";
import { Badge } from "../ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../ui/tabs";
import { Button } from "../ui/button";
import { Newspaper, Cloud, TrendingUp, FileText, Radio, Globe, MapPin, Settings, Target } from "lucide-react";
import { useRogerData, RogerEvent } from "../../hooks/use-roger-data";
import { motion, AnimatePresence } from "framer-motion";
import { useState } from "react";
import IntelligenceSettings from "./IntelligenceSettings";
import RelevanceBadge from "./RelevanceBadge";
import WhyThisEvent from "./WhyThisEvent";
import EntityChips from "./EntityChips";
import { formatExact, formatWhen } from "@/app/lib/format";

const IntelligenceFeed = () => {
  const { events, isConnected } = useRogerData();

  // Region toggle state (Sri Lanka / World)
  const [region, setRegion] = useState<"sri_lanka" | "world">("sri_lanka");

  // Settings panel toggle
  const [showSettings, setShowSettings] = useState(false);

  // "Relevant to me" filter. Off by default, on purpose: the platform ranks,
  // the user decides what to hide. A risk feed that silently drops something
  // you needed is the worst failure it can have.
  const [onlyRelevant, setOnlyRelevant] = useState(false);

  // ALWAYS ensure events is an array
  const safeEvents: RogerEvent[] = Array.isArray(events) ? events : [];

  // Only offer the toggle when events actually carry relevance -- i.e. the
  // user has an exposure profile. Otherwise it would filter on nothing and
  // appear broken.
  const isRanked = safeEvents.some(e => e?.relevance != null);
  // Mirrors RELEVANT_THRESHOLD in backend/src/intelligence/relevance.py.
  const RELEVANT_THRESHOLD = 0.35;
  const relevantCount = safeEvents.filter(
    e => (e?.relevance?.score ?? 0) >= RELEVANT_THRESHOLD
  ).length;

  // Filter by region first
  const regionFilteredEvents = safeEvents.filter(e => {
    // If event has region field, use it; otherwise infer from domain
    const eventRegion = e?.region || "sri_lanka"; // Default to Sri Lanka
    if (eventRegion !== region) return false;
    if (onlyRelevant && isRanked) {
      return (e?.relevance?.score ?? 0) >= RELEVANT_THRESHOLD;
    }
    return true;
  });

  // Then filter by category
  const allEvents = regionFilteredEvents;
  const newsEvents = regionFilteredEvents.filter(e => e?.domain === "social" || e?.domain === "intelligence");
  const politicalEvents = regionFilteredEvents.filter(e => e?.domain === "political");
  const weatherEvents = regionFilteredEvents.filter(e => e?.domain === "weather" || e?.domain === "meteorological");
  const economicEvents = regionFilteredEvents.filter(e => e?.domain === "economical" || e?.domain === "market");

  const renderEventCard = (item: RogerEvent, idx: number) => {
    if (!item) return null;

    const isRisk = item.impact_type === "risk";

    const severityColorMap: Record<string, string> = {
      critical: "destructive",
      high: "warning",
      medium: "primary",
      low: "secondary",
    };
    const severityColor = severityColorMap[item.severity] || "secondary";

    const domainIconMap: Record<string, React.ComponentType<any>> = {
      social: Newspaper,
      political: FileText,
      weather: Cloud,
      meteorological: Cloud,
      economical: TrendingUp,
      market: TrendingUp,
      intelligence: Radio,
    };
    const Icon = domainIconMap[item.domain] || Radio;

    return (
      <motion.div
        key={item.event_id}
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: idx * 0.05 }}
      >
        <Card
          className={`p-4 bg-muted/30 border-l-4 hover:bg-muted/50 transition-colors ${severityColor === "destructive"
            ? "border-l-destructive"
            : severityColor === "warning"
              ? "border-l-warning"
              : severityColor === "primary"
                ? "border-l-primary"
                : "border-l-secondary"
            }`}
        >
          <div className="flex items-start justify-between mb-2">
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-1">
                <Icon className="w-4 h-4" />
                <Badge
                  className={
                    severityColor === "destructive"
                      ? "bg-destructive text-destructive-foreground"
                      : severityColor === "warning"
                        ? "bg-warning text-warning-foreground"
                        : severityColor === "primary"
                          ? "bg-primary text-primary-foreground"
                          : "bg-secondary text-secondary-foreground"
                  }
                >
                  {item.severity?.toUpperCase()}
                </Badge>

                <Badge className={isRisk ? "bg-destructive/20 text-destructive" : "bg-success/20 text-success"}>
                  {isRisk ? "⚠️ RISK" : "✨ OPP"}
                </Badge>

                <Badge className="border border-border">{item.domain}</Badge>

                {/* Why this is ranked where it is. Absent when the event was
                    not scored -- which means "no profile", not "irrelevant". */}
                <RelevanceBadge relevance={item.relevance} />
              </div>

              <h3 className="font-bold text-sm mb-1">{item.summary}</h3>

              {/* What this event is actually about. These are the canonical
                  names the relevance scorer joins on, so showing them is what
                  makes a "matched on Port of Colombo" badge checkable. */}
              <EntityChips
                entities={item.entities}
                extracted={item.entities_extracted}
                className="mb-1.5"
              />

              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span>Confidence: {Math.round((item.confidence ?? 0) * 100)}%</span>
                <span>•</span>
                <span className="font-mono" title={formatExact(item.timestamp)}>
                  {formatWhen(item.timestamp)}
                </span>
              </div>

              {/* Provenance the pipeline already carries -- whether a model
                  checked this, how credible it is, and why it ranks here. */}
              <WhyThisEvent event={item} />
            </div>
          </div>
        </Card>
      </motion.div>
    );
  };

  return (
    <div className="space-y-6">
      <Card className="p-6 bg-card border-border">
        <div className="flex items-center gap-2 mb-4">
          <Radio className="w-5 h-5 text-primary" />
          <h2 className="text-lg font-bold">INTELLIGENCE FEED</h2>

          <div className="ml-auto flex items-center gap-3">
            {/* Only offered once the user has an exposure profile -- without
                one every event scores null and the toggle would filter on
                nothing. The count is shown so enabling it is never a surprise. */}
            {isRanked && (
              <Button
                variant={onlyRelevant ? "default" : "outline"}
                size="sm"
                onClick={() => setOnlyRelevant(!onlyRelevant)}
                className="flex items-center gap-1"
                title="Show only events that touch your declared exposure"
              >
                <Target className="w-4 h-4" />
                <span className="hidden sm:inline">
                  Relevant to me ({relevantCount})
                </span>
              </Button>
            )}
            <Button
              variant={showSettings ? "default" : "outline"}
              size="sm"
              onClick={() => setShowSettings(!showSettings)}
              className="flex items-center gap-1"
            >
              <Settings className="w-4 h-4" />
              <span className="hidden sm:inline">{showSettings ? "Hide" : "Settings"}</span>
            </Button>
            <span className="text-xs font-mono text-muted-foreground">
              {isConnected ? (
                <span className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-success animate-pulse"></span>
                  Live
                </span>
              ) : (
                <span className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-warning"></span>
                  Reconnecting...
                </span>
              )}
            </span>
          </div>
        </div>

        {/* SETTINGS PANEL */}
        <AnimatePresence>
          {showSettings && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="mb-4 overflow-hidden"
            >
              <IntelligenceSettings />
            </motion.div>
          )}
        </AnimatePresence>

        {/* REGION TOGGLE - Sri Lanka / World */}
        <div className="flex gap-2 mb-4 overflow-x-auto hide-scrollbar">
          <button
            onClick={() => setRegion("sri_lanka")}
            className={`flex items-center gap-2 px-3 sm:px-4 py-2 rounded-lg font-medium transition-all whitespace-nowrap text-sm ${region === "sri_lanka"
              ? "bg-primary text-primary-foreground shadow-lg"
              : "bg-muted text-muted-foreground hover:bg-muted/80"
              }`}
          >
            <MapPin className="w-4 h-4" />
            🇱🇰 <span className="hidden sm:inline">Sri Lanka</span>
            <Badge variant="secondary" className="ml-1">
              {safeEvents.filter(e => (e?.region || "sri_lanka") === "sri_lanka").length}
            </Badge>
          </button>
          <button
            onClick={() => setRegion("world")}
            className={`flex items-center gap-2 px-3 sm:px-4 py-2 rounded-lg font-medium transition-all whitespace-nowrap text-sm ${region === "world"
              ? "bg-primary text-primary-foreground shadow-lg"
              : "bg-muted text-muted-foreground hover:bg-muted/80"
              }`}
          >
            <Globe className="w-4 h-4" />
            🌍 <span className="hidden sm:inline">World</span>
            <Badge variant="secondary" className="ml-1">
              {safeEvents.filter(e => e?.region === "world").length}
            </Badge>
          </button>
        </div>

        <Tabs defaultValue="all" className="w-full">
          <div className="overflow-x-auto hide-scrollbar -mx-2 px-2 sm:mx-0 sm:px-0 pb-2">
            <TabsList className="inline-flex h-auto w-max sm:w-full justify-start sm:justify-center p-1">
              <TabsTrigger value="all" className="px-3 py-1.5 text-xs sm:text-sm data-[state=active]:bg-background data-[state=active]:shadow-sm">ALL ({allEvents.length})</TabsTrigger>
              <TabsTrigger value="news" className="px-3 py-1.5 text-xs sm:text-sm data-[state=active]:bg-background data-[state=active]:shadow-sm">NEWS ({newsEvents.length})</TabsTrigger>
              <TabsTrigger value="political" className="px-3 py-1.5 text-xs sm:text-sm data-[state=active]:bg-background data-[state=active]:shadow-sm">POLITICAL ({politicalEvents.length})</TabsTrigger>
              <TabsTrigger value="weather" className="px-3 py-1.5 text-xs sm:text-sm data-[state=active]:bg-background data-[state=active]:shadow-sm">WEATHER ({weatherEvents.length})</TabsTrigger>
              <TabsTrigger value="economic" className="px-3 py-1.5 text-xs sm:text-sm data-[state=active]:bg-background data-[state=active]:shadow-sm">ECONOMIC ({economicEvents.length})</TabsTrigger>
            </TabsList>
          </div>

          {/* ALL */}
          <TabsContent value="all" className="space-y-3 max-h-[600px] overflow-y-auto intel-scrollbar pr-2">
            {allEvents.length > 0 ? (
              allEvents.map(renderEventCard)
            ) : (
              <div className="text-center py-12 text-muted-foreground">
                <Radio className="w-12 h-12 mx-auto mb-3 opacity-50" />
                <p className="text-sm font-mono">Waiting for intelligence data...</p>
              </div>
            )}
          </TabsContent>

          {/* NEWS */}
          <TabsContent value="news" className="space-y-3 max-h-[600px] overflow-y-auto intel-scrollbar pr-2">
            {newsEvents.length > 0 ? (
              newsEvents.map(renderEventCard)
            ) : (
              <div className="text-center py-12 text-muted-foreground">
                <Newspaper className="w-12 h-12 mx-auto mb-3 opacity-50" />
                <p className="text-sm">No news events yet</p>
              </div>
            )}
          </TabsContent>

          {/* POLITICAL */}
          <TabsContent value="political" className="space-y-3 max-h-[600px] overflow-y-auto intel-scrollbar pr-2">
            {politicalEvents.length > 0 ? (
              politicalEvents.map(renderEventCard)
            ) : (
              <div className="text-center py-12 text-muted-foreground">
                <FileText className="w-12 h-12 mx-auto mb-3 opacity-50" />
                <p className="text-sm">No political updates yet</p>
              </div>
            )}
          </TabsContent>

          {/* WEATHER */}
          <TabsContent value="weather" className="space-y-3 max-h-[600px] overflow-y-auto intel-scrollbar pr-2">
            {weatherEvents.length > 0 ? (
              weatherEvents.map(renderEventCard)
            ) : (
              <div className="text-center py-12 text-muted-foreground">
                <Cloud className="w-12 h-12 mx-auto mb-3 opacity-50" />
                <p className="text-sm">No weather alerts yet</p>
              </div>
            )}
          </TabsContent>

          {/* ECONOMIC */}
          <TabsContent value="economic" className="space-y-3 max-h-[600px] overflow-y-auto intel-scrollbar pr-2">
            {economicEvents.length > 0 ? (
              economicEvents.map(renderEventCard)
            ) : (
              <div className="text-center py-12 text-muted-foreground">
                <TrendingUp className="w-12 h-12 mx-auto mb-3 opacity-50" />
                <p className="text-sm">No economic data yet</p>
              </div>
            )}
          </TabsContent>
        </Tabs>
      </Card>
    </div>
  );
};

export default IntelligenceFeed;

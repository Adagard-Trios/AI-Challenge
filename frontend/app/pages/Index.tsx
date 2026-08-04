'use client'

import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import DashboardOverview from "../components/dashboard/DashboardOverview";
import MapView from "../components/map/MapView";
import IntelligenceFeed from "../components/intelligence/IntelligenceFeed";
import StockPredictions from "../components/dashboard/StockPredictions";
import AnomalyDetection from "../components/dashboard/AnomalyDetection";
import WeatherPredictions from "../components/dashboard/WeatherPredictions";
import CurrencyPrediction from "../components/dashboard/CurrencyPrediction";
import NationalThreatCard from "../components/dashboard/NationalThreatCard";
import HistoricalIntel from "../components/dashboard/HistoricalIntel";
import TrendingTopics from "../components/dashboard/TrendingTopics";
import SatelliteView from "../components/map/SatelliteView";
import LoadingScreen from "../components/LoadingScreen";
import { Activity, Map, Radio, BarChart3, Zap, Brain, Cloud, DollarSign, Satellite } from "lucide-react";
import { useRogerData } from "../hooks/use-roger-data";
import { Badge } from "../components/ui/badge";

const Index = () => {
  const { status, run_count, isConnected, first_run_complete, events } = useRogerData();

  // Show loading screen until:
  // 1. first_run_complete is true, OR
  // 2. We have existing events from REST API (faster initial load)
  // This ensures the loading screen disappears once ANY data is available
  const isLoading = status === 'initializing' && !first_run_complete && (!events || events.length === 0);

  if (isLoading) {
    return <LoadingScreen />;
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b border-border bg-card sticky top-0 z-50">
        <div className="container mx-auto px-4 sm:px-6 py-3 sm:py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <div className="w-10 h-10 bg-primary rounded flex items-center justify-center">
                  <Activity className="w-6 h-6 text-primary-foreground" />
                </div>
                <div>
                  <h1 className="text-lg sm:text-xl font-bold tracking-tight text-foreground">
                    ROGER
                  </h1>
                  <p className="text-xs text-muted-foreground font-mono hidden sm:block">SITUATIONAL AWARENESS</p>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2 sm:gap-4">
              {/* Connection Status */}
              {isConnected ? (
                <Badge className="bg-success/20 text-success flex items-center gap-1 sm:gap-2 text-xs">
                  <span className="w-2 h-2 rounded-full bg-success animate-pulse"></span>
                  <span className="hidden sm:inline">OPERATIONAL</span>
                </Badge>
              ) : (
                <Badge className="bg-warning/20 text-warning flex items-center gap-1 sm:gap-2 text-xs">
                  <span className="w-2 h-2 rounded-full bg-warning animate-pulse"></span>
                  <span className="hidden sm:inline">RECONNECTING</span>
                </Badge>
              )}

              {/* System Status - hidden on mobile */}
              <Badge className="border border-border items-center gap-2 hidden sm:flex">
                <Zap className="w-3 h-3" />
                Run #{run_count}
              </Badge>

              {/* Time - hidden on mobile */}
              <div className="text-xs font-mono text-muted-foreground hidden md:block">
                {new Date().toLocaleString('en-US', {
                  hour: '2-digit',
                  minute: '2-digit',
                  hour12: false
                })} HRS
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="container mx-auto px-3 sm:px-6 py-4 sm:py-6">
        <Tabs defaultValue="overview" className="w-full">
          <div className="overflow-x-auto hide-scrollbar -mx-3 px-3 sm:mx-0 sm:px-0">
            <TabsList className="inline-flex w-max sm:grid sm:w-full sm:grid-cols-7 mb-4 sm:mb-6 bg-card border border-border min-w-full sm:min-w-0">
              <TabsTrigger value="overview" className="data-ready gap-2 px-3 sm:px-4 py-2.5 sm:py-2">
                <BarChart3 className="w-4 h-4" />
                <span className="hidden sm:inline">OVERVIEW</span>
              </TabsTrigger>
              <TabsTrigger value="map" className="data-ready gap-2 px-3 sm:px-4 py-2.5 sm:py-2">
                <Map className="w-4 h-4" />
                <span className="hidden sm:inline">TERRITORY MAP</span>
              </TabsTrigger>
              <TabsTrigger value="intelligence" className="data-ready gap-2 px-3 sm:px-4 py-2.5 sm:py-2">
                <Radio className="w-4 h-4" />
                <span className="hidden sm:inline">INTEL FEED</span>
              </TabsTrigger>
              <TabsTrigger value="satellite" className="data-ready gap-2 px-3 sm:px-4 py-2.5 sm:py-2">
                <Satellite className="w-4 h-4" />
                <span className="hidden sm:inline">SATELLITE</span>
              </TabsTrigger>
              <TabsTrigger value="weather" className="data-ready gap-2 px-3 sm:px-4 py-2.5 sm:py-2">
                <Cloud className="w-4 h-4" />
                <span className="hidden sm:inline">WEATHER</span>
              </TabsTrigger>
              <TabsTrigger value="anomalies" className="data-ready gap-2 px-3 sm:px-4 py-2.5 sm:py-2">
                <Brain className="w-4 h-4" />
                <span className="hidden sm:inline">ANOMALIES</span>
              </TabsTrigger>
              <TabsTrigger value="analytics" className="data-ready gap-2 px-3 sm:px-4 py-2.5 sm:py-2">
                <Activity className="w-4 h-4" />
                <span className="hidden sm:inline">ANALYTICS</span>
              </TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="overview" className="space-y-6 animate-fade-in">
            <DashboardOverview />
            <TrendingTopics />
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <StockPredictions />
              <CurrencyPrediction />
            </div>
          </TabsContent>

          <TabsContent value="map" className="animate-fade-in">
            <MapView />
          </TabsContent>

          <TabsContent value="intelligence" className="animate-fade-in">
            <IntelligenceFeed />
          </TabsContent>

          <TabsContent value="satellite" className="animate-fade-in">
            <SatelliteView />
          </TabsContent>

          <TabsContent value="weather" className="animate-fade-in space-y-6">
            {/* National Threat Score */}
            <NationalThreatCard />

            {/* Weather Predictions */}
            <WeatherPredictions />

            {/* Historical Climate Analysis */}
            <HistoricalIntel />
          </TabsContent>

          <TabsContent value="anomalies" className="animate-fade-in">
            <AnomalyDetection />
          </TabsContent>

          <TabsContent value="analytics" className="animate-fade-in">
            <div className="grid gap-6">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <StockPredictions />
                <CurrencyPrediction />
              </div>
              <AnomalyDetection />
            </div>
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
};

export default Index;

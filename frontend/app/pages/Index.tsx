'use client'

import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import DashboardOverview from "../components/dashboard/DashboardOverview";
import MapView from "../components/map/MapView";
import IntelligenceFeed from "../components/intelligence/IntelligenceFeed";
import StoryFeed from "../components/intelligence/StoryFeed";
import RiskIndices from "../components/dashboard/RiskIndices";
import StockPredictions from "../components/dashboard/StockPredictions";
import AnomalyDetection from "../components/dashboard/AnomalyDetection";
import WeatherPredictions from "../components/dashboard/WeatherPredictions";
import CurrencyPrediction from "../components/dashboard/CurrencyPrediction";
import NationalThreatCard from "../components/dashboard/NationalThreatCard";
import HistoricalIntel from "../components/dashboard/HistoricalIntel";
import TrendingTopics from "../components/dashboard/TrendingTopics";
import SatelliteView from "../components/map/SatelliteView";
import LoadingScreen from "../components/LoadingScreen";
import SocialAccounts from "../components/settings/SocialAccounts";
import CollectedPosts from "../components/settings/CollectedPosts";
import { Activity, Map, Radio, BarChart3, Zap, Brain, Cloud, DollarSign, Satellite, Link2, Layers } from "lucide-react";
import { useRogerData } from "../hooks/use-roger-data";
import { useAuth } from "../lib/auth-context";
import { useNavigate } from "react-router-dom";
import { Badge } from "../components/ui/badge";
import { useEffect, useState } from "react";

const Index = () => {
  const { status, run_count, isConnected, first_run_complete, events } = useRogerData();
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  // Wait for the first agent cycle, but never indefinitely.
  //
  // This used to block on `status === 'initializing' && no events`, with no
  // upper bound. A cycle fans out to five scraping agents and takes minutes on
  // a good run -- and if scraping stalls or the LLM is rate limited it never
  // completes at all. So a user who had just signed in successfully sat on a
  // spinner with no way forward, which reads exactly like a failed login.
  //
  // Waiting was never necessary. Every panel already handles having no data:
  // stories says "No stories yet", collected posts says "Nothing collected
  // yet", the cards carry provenance badges. And the Accounts tab -- where you
  // go to connect an account so that there IS data -- does not depend on the
  // feed at all, so blocking it is precisely backwards.
  const [waitedLongEnough, setWaitedLongEnough] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setWaitedLongEnough(true), 8000);
    return () => clearTimeout(timer);
  }, []);

  const noDataYet =
    status === 'initializing' && !first_run_complete && (!events || events.length === 0);

  if (noDataYet && !waitedLongEnough) {
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

              {/* Sign in / out.
                  Without this there was no way to authenticate when
                  AUTH_ENFORCED is off, and the social account fields require a
                  user -- so they were unreachable by design with no way to fix
                  it from the UI. */}
              {user ? (
                <button
                  onClick={() => { void logout(); }}
                  title={user.email}
                  className="rounded border border-border px-2 py-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                >
                  Sign out
                </button>
              ) : (
                <button
                  onClick={() => navigate("/login")}
                  className="rounded bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground hover:opacity-90 transition-opacity"
                >
                  Sign in
                </button>
              )}

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
        {/* An empty dashboard is indistinguishable from a broken one unless it
            says which it is. The first cycle takes minutes; the Accounts tab
            works immediately and is where you go to make there be data. */}
        {noDataYet && (
          <div className="mb-4 flex items-start gap-2 rounded-lg border border-border bg-card p-3 text-xs text-muted-foreground">
            <Zap className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            <span>
              The first collection cycle has not finished yet, so panels below
              are empty rather than broken. It fans out to five agents and takes
              a few minutes. Everything still works meanwhile &mdash; the{" "}
              <strong className="text-foreground">ACCOUNTS</strong> tab does not
              depend on the feed.
            </span>
          </div>
        )}
        <Tabs defaultValue="overview" className="w-full">
          <div className="overflow-x-auto hide-scrollbar -mx-3 px-3 sm:mx-0 sm:px-0">
            <TabsList className="inline-flex w-max sm:grid sm:w-full sm:grid-cols-9 mb-4 sm:mb-6 bg-card border border-border min-w-full sm:min-w-0">
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
              <TabsTrigger value="stories" className="data-ready gap-2 px-3 sm:px-4 py-2.5 sm:py-2">
                <Layers className="w-4 h-4" />
                <span className="hidden sm:inline">STORIES</span>
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
              <TabsTrigger value="accounts" className="data-ready gap-2 px-3 sm:px-4 py-2.5 sm:py-2">
                <Link2 className="w-4 h-4" />
                <span className="hidden sm:inline">ACCOUNTS</span>
              </TabsTrigger>
            </TabsList>
          </div>

          <TabsContent value="overview" className="space-y-6 animate-fade-in">
            <DashboardOverview />
            {/* The four risk indices the aggregator has always computed and
                nothing rendered -- each one openable to the events behind it. */}
            <RiskIndices />
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

          <TabsContent value="stories" className="animate-fade-in">
            <StoryFeed />
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

          <TabsContent value="accounts" className="animate-fade-in space-y-8">
            {/* Sign in here — the server is this machine, so the fields and the
                browser window are both in front of you. */}
            <SocialAccounts />

            {/* Proof the accounts above are actually working. Without this the
                whole flow ended at a row count in a database. */}
            <CollectedPosts />

          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
};

export default Index;

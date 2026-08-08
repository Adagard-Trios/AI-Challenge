'use client'

import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import DashboardOverview from "../components/dashboard/DashboardOverview";
import MapView from "../components/map/MapView";
import IntelligenceFeed from "../components/intelligence/IntelligenceFeed";
import StoryFeed from "../components/intelligence/StoryFeed";
import ImageSearch from "../components/intelligence/ImageSearch";
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
import ThemeToggle from "../components/ThemeToggle";
import SocialAccounts from "../components/settings/SocialAccounts";
import CollectedPosts from "../components/settings/CollectedPosts";
import { Activity, Map, Radio, BarChart3, Zap, Brain, Cloud, Satellite, Link2, Layers } from "lucide-react";
import { useRogerData } from "../hooks/use-roger-data";
import { useAuth } from "../lib/auth-context";
import { useNavigate } from "react-router-dom";
import { Badge } from "../components/ui/badge";
import { useEffect, useState } from "react";

/**
 * The nine dashboard tabs, in the order they appear.
 *
 * "TERRITORY MAP" and "ANOMALIES" are gone. This is a civilian early-warning
 * tool for district offices and small businesses -- districts are
 * administrative units, not territory to be held, and the military register
 * read badly against a product whose own framing is SDG 11/13. "SITUATIONAL
 * AWARENESS" and "INTEL FEED" stay: they are the domain's actual vocabulary
 * and the team wants them.
 */
const TABS = [
  { value: "overview", label: "OVERVIEW", Icon: BarChart3 },
  { value: "map", label: "DISTRICTS", Icon: Map },
  { value: "intelligence", label: "INTEL FEED", Icon: Radio },
  { value: "stories", label: "STORIES", Icon: Layers },
  { value: "satellite", label: "SATELLITE", Icon: Satellite },
  { value: "weather", label: "WEATHER", Icon: Cloud },
  { value: "anomalies", label: "UNUSUAL ACTIVITY", Icon: Brain },
  { value: "analytics", label: "ANALYTICS", Icon: Activity },
  { value: "accounts", label: "ACCOUNTS", Icon: Link2 },
] as const;

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

  // Ticking wall clock. Starts empty so the first client render matches, then
  // updates every second.
  const [clock, setClock] = useState("--:--");

  useEffect(() => {
    const tick = () =>
      setClock(
        new Date().toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        }),
      );
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
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
              {/* Connection status.
                  "OPERATIONAL" / "RECONNECTING" described the transport in
                  mission-control register. What a district officer needs to
                  know is whether what they are looking at is current. */}
              {isConnected ? (
                <Badge className="bg-success/20 text-success flex items-center gap-1 sm:gap-2 text-xs">
                  <span className="w-2 h-2 rounded-full bg-success animate-pulse"></span>
                  <span className="hidden sm:inline">Live</span>
                </Badge>
              ) : (
                <Badge className="bg-warning/20 text-warning flex items-center gap-1 sm:gap-2 text-xs">
                  <span className="w-2 h-2 rounded-full bg-warning animate-pulse"></span>
                  <span className="hidden sm:inline">Reconnecting</span>
                </Badge>
              )}

              {/* Collection cycle count - hidden on mobile */}
              <Badge className="border border-border items-center gap-2 hidden sm:flex">
                <Zap className="w-3 h-3" />
                Cycle {run_count}
              </Badge>

              <ThemeToggle />

              {/* Sign in / out.
                  Without this there was no way to authenticate when
                  AUTH_ENFORCED is off, and the social account fields require a
                  user -- so they were unreachable by design with no way to fix
                  it from the UI. */}
              {user ? (
                <button
                  onClick={() => { void logout(); }}
                  title={user.email}
                  className="rounded border border-border px-3 min-h-[44px] sm:min-h-0 sm:py-1 text-xs text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                >
                  Sign out
                </button>
              ) : (
                <button
                  onClick={() => navigate("/login")}
                  className="rounded bg-primary px-3 min-h-[44px] sm:min-h-0 sm:py-1 text-xs font-medium text-primary-foreground hover:opacity-90 transition-opacity focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                >
                  Sign in
                </button>
              )}

              {/* Time - hidden on mobile.
                  This rendered `new Date()` once at mount and never again, so
                  the wall clock on a live operations dashboard was frozen at
                  page-load time -- worse than showing nothing, because it
                  looks authoritative. */}
              <div className="text-xs font-mono text-muted-foreground hidden md:block">
                {clock} HRS
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
              {TABS.map(({ value, label, Icon }) => (
                <TabsTrigger
                  key={value}
                  value={value}
                  /* The label used to be `hidden sm:inline`, which left nine
                     40x36 icon buttons on mobile with no accessible name and
                     nothing to tell them apart -- unusable with a screen
                     reader and unlearnable without one. The list already
                     scrolls horizontally, so there is room to just show it.
                     aria-label stays as the belt-and-braces for the icon. */
                  aria-label={label}
                  className="gap-2 px-3 sm:px-4 min-h-[44px] sm:min-h-0 sm:py-2"
                >
                  <Icon className="w-4 h-4 shrink-0" />
                  <span>{label}</span>
                </TabsTrigger>
              ))}
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

          <TabsContent value="intelligence" className="animate-fade-in space-y-8">
            {/* Search the collected corpus by picture. Answers "has this photo
                been posted before", which text search cannot. */}
            <ImageSearch />
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

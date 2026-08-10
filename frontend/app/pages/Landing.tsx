"use client";

/**
 * Landing.tsx
 *
 * What a signed-out visitor sees at "/".
 *
 * Before this, "/" fell back to the bare login form, so the URL a judge or a
 * district officer is given opened on an email box with no statement of what
 * the thing is or who it is for. Worse, when the enforcement probe failed the
 * dashboard itself rendered to anyone -- see the note in auth-context.tsx.
 *
 * The copy here is taken from the app's own metadata rather than written fresh,
 * so the page cannot drift into claiming capabilities the platform lacks.
 */

import React from "react";
import { useNavigate } from "react-router-dom";
import { Activity, Droplets, LineChart, LogIn, Radio, Zap } from "lucide-react";

/** Named for what the dashboard genuinely carries -- these are its real tabs. */
const COVERAGE = [
  { icon: Droplets, label: "Flood and water", detail: "River gauges and reservoir levels by district" },
  { icon: Zap, label: "Power", detail: "Outage reports and grid disruption" },
  { icon: Activity, label: "Health and anomalies", detail: "Unusual patterns surfaced from the collected record" },
  { icon: LineChart, label: "Economic", detail: "Currency, commodity and fuel movement" },
];

export default function Landing() {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-background">
      {/* The badge the whole page hangs off: say plainly that there is more
          behind a login, rather than letting the visitor guess why the page
          looks empty. */}
      <div className="border-b border-border bg-muted/40">
        <div className="mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <p className="text-sm text-muted-foreground">
            <span className="mr-2 inline-block h-2 w-2 rounded-full bg-primary align-middle" />
            Sign in to see the platform, the live dashboard is not public.
          </p>
          <button
            onClick={() => navigate("/login")}
            className="inline-flex items-center gap-2 rounded bg-primary px-4 py-2 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            <LogIn className="h-4 w-4" aria-hidden />
            Sign in
          </button>
        </div>
      </div>

      <main className="mx-auto max-w-4xl px-4 py-16 sm:py-24">
        <section className="space-y-5">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Sri Lanka AI Challenge 2026
          </p>
          <h1 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            Roger, early warning for Sri Lanka
          </h1>
          <p className="max-w-2xl text-base leading-relaxed text-muted-foreground">
            Continuous monitoring of Sri Lankan flood, power, water, health and
            economic sources, turned into district-level alerts with the
            reasoning attached.
          </p>

          <div className="flex flex-wrap gap-3 pt-2">
            <button
              onClick={() => navigate("/login")}
              className="inline-flex items-center gap-2 rounded-md bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              <LogIn className="h-4 w-4" aria-hidden />
              Sign in to continue
            </button>
          </div>
        </section>

        <section className="mt-16 grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-2">
          {COVERAGE.map(({ icon: Icon, label, detail }) => (
            <div key={label} className="bg-background p-5">
              <div className="flex items-center gap-2">
                <Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
                <h2 className="text-sm font-medium text-foreground">{label}</h2>
              </div>
              <p className="mt-1.5 text-sm text-muted-foreground">{detail}</p>
            </div>
          ))}
        </section>

        {/* Stated because it is the honest description of the source material,
            and because a reader should know this is built on public
            instrumentation rather than anything privileged. */}
        <section className="mt-10 flex items-start gap-3 rounded-lg border border-border p-5">
          <Radio className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
          <p className="text-sm leading-relaxed text-muted-foreground">
            Built from Sri Lanka&apos;s own public instrumentation and reporting.
            Every alert on the dashboard keeps the events it was derived from, so
            a district officer can see why it fired rather than being asked to
            trust it.
          </p>
        </section>
      </main>
    </div>
  );
}

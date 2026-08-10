"use client";

import React from "react";
import { AlertTriangle } from "lucide-react";

/**
 * Keeps one broken panel from taking down the dashboard.
 *
 * There were no error boundaries anywhere in this app. Combined with
 * `ssr: false` on the only route, that meant any component throwing during
 * render replaced the whole page with Next's bare "Application error: a
 * client-side exception has occurred" -- no header, no tabs, no other panel,
 * nothing to retry.
 *
 * That is not hypothetical. It was reproduced in a production build:
 * `/api/trending` returning `{status: "unavailable"}` with HTTP 200 -- a shape
 * this backend genuinely produces for capabilities that are not running -- made
 * TrendingTopics read `.length` of undefined, and the entire dashboard went
 * white. On a flood-warning tool, one unavailable capability must not be able
 * to hide the flood warnings.
 *
 * Scoped per panel rather than once at the root, so a failure is contained to
 * the card it happened in and everything around it keeps working.
 */

interface Props {
    /** Shown in the fallback so the reader knows WHICH panel failed. */
    name: string;
    children: React.ReactNode;
}

interface State {
    error: Error | null;
}

export default class PanelBoundary extends React.Component<Props, State> {
    state: State = { error: null };

    static getDerivedStateFromError(error: Error): State {
        return { error };
    }

    componentDidCatch(error: Error, info: React.ErrorInfo) {
        // Keep the real stack in the console; the UI stays readable.
        console.error(`[Roger] Panel "${this.props.name}" crashed:`, error, info);
    }

    render() {
        if (!this.state.error) return this.props.children;

        return (
            <div
                role="alert"
                className="rounded-lg border border-border bg-card p-4 text-sm"
            >
                <div className="flex items-start gap-2">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
                    <div className="min-w-0">
                        <p className="font-medium text-foreground">
                            {this.props.name} could not be displayed
                        </p>
                        {/* Says it is this panel only -- otherwise a reader cannot
                            tell whether the rest of the page is trustworthy. */}
                        <p className="mt-1 text-xs text-muted-foreground">
                            This panel hit an unexpected response and has been hidden. Every
                            other panel on this page is unaffected. The details are in the
                            browser console.
                        </p>
                        <button
                            type="button"
                            onClick={() => this.setState({ error: null })}
                            className="mt-2 rounded border border-border px-2 py-1 text-xs text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                        >
                            Try again
                        </button>
                    </div>
                </div>
            </div>
        );
    }
}

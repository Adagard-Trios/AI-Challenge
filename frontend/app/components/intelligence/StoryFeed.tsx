"use client";

import { useCallback, useEffect, useState } from "react";
import {
    AlertTriangle,
    ChevronDown,
    ChevronRight,
    Clock,
    Flame,
    Layers,
    Moon,
    RefreshCw,
    TrendingUp,
} from "lucide-react";
import { Badge } from "../ui/badge";
import { apiGet } from "../../lib/api";
import { formatExact, formatWhen } from "../../lib/format";

/**
 * Ongoing stories — events threaded together instead of deduplicated away.
 *
 * The backend has computed this for a while and nothing rendered it. When a new
 * event semantically matches a prior one, the dedup pipeline knows they are the
 * same developing situation; it used to drop the newcomer. So a flood unfolding
 * over three days appeared as forty disconnected rows, or thirty-nine silently
 * discarded ones, and no object anywhere represented "the Kelani flood".
 *
 * A story has a title, an LLM brief that regenerates as the story moves, and a
 * state derived from its own timeline. This is the difference between a feed
 * and an intelligence product: a feed tells you what was said, a story tells
 * you what is happening.
 *
 * Two honesty rules, both load-bearing:
 *
 *   - `brief_stale` is shown, never hidden. A brief that could not be
 *     regenerated is last cycle's summary of a story that has since moved, and
 *     presenting that as current is exactly the failure the badge exists for.
 *   - an empty list says "no stories yet", not "no stories". Threading needs a
 *     database; without one there are no stories to list, which is different
 *     from none having happened.
 */

export interface Story {
    id: string;
    title: string;
    brief: string | null;
    brief_stale: boolean;
    domain: string | null;
    peak_severity: string | null;
    event_count: number;
    event_ids: string[];
    first_seen: string | null;
    last_seen: string | null;
    state: "escalating" | "developing" | "quiet" | "resolved" | string;
}

const STATE_CONFIG: Record<
    string,
    { label: string; className: string; Icon: typeof Flame; title: string }
> = {
    escalating: {
        label: "ESCALATING",
        className: "bg-destructive/20 text-destructive",
        Icon: TrendingUp,
        title: "Severity has risen since this story started.",
    },
    developing: {
        label: "DEVELOPING",
        className: "bg-warning/20 text-warning",
        Icon: Flame,
        title: "Gained a new event recently.",
    },
    quiet: {
        label: "QUIET",
        className: "bg-muted text-muted-foreground",
        Icon: Moon,
        title: "Nothing new for six hours.",
    },
    resolved: {
        label: "RESOLVED",
        className: "bg-success/20 text-success",
        Icon: Clock,
        title: "Nothing new for twenty-four hours.",
    },
};

const SEVERITY_TONE: Record<string, string> = {
    critical: "bg-destructive/20 text-destructive",
    high: "bg-destructive/15 text-destructive",
    medium: "bg-warning/20 text-warning",
    low: "bg-muted text-muted-foreground",
};

const StoryCard = ({ story }: { story: Story }) => {
    const [open, setOpen] = useState(false);

    const state = STATE_CONFIG[story.state] ?? STATE_CONFIG.developing;
    const StateIcon = state.Icon;

    return (
        <div className="rounded-lg border border-border bg-card p-4">
            <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2 mb-1.5">
                        <Badge className={`${state.className} text-xs flex items-center gap-1`} title={state.title}>
                            <StateIcon className="w-3 h-3" />
                            {state.label}
                        </Badge>

                        {story.peak_severity && (
                            <Badge
                                className={`${
                                    SEVERITY_TONE[story.peak_severity.toLowerCase()] ??
                                    SEVERITY_TONE.low
                                } text-xs`}
                                title="Highest severity seen across this story"
                            >
                                PEAK {story.peak_severity.toUpperCase()}
                            </Badge>
                        )}

                        {story.domain && (
                            <Badge className="bg-muted text-muted-foreground text-xs">
                                {story.domain}
                            </Badge>
                        )}

                        <Badge
                            className="bg-primary/15 text-primary text-xs flex items-center gap-1"
                            title="Events threaded into this story"
                        >
                            <Layers className="w-3 h-3" />
                            {story.event_count} {story.event_count === 1 ? "event" : "events"}
                        </Badge>
                    </div>

                    <h3 className="font-semibold text-foreground leading-snug">
                        {story.title}
                    </h3>
                </div>
            </div>

            {story.brief && (
                <p className="mt-2 text-sm text-muted-foreground leading-relaxed">
                    {story.brief}
                </p>
            )}

            {/* Never quietly present a stale brief as current. */}
            {story.brief_stale && (
                <div
                    className="mt-2 flex items-start gap-1.5 text-xs text-warning"
                    title="The story gained events after this brief was written."
                >
                    <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                    <span>
                        This summary predates the newest events in the story — it
                        could not be regenerated on the last cycle.
                    </span>
                </div>
            )}

            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                <span title={formatExact(story.first_seen)}>
                    First seen {formatWhen(story.first_seen)}
                </span>
                <span title={formatExact(story.last_seen)}>
                    Last update {formatWhen(story.last_seen)}
                </span>

                {story.event_ids.length > 0 && (
                    <button
                        onClick={() => setOpen(!open)}
                        className="flex items-center gap-1 hover:text-foreground transition-colors"
                        aria-expanded={open}
                    >
                        {open ? (
                            <ChevronDown className="w-3 h-3" />
                        ) : (
                            <ChevronRight className="w-3 h-3" />
                        )}
                        {open ? "Hide" : "Show"} contributing events
                    </button>
                )}
            </div>

            {open && (
                <ul className="mt-2 space-y-1 rounded-md border border-border bg-muted/20 p-2.5">
                    {story.event_ids.map((id, index) => (
                        <li key={id} className="font-mono text-xs text-muted-foreground">
                            {index + 1}. {id}
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
};

const StoryFeed = () => {
    const [stories, setStories] = useState<Story[]>([]);
    const [loading, setLoading] = useState(true);

    const load = useCallback(async () => {
        setLoading(true);
        const data = await apiGet<{ stories: Story[]; total: number }>(
            "/api/stories?limit=25",
            { stories: [], total: 0 },
        );
        setStories(data.stories ?? []);
        setLoading(false);
    }, []);

    useEffect(() => {
        void load();
        // Stories change on the agent cycle, not per second. Polling this
        // slowly keeps a free-tier instance from spending its budget on a tab
        // nobody is watching.
        const timer = setInterval(() => void load(), 120_000);
        return () => clearInterval(timer);
    }, [load]);

    return (
        <div className="space-y-4">
            <div className="flex items-start justify-between gap-4">
                <div>
                    <h2 className="text-lg font-bold text-foreground flex items-center gap-2">
                        <Layers className="w-5 h-5 text-primary" />
                        ONGOING STORIES
                    </h2>
                    <p className="text-xs text-muted-foreground mt-0.5">
                        Related events threaded into one developing situation, with a
                        summary that is rewritten as the story moves.
                    </p>
                </div>

                <button
                    onClick={() => void load()}
                    className="flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
                    disabled={loading}
                >
                    <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
                    Refresh
                </button>
            </div>

            {loading && stories.length === 0 && (
                <p className="text-sm text-muted-foreground">Loading stories…</p>
            )}

            {!loading && stories.length === 0 && (
                <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
                    <p className="font-medium text-foreground mb-1">No stories yet.</p>
                    <p>
                        A story appears once two or more events are recognised as the
                        same developing situation. If this stays empty while the feed
                        fills up, story threading has no database to write to — check{" "}
                        <code className="font-mono text-xs">/api/status</code> for a
                        missing <code className="font-mono text-xs">DATABASE_URL</code>.
                    </p>
                </div>
            )}

            <div className="space-y-3">
                {stories.map((story) => (
                    <StoryCard key={story.id} story={story} />
                ))}
            </div>
        </div>
    );
};

export default StoryFeed;

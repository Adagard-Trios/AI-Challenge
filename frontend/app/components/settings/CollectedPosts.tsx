"use client";

/**
 * CollectedPosts.tsx
 * The posts your connected accounts actually collected.
 *
 * These were being stored and shown nowhere. `/api/ingest/recent` has existed
 * since the connector landed and had no consumer in the frontend, so the whole
 * point of connecting an account — "so that we can scrape the posts" — ended at
 * a row count in a database.
 *
 * They reach the intelligence feed too, via the agent cycle, but that takes a
 * few minutes and applies filtering. This is the raw evidence: proof that a
 * connected account is working, visible the moment Collect finishes rather
 * than after the next cycle. When social collection silently stops — an expired
 * session, a challenge, a spent budget — this is the panel that shows it,
 * because a feed missing some posts looks exactly like a quiet day.
 */

import React, { useCallback, useEffect, useState } from "react";
import {
  Inbox, MessageSquare, RefreshCw, Repeat2, ScanText, ThumbsUp,
} from "lucide-react";

import { apiGet } from "@/app/lib/api";
import { formatCount, formatExact, formatWhen } from "@/app/lib/format";

interface PostImage {
  url: string;
  ocr_text: string | null;
  ocr_lang: string | null;
  /** 0-1. Low values are marked rather than hidden — these are photographs,
   *  not scans, so a weak read should not read as text that was certainly
   *  there. Sinhala in particular is poorly served by every general engine. */
  ocr_confidence: number | null;
}

interface Post {
  platform: string;
  poster: string | null;
  text: string;
  url: string | null;
  posted_at: string | null;
  likes: number;
  shares: number;
  comments: number;
  collected_at: string | null;
  images: PostImage[];
}

const PLATFORM_TONE: Record<string, string> = {
  twitter: "bg-sky-500/15 text-sky-300",
  linkedin: "bg-blue-500/15 text-blue-300",
  facebook: "bg-indigo-500/15 text-indigo-300",
  instagram: "bg-pink-500/15 text-pink-300",
  reddit: "bg-orange-500/15 text-orange-300",
};

const CollectedPosts = () => {
  const [posts, setPosts] = useState<Post[]>([]);
  const [filter, setFilter] = useState<string>("all");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const data = await apiGet<{ posts: Post[]; count: number }>(
      "/api/ingest/recent?limit=50",
      { posts: [], count: 0 },
    );
    setPosts(data.posts ?? []);
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const platforms = Array.from(new Set(posts.map((p) => p.platform))).sort();
  const shown = filter === "all" ? posts : posts.filter((p) => p.platform === filter);

  return (
    <div className="space-y-3">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-bold text-slate-100">
            <Inbox className="w-4 h-4 text-slate-400" />
            COLLECTED POSTS
          </h3>
          <p className="mt-0.5 text-xs text-slate-400">
            Raw posts from your connected accounts, newest first. These also feed
            the intelligence pipeline on the next agent cycle.
          </p>
        </div>
        <button
          onClick={() => void load()}
          className="flex items-center gap-1.5 rounded-md border border-slate-600 px-2.5 py-1.5 text-xs text-slate-300 hover:bg-slate-700/50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {platforms.length > 1 && (
        <div className="flex flex-wrap gap-1.5">
          {["all", ...platforms].map((p) => (
            <button
              key={p}
              onClick={() => setFilter(p)}
              className={`rounded-md px-2 py-1 text-xs transition-colors ${
                filter === p
                  ? "bg-slate-700 text-slate-100"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {p === "all" ? `All (${posts.length})` : p}
            </button>
          ))}
        </div>
      )}

      {!loading && posts.length === 0 && (
        <div className="rounded-lg border border-slate-700/50 bg-slate-800/30 p-4 text-xs text-slate-400">
          <p className="mb-1 font-medium text-slate-300">Nothing collected yet.</p>
          <p>
            Connect an account above, then use <strong>Collect now</strong>. If
            this stays empty after a successful collect, check the account&apos;s
            status — an expired session or a challenge stops collection without
            emptying the feed, which looks identical to a quiet day.
          </p>
        </div>
      )}

      <div className="space-y-2">
        {shown.map((post, index) => (
          <div
            key={`${post.platform}-${post.collected_at}-${index}`}
            className="rounded-lg border border-slate-700/50 bg-slate-800/40 p-3"
          >
            <div className="mb-1.5 flex flex-wrap items-center gap-2">
              <span
                className={`rounded px-1.5 py-0.5 text-xs ${
                  PLATFORM_TONE[post.platform] ?? "bg-slate-700 text-slate-300"
                }`}
              >
                {post.platform}
              </span>
              {post.poster && (
                <span className="text-xs font-medium text-slate-300">
                  {post.poster}
                </span>
              )}
              <span
                className="text-xs text-slate-500"
                title={formatExact(post.posted_at ?? post.collected_at)}
              >
                {formatWhen(post.posted_at ?? post.collected_at)}
              </span>
            </div>

            {post.text ? (
              <p className="whitespace-pre-wrap text-sm leading-snug text-slate-200">
                {post.text.length > 400 ? `${post.text.slice(0, 400)}…` : post.text}
              </p>
            ) : (
              <p className="text-sm italic text-slate-500">
                No caption — this post is the image.
              </p>
            )}

            {/* What was read out of the pictures. Shown separately from the
                caption because a machine reading a photograph and a human
                typing a sentence deserve different trust. */}
            {(post.images ?? []).filter((i) => i.ocr_text).map((image, i) => (
              <div
                key={`${image.url}-${i}`}
                className="mt-2 rounded border border-slate-700/50 bg-slate-900/40 p-2"
              >
                <div className="mb-1 flex items-center gap-2 text-xs text-slate-400">
                  <ScanText className="h-3 w-3" />
                  <span>Text in image</span>
                  {image.ocr_lang && image.ocr_lang !== "unknown" && (
                    <span className="rounded bg-slate-700 px-1 py-0.5">
                      {image.ocr_lang}
                    </span>
                  )}
                  {image.ocr_confidence !== null && (
                    <span
                      className={
                        image.ocr_confidence < 0.6 ? "text-amber-400" : "text-slate-500"
                      }
                      title={
                        image.ocr_confidence < 0.6
                          ? "Low confidence — treat this as uncertain."
                          : "Extraction confidence"
                      }
                    >
                      {Math.round(image.ocr_confidence * 100)}% confident
                      {image.ocr_confidence < 0.6 && " — uncertain"}
                    </span>
                  )}
                </div>
                <p className="whitespace-pre-wrap text-xs text-slate-300">
                  {image.ocr_text}
                </p>
              </div>
            ))}

            <div className="mt-2 flex items-center gap-4 text-xs text-slate-500">
              <span className="flex items-center gap-1">
                <ThumbsUp className="w-3 h-3" />
                {formatCount(post.likes)}
              </span>
              <span className="flex items-center gap-1">
                <Repeat2 className="w-3 h-3" />
                {formatCount(post.shares)}
              </span>
              <span className="flex items-center gap-1">
                <MessageSquare className="w-3 h-3" />
                {formatCount(post.comments)}
              </span>
              {post.url && (
                <a
                  href={post.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="ml-auto text-slate-400 hover:text-slate-200"
                >
                  Open original →
                </a>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default CollectedPosts;

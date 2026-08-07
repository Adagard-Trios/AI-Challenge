"use client";

/**
 * ImageSearch.tsx
 * Find collected posts by picture rather than by word.
 *
 * The question this exists to answer is "has this photograph been posted
 * before?" — because a recycled disaster photo is one of the most common
 * shapes misinformation takes, and it is invisible to text search. A 2017
 * flood picture reposted as today's news reads as a perfectly ordinary post
 * until you check the image.
 *
 * Two kinds of answer, kept visually distinct because they are different
 * claims:
 *
 *   same image    — the perceptual hashes match. This photograph has appeared
 *                   before. That is evidence.
 *   similar scene — CLIP thinks they look alike. That is context, not proof,
 *                   and presenting it as the former would be the same
 *                   over-claiming this codebase keeps having to undo.
 */

import React, { useRef, useState } from "react";
import {
  AlertTriangle, Copy, ImageIcon, Loader2, Search, Upload,
} from "lucide-react";

import { API_BASE, apiFetch } from "@/app/lib/api";
import { formatWhen } from "@/app/lib/format";

interface Match {
  post_id: string;
  platform: string;
  poster: string | null;
  text: string;
  url: string | null;
  image_url: string;
  ocr_text: string | null;
  collected_at: string | null;
  matched_on: "same_image" | "similar_scene" | string;
  phash_distance: number | null;
  similarity: number | null;
}

interface Result {
  matches: Match[];
  total: number;
  phash_used: boolean;
  clip_used: boolean;
}

const ImageSearch = () => {
  const [result, setResult] = useState<Result | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const search = async (file: File) => {
    setBusy(true);
    setError(null);
    setResult(null);
    setPreview(URL.createObjectURL(file));

    try {
      const body = new FormData();
      body.append("file", file);
      // Deliberately not using api() — it sets a JSON Content-Type, and a
      // multipart upload needs the browser to set its own boundary.
      const res = await apiFetch(`${API_BASE}/api/social/images/search`, {
        method: "POST",
        body,
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail || `Search failed (${res.status})`);
      }
      setResult(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Search failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-bold text-foreground">
          <ImageIcon className="h-5 w-5 text-primary" />
          SEARCH BY IMAGE
        </h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Upload a picture to find collected posts that use it. Catches a
          photograph being reposted as new — the most common shape a recycled
          disaster image takes.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <input
          ref={input}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void search(file);
          }}
        />
        <button
          onClick={() => input.current?.click()}
          disabled={busy}
          className="flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Upload className="h-4 w-4" />
          )}
          {busy ? "Searching…" : "Choose an image"}
        </button>

        {preview && (
          /* eslint-disable-next-line @next/next/no-img-element */
          <img
            src={preview}
            alt="Uploaded"
            className="h-16 w-16 rounded border border-border object-cover"
          />
        )}
      </div>

      {error && (
        <p className="flex items-start gap-2 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          {error}
        </p>
      )}

      {result && (
        <div className="space-y-3">
          <p className="text-xs text-muted-foreground">
            {result.total === 0
              ? "No collected post uses this image."
              : `${result.total} match${result.total === 1 ? "" : "es"}.`}
            {" "}
            Matched on perceptual hash
            {result.clip_used
              ? " and visual similarity."
              : " only — set ENABLE_CLIP_SEARCH=1 to also match similar scenes."}
          </p>

          {result.matches.map((m) => (
            <div
              key={`${m.post_id}-${m.image_url}`}
              className="rounded-lg border border-border bg-card p-3"
            >
              <div className="mb-1.5 flex flex-wrap items-center gap-2">
                {m.matched_on === "same_image" ? (
                  <span
                    className="flex items-center gap-1 rounded bg-destructive/20 px-1.5 py-0.5 text-xs text-destructive"
                    title="The perceptual hashes match — this is the same photograph."
                  >
                    <Copy className="h-3 w-3" />
                    SAME IMAGE
                    {m.phash_distance !== null && ` · distance ${m.phash_distance}`}
                  </span>
                ) : (
                  <span
                    className="flex items-center gap-1 rounded bg-warning/20 px-1.5 py-0.5 text-xs text-warning"
                    title="Visually similar. Context, not proof of reuse."
                  >
                    <Search className="h-3 w-3" />
                    SIMILAR SCENE
                    {m.similarity !== null && ` · ${(m.similarity * 100).toFixed(0)}%`}
                  </span>
                )}
                <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                  {m.platform}
                </span>
                {m.poster && (
                  <span className="text-xs text-muted-foreground">{m.poster}</span>
                )}
                <span className="text-xs text-muted-foreground">
                  {formatWhen(m.collected_at)}
                </span>
              </div>

              {m.text ? (
                <p className="text-sm text-foreground">{m.text}</p>
              ) : (
                <p className="text-sm italic text-muted-foreground">
                  No caption — this post is the image.
                </p>
              )}

              {m.ocr_text && (
                <p className="mt-1.5 rounded bg-muted/30 p-2 text-xs text-muted-foreground">
                  <span className="font-medium">Text in image: </span>
                  {m.ocr_text}
                </p>
              )}

              {m.url && (
                <a
                  href={m.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-1.5 inline-block text-xs text-muted-foreground hover:text-foreground"
                >
                  Open original →
                </a>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default ImageSearch;

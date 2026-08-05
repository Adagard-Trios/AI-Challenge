"use client";

import { AlertTriangle, HelpCircle } from "lucide-react";

/**
 * Says how far behind a model's training data is.
 *
 * The stock model was trained on data ending 2025-09-19 and is being asked to
 * predict Colombo Stock Exchange prices in August 2026 — a ten month gap,
 * rendered with exactly the same confidence as a live quote. A prediction from
 * a stale window is not so much wrong as unfalsifiable: without the cutoff, a
 * reader has no way to weigh it.
 *
 * Fresh models render nothing. This only appears when there is something to
 * say, so it stays worth reading.
 */

export interface TrainingInfo {
    training_cutoff?: string | null;
    age_days?: number | null;
    staleness?: "fresh" | "stale" | "unknown";
    threshold_days?: number;
    message?: string;
}

interface ModelStalenessProps {
    training?: TrainingInfo | null;
    className?: string;
}

const ModelStaleness = ({ training, className = "" }: ModelStalenessProps) => {
    const state = training?.staleness;

    // Fresh, or a model that has not reported — nothing useful to add.
    if (!training || state === "fresh") return null;

    const isUnknown = state === "unknown";
    const Icon = isUnknown ? HelpCircle : AlertTriangle;

    const tone = isUnknown
        ? "bg-muted/40 border-muted text-muted-foreground"
        : "bg-warning/10 border-warning/40 text-warning";

    const fallback = isUnknown
        ? "Training date unknown — treat this output as unverified."
        : "This model's training data is out of date.";

    return (
        <div
            className={`flex items-start gap-2 rounded-md border px-2 py-1.5 text-xs ${tone} ${className}`}
        >
            <Icon className="w-3.5 h-3.5 mt-0.5 shrink-0" />
            <span>{training.message || fallback}</span>
        </div>
    );
};

export default ModelStaleness;

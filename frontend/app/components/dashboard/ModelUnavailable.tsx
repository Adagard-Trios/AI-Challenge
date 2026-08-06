"use client";

import { CircleSlash, Cpu } from "lucide-react";

/**
 * Why a model card is empty.
 *
 * The deployed backend runs on a 512 MB instance. Three of the four ML models
 * — weather (LSTM), currency (GRU) and stock (LSTM/GRU/BiLSTM) — are Keras and
 * need TensorFlow, which does not fit alongside the API. Their endpoints
 * correctly return `{"status": "unavailable"}`.
 *
 * The cards then rendered a spinner that never resolved, or a bare red error
 * string. Both read as "this product is broken" when the truth is "this
 * capability needs a machine we have not paid for" — a materially different
 * claim, and the honest one is also the better one.
 *
 * Anomaly detection is deliberately not in this list: it runs in-process on
 * 384-dim ONNX MiniLM embeddings and genuinely produces predictions here.
 */

interface ModelUnavailableProps {
    /** The model's own message, when it sent one. */
    message?: string | null;
    /** What this card would show if the model were running. */
    capability: string;
    /** Env var that switches it on. */
    serviceEnv?: string;
}

const ModelUnavailable = ({
    message,
    capability,
    serviceEnv,
}: ModelUnavailableProps) => (
    <div className="rounded-lg border border-border bg-muted/20 p-4 text-sm">
        <div className="flex items-start gap-2.5">
            <CircleSlash className="w-4 h-4 mt-0.5 text-muted-foreground shrink-0" />
            <div className="space-y-1.5">
                <p className="font-medium text-foreground">
                    Not running on this deployment
                </p>
                <p className="text-muted-foreground leading-relaxed">
                    {capability} is a TensorFlow model. The API runs on a 512 MB
                    instance, which cannot hold TensorFlow and serve requests at the
                    same time, so this model is not loaded here.
                </p>
                {serviceEnv && (
                    <p className="text-xs text-muted-foreground flex items-center gap-1.5">
                        <Cpu className="w-3 h-3 shrink-0" />
                        Set{" "}
                        <code className="font-mono text-xs bg-muted px-1 py-0.5 rounded">
                            {serviceEnv}
                        </code>{" "}
                        to a dedicated instance to enable it.
                    </p>
                )}
                {message && (
                    <p className="text-xs text-muted-foreground/70 font-mono">
                        {message}
                    </p>
                )}
            </div>
        </div>
    </div>
);

export default ModelUnavailable;

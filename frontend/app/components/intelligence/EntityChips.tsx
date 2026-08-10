"use client";

import { Building2, Factory, MapPin, Route, Tag } from "lucide-react";
import { Badge } from "../ui/badge";
import type { EventEntity } from "../../hooks/use-roger-data";

/**
 * The real-world things an event is about.
 *
 * Extracted by the LLM on the same call that classifies the event, no extra
 * cost, then canonicalised through src/intelligence/taxonomy.py so that
 * "Colombo Port", "Port of Colombo" and "colombo harbour" become one entity.
 * That canonicalisation is what makes the join to a user's exposure profile
 * work at all; five spellings of the same port match nothing.
 *
 * Rendering them matters beyond decoration: an entity chip is the visible
 * evidence for *why* an event was ranked for this user. The relevance badge
 * says "matched on Port of Colombo"; these chips are where that name came from.
 *
 * The distinction between "extracted nothing" and "extraction did not run" is
 * preserved. An event the model never saw has no entities because nothing
 * looked, which is not the same as an event that genuinely names nothing.
 */

const ICONS: Record<string, typeof MapPin> = {
    PLACE: MapPin,
    ORG: Building2,
    SECTOR: Factory,
    INFRASTRUCTURE: Building2,
    LANE: Route,
};

const ROLE_TONE: Record<string, string> = {
    // What the event happened *to* is the useful one; an actor or a passing
    // mention is weaker evidence and should not read as equally strong.
    affected: "bg-primary/15 text-primary",
    actor: "bg-warning/15 text-warning",
    mentioned: "bg-muted text-muted-foreground",
};

interface EntityChipsProps {
    entities?: EventEntity[] | null;
    /** False when the model never ran on this event. */
    extracted?: boolean;
    className?: string;
}

const EntityChips = ({ entities, extracted, className = "" }: EntityChipsProps) => {
    const rows = entities ?? [];

    // Nothing to say, and saying "no entities" on every unprocessed event would
    // be noise on a busy feed.
    if (rows.length === 0) {
        if (extracted === false) {
            return (
                <p
                    className={`text-xs text-muted-foreground ${className}`}
                    title="The language model did not run on this event, so nothing was extracted."
                >
                    Entities not extracted
                </p>
            );
        }
        return null;
    }

    return (
        <div className={`flex flex-wrap items-center gap-1.5 ${className}`}>
            <Tag className="w-3 h-3 text-muted-foreground shrink-0" />
            {rows.map((entity, index) => {
                const Icon = ICONS[String(entity.type ?? "").toUpperCase()] ?? Tag;
                const tone =
                    ROLE_TONE[String(entity.role ?? "").toLowerCase()] ?? ROLE_TONE.mentioned;

                return (
                    <Badge
                        key={`${entity.name}-${index}`}
                        className={`${tone} text-xs flex items-center gap-1`}
                        title={
                            entity.role
                                ? `${entity.type ?? "entity"} · ${entity.role}`
                                : String(entity.type ?? "entity")
                        }
                    >
                        <Icon className="w-2.5 h-2.5" />
                        {entity.name}
                    </Badge>
                );
            })}
        </div>
    );
};

export default EntityChips;

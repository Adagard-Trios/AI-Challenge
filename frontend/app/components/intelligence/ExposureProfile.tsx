"use client";

import { useState, useEffect } from "react";
import { Card } from "../ui/card";
import { Badge } from "../ui/badge";
import { Building2, Ship, Factory, Route, Tag, X, Save, Target } from "lucide-react";
import { API_BASE, apiFetch } from "@/app/lib/api";

/**
 * What this business depends on.
 *
 * Without it every account sees an identical feed. With it, events are ranked
 * against the things that actually touch this business, the districts it
 * operates in, the port its goods move through, its suppliers, its sector.
 *
 * The picker vocabularies come from the server, which builds them from the same
 * seed table the entity extractor canonicalises to. That is deliberate: a user
 * must not be able to type a value that events can never match, because the
 * result would be a profile that silently matches nothing and a feed that looks
 * like a quiet news day.
 */

interface Profile {
    districts: string[];
    infrastructure: string[];
    lanes: string[];
    sectors: string[];
    suppliers: string[];
    keywords: string[];
}

interface Vocabulary {
    districts: string[];
    infrastructure: string[];
    sectors: string[];
}

const EMPTY: Profile = {
    districts: [], infrastructure: [], lanes: [],
    sectors: [], suppliers: [], keywords: [],
};

type FieldKey = keyof Profile;

const FIELDS: Array<{
    key: FieldKey;
    label: string;
    hint: string;
    Icon: typeof Building2;
    vocabKey?: keyof Vocabulary;
}> = [
        {
            key: "districts", label: "Where you operate", Icon: Building2,
            hint: "Districts with facilities, staff or customers.",
            vocabKey: "districts",
        },
        {
            key: "infrastructure", label: "What you move through", Icon: Ship,
            hint: "Ports, airports and roads your goods depend on.",
            vocabKey: "infrastructure",
        },
        {
            key: "sectors", label: "Your sector", Icon: Factory,
            hint: "Industry-wide events will be ranked up.",
            vocabKey: "sectors",
        },
        {
            key: "suppliers", label: "Suppliers and counterparties", Icon: Target,
            hint: "Named companies. The strongest match there is.",
        },
        {
            key: "lanes", label: "Trade routes", Icon: Route,
            hint: "Named corridors, e.g. Colombo-Singapore.",
        },
        {
            key: "keywords", label: "Anything else", Icon: Tag,
            hint: "Free text, matched against the event summary.",
        },
    ];

const ExposureProfileEditor = () => {
    const [profile, setProfile] = useState<Profile>(EMPTY);
    const [vocabulary, setVocabulary] = useState<Vocabulary | null>(null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [drafts, setDrafts] = useState<Record<string, string>>({});

    useEffect(() => {
        const load = async () => {
            try {
                const res = await apiFetch(`${API_BASE}/api/exposure`);
                if (res.status === 401) {
                    setError("Sign in to set an exposure profile. Until then your feed is shown unranked.");
                    return;
                }
                const data = await res.json();
                setProfile({ ...EMPTY, ...(data.profile || {}) });
                setVocabulary(data.vocabulary || null);
            } catch {
                setError("Could not load your exposure profile.");
            } finally {
                setLoading(false);
            }
        };
        load();
    }, []);

    const add = (key: FieldKey, raw?: string) => {
        const value = (raw ?? drafts[key] ?? "").trim();
        if (!value) return;
        if (profile[key].some((v) => v.toLowerCase() === value.toLowerCase())) return;

        setProfile((p) => ({ ...p, [key]: [...p[key], value] }));
        setDrafts((d) => ({ ...d, [key]: "" }));
    };

    const remove = (key: FieldKey, value: string) => {
        setProfile((p) => ({ ...p, [key]: p[key].filter((v) => v !== value) }));
    };

    const save = async () => {
        setSaving(true);
        setMessage(null);
        try {
            const res = await apiFetch(`${API_BASE}/api/exposure`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(profile),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "save failed");

            // The server canonicalises on write ("Colombo Port" is stored as
            // "Port of Colombo"), so take back what it stored rather than
            // keeping what was typed, otherwise the UI shows a value that no
            // longer matches what is being matched against.
            setProfile({ ...EMPTY, ...(data.profile || {}) });
            setMessage(
                data.configured
                    ? "Saved. Your feed is now ranked against this."
                    : "Saved. Add at least one item to rank your feed."
            );
        } catch (err) {
            setError(err instanceof Error ? err.message : "Could not save.");
        } finally {
            setSaving(false);
        }
    };

    const total = Object.values(profile).reduce((n, list) => n + list.length, 0);

    if (loading) {
        return (
            <Card className="p-6 bg-card border-border">
                <p className="text-sm text-muted-foreground">Loading exposure profile…</p>
            </Card>
        );
    }

    if (error && total === 0) {
        return (
            <Card className="p-6 bg-card border-border">
                <div className="flex items-center gap-2 mb-2">
                    <Target className="w-5 h-5 text-muted-foreground" />
                    <h3 className="font-bold">YOUR EXPOSURE</h3>
                </div>
                <p className="text-sm text-muted-foreground">{error}</p>
            </Card>
        );
    }

    return (
        <Card className="p-6 bg-card border-border">
            <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-2">
                    <div className="p-2 rounded-lg bg-primary/20">
                        <Target className="w-5 h-5 text-primary" />
                    </div>
                    <div>
                        <h3 className="font-bold">YOUR EXPOSURE</h3>
                        <p className="text-xs text-muted-foreground">
                            {total > 0
                                ? `${total} item${total === 1 ? "" : "s"}, your feed is ranked against these`
                                : "Tell the platform what your business depends on"}
                        </p>
                    </div>
                </div>
                <button
                    onClick={save}
                    disabled={saving}
                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-primary text-primary-foreground text-sm disabled:opacity-50"
                >
                    <Save className="w-3.5 h-3.5" />
                    {saving ? "Saving…" : "Save"}
                </button>
            </div>

            {message && (
                <p className="text-xs text-success mb-3">{message}</p>
            )}
            {error && total > 0 && (
                <p className="text-xs text-destructive mb-3">{error}</p>
            )}

            <div className="space-y-4">
                {FIELDS.map(({ key, label, hint, Icon, vocabKey }) => {
                    const options = vocabKey && vocabulary ? vocabulary[vocabKey] : null;
                    const remaining = options
                        ? options.filter((o) => !profile[key].includes(o))
                        : null;

                    return (
                        <div key={key}>
                            <div className="flex items-center gap-2 mb-1">
                                <Icon className="w-3.5 h-3.5 text-muted-foreground" />
                                <span className="text-sm font-semibold">{label}</span>
                            </div>
                            <p className="text-xs text-muted-foreground mb-2">{hint}</p>

                            <div className="flex flex-wrap gap-1 mb-2">
                                {profile[key].map((value) => (
                                    <Badge
                                        key={value}
                                        className="bg-primary/15 text-primary flex items-center gap-1"
                                    >
                                        {value}
                                        <button
                                            onClick={() => remove(key, value)}
                                            aria-label={`Remove ${value}`}
                                            className="hover:text-destructive"
                                        >
                                            <X className="w-3 h-3" />
                                        </button>
                                    </Badge>
                                ))}
                                {profile[key].length === 0 && (
                                    <span className="text-xs text-muted-foreground italic">
                                        nothing yet
                                    </span>
                                )}
                            </div>

                            {remaining ? (
                                <select
                                    value=""
                                    onChange={(e) => e.target.value && add(key, e.target.value)}
                                    className="w-full text-sm rounded-lg bg-muted/30 border border-border px-2 py-1.5"
                                >
                                    <option value="">Add…</option>
                                    {remaining.map((o) => (
                                        <option key={o} value={o}>{o}</option>
                                    ))}
                                </select>
                            ) : (
                                <input
                                    value={drafts[key] || ""}
                                    onChange={(e) =>
                                        setDrafts((d) => ({ ...d, [key]: e.target.value }))
                                    }
                                    onKeyDown={(e) => e.key === "Enter" && add(key)}
                                    placeholder="Type and press Enter"
                                    className="w-full text-sm rounded-lg bg-muted/30 border border-border px-2 py-1.5"
                                />
                            )}
                        </div>
                    );
                })}
            </div>
        </Card>
    );
};

export default ExposureProfileEditor;

"use client";

import { Badge } from "../ui/badge";
import { Radio, AlertTriangle, CircleSlash, CloudOff } from "lucide-react";

/**
 * Says where a card's data came from.
 *
 * Cards used to render a "LIVE" badge only when scrape_status was "live", and
 * nothing at all otherwise. Stale data was therefore signalled by the ABSENCE
 * of a badge, which nobody notices -- so a hardcoded 2.1% inflation figure sat
 * on the dashboard looking exactly like a live one, next to a policy rate that
 * was a full point out and a USD/LKR rate off by 8%.
 *
 * The rule here is the inverse: "live" is quiet, everything else is loud.
 */

export type ScrapeStatus =
    | "live"
    | "partial"
    | "baseline"
    | "unavailable"
    | "error";

interface DataProvenanceProps {
    status?: string;
    /** The period the DATA describes -- not when it was fetched. */
    asOf?: string | null;
    /** Hide the as-of chip when the card shows the date itself. */
    showAsOf?: boolean;
    className?: string;
}

const config: Record<
    ScrapeStatus,
    { label: string; title: string; className: string; Icon: typeof Radio }
> = {
    live: {
        label: "LIVE",
        title: "Fetched from the source on this request.",
        className: "bg-success/20 text-success",
        Icon: Radio,
    },
    partial: {
        label: "PARTIAL",
        title: "Some values are live; others could not be read and fell back.",
        className: "bg-warning/20 text-warning",
        Icon: AlertTriangle,
    },
    baseline: {
        label: "NOT LIVE",
        title:
            "The source could not be read. These are fallback values and may be " +
            "badly out of date — do not act on them.",
        className: "bg-destructive/20 text-destructive",
        Icon: CloudOff,
    },
    unavailable: {
        label: "NO SOURCE",
        title: "There is no readable source for this data yet.",
        className: "bg-muted text-muted-foreground",
        Icon: CircleSlash,
    },
    error: {
        label: "FETCH FAILED",
        title: "The attempt to read the source raised an error.",
        className: "bg-destructive/20 text-destructive",
        Icon: AlertTriangle,
    },
};

const DataProvenance = ({
    status,
    asOf,
    showAsOf = true,
    className = "",
}: DataProvenanceProps) => {
    // An absent status is not an implicit "live" — it means the tool did not
    // say, which is exactly the situation this component exists to surface.
    const key = (status && status in config ? status : "unavailable") as ScrapeStatus;
    const { label, title, className: tone, Icon } = config[key];
    const isLive = key === "live";

    return (
        <div className={`flex items-center gap-1 ${className}`}>
            <Badge
                title={title}
                className={`${tone} text-xs flex items-center gap-1 ${
                    isLive ? "" : "font-semibold"
                }`}
            >
                <Icon className={`w-2.5 h-2.5 ${isLive ? "animate-pulse" : ""}`} />
                {label}
            </Badge>
            {showAsOf && asOf && (
                <Badge
                    className="bg-muted text-muted-foreground text-xs"
                    title="The period this data describes"
                >
                    {asOf}
                </Badge>
            )}
        </div>
    );
};

export default DataProvenance;

"use client";

import React, { useMemo } from "react";
import { motion } from "framer-motion";
import sriLanka from "@svg-maps/sri-lanka";

// ------------ Types ------------

interface LocationShape {
  id?: string;
  name?: string;
  centroid?: [number, number];
  path?: string;
  paths?: string;
  d?: string;
  geometry?: {
    coordinates?: any;
  };
}

interface SriLankaMapData {
  locations?: LocationShape[];
  features?: LocationShape[];
  viewBox?: string;
}

interface Centroid {
  id: string;
  x: number;
  y: number;
}

interface SriLankaMapProps {
  selectedDistrict: string | null;
  onDistrictSelect: (district: string) => void;
  alertCounts?: Record<string, number>;
  className?: string;
  width?: number | string;
  height?: number | string;
}

// ------------ Component ------------

const SriLankaMap: React.FC<SriLankaMapProps> = ({
  selectedDistrict,
  onDistrictSelect,
  alertCounts = {},
  className = "",
  width = "100%",
  height = "100%",
}) => {
  const mapData = sriLanka as unknown as SriLankaMapData;

  const safeAlerts = alertCounts || {};
  const totalAlerts = Object.values(safeAlerts).reduce((a, b) => a + (b || 0), 0);

  // Extract locations safely
  const locations: LocationShape[] = Array.isArray(mapData.locations)
    ? mapData.locations
    : Array.isArray(mapData.features)
    ? mapData.features
    : [];

  // ------------ Compute Centroids (safe + typed) ------------

  const centroids = useMemo<Centroid[]>(() => {
    return locations.map((loc) => {
      const id = loc.id ?? loc.name ?? "unknown";

      // Use existing centroid
      if (
        Array.isArray(loc.centroid) &&
        loc.centroid.length === 2 &&
        typeof loc.centroid[0] === "number" &&
        typeof loc.centroid[1] === "number"
      ) {
        return { id, x: loc.centroid[0], y: loc.centroid[1] };
      }

      // Compute centroid from SVG path
      const d = loc.path ?? loc.paths ?? loc.d ?? "";
      const nums = d.match(/-?\d+\.?\d*/g)?.map(Number) ?? [];

      const xs = nums.filter((_, i) => i % 2 === 0);
      const ys = nums.filter((_, i) => i % 2 === 1);

      const x = xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0;
      const y = ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : 0;

      return { id, x, y };
    });
  }, [locations]);

  // Helper to find a centroid
  const findCentroid = (id: string): [number, number] => {
    const c = centroids.find((c) => c.id === id);
    return c ? [c.x, c.y] : [0, 0];
  };

  const viewBox = mapData.viewBox ?? "0 0 600 900";

  // ------------ Render ------------

  return (
    <div className={`relative ${className}`} style={{ width, height }}>
      <svg
        viewBox={viewBox}
        width="100%"
        height="100%"
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label="Sri Lanka map by district"
      >
        <g id="base">
          <rect width="100%" height="100%" fill="transparent" />
        </g>

        <g id="districts">
          {locations.map((loc) => {
            const id = loc.id ?? loc.name ?? "unknown";
            const name = loc.name ?? id;

            const pathData =
              loc.path ??
              loc.paths ??
              loc.d ??
              (loc.geometry?.coordinates ? "" : "");

            const alertCount = safeAlerts[name] ?? 0;
            const isSelected = selectedDistrict === name;
            const hasAlerts = alertCount > 0;

            const fill = isSelected
              ? "hsl(var(--primary) / 0.95)"
              : hasAlerts
              ? "hsl(var(--destructive) / 0.28)"
              : "hsl(var(--muted) / 0.22)";

            const stroke = isSelected
              ? "hsl(var(--primary))"
              : hasAlerts
              ? "hsl(var(--destructive))"
              : "hsl(var(--border))";

            const strokeWidth = isSelected ? 2.2 : hasAlerts ? 1.5 : 0.9;

            const [cx, cy] = findCentroid(id);

            return (
              <g key={id} id={`grp-${id}`} data-name={name}>
                {pathData ? (
                  <motion.path
                    id={id}
                    d={pathData}
                    fill={fill}
                    stroke={stroke}
                    strokeWidth={strokeWidth}
                    className="cursor-pointer"
                    onClick={() => onDistrictSelect(name)}
                    whileHover={{ opacity: 0.85 }}
                    whileTap={{ scale: 0.995 }}
                    initial={{ opacity: 0.98 }}
                    transition={{ duration: 0.18 }}
                  />
                ) : (
                  <motion.circle
                    cx={cx}
                    cy={cy}
                    r={10}
                    fill={fill}
                    stroke={stroke}
                    strokeWidth={1}
                    onClick={() => onDistrictSelect(name)}
                    className="cursor-pointer"
                  />
                )}

                {alertCount > 0 && (
                  <motion.g
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    transition={{ type: "spring", stiffness: 200 }}
                  >
                    <circle
                      cx={cx}
                      cy={cy}
                      r={10}
                      fill="hsl(var(--destructive))"
                      stroke="white"
                      strokeWidth={1.2}
                    />
                    <text
                      x={cx}
                      y={cy + 4}
                      textAnchor="middle"
                      fontSize={9}
                      fontWeight={700}
                      fill="#fff"
                      pointerEvents="none"
                    >
                      {alertCount}
                    </text>
                  </motion.g>
                )}
              </g>
            );
          })}
        </g>
      </svg>

      {/* Legend */}
      <div className="absolute top-3 right-3 bg-card/95 border border-border rounded p-2 text-xs text-center">
        <div className="text-lg font-bold text-destructive">{totalAlerts}</div>
        <div className="text-[10px] text-muted-foreground uppercase">
          Total Alerts
        </div>
      </div>

      <style>{`
        svg .cursor-pointer { cursor: pointer; }
      `}</style>
    </div>
  );
};

export default SriLankaMap;

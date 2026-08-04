import * as React from "react";
import * as RechartsPrimitive from "recharts";

import { cn } from "../../lib/utils";

// Format: { THEME_NAME: CSS_SELECTOR }
const THEMES = { light: "", dark: ".dark" } as const;

export type ChartConfig = {
  [k: string]: {
    label?: React.ReactNode;
    icon?: React.ComponentType;
  } & (
    | { color?: string; theme?: never }
    | { color?: never; theme: Record<keyof typeof THEMES, string> }
  );
};

type ChartContextProps = {
  config: ChartConfig;
};

const ChartContext = React.createContext<ChartContextProps | null>(null);

function useChart() {
  const context = React.useContext(ChartContext);
  if (!context) {
    throw new Error("useChart must be used within a <ChartContainer />");
  }
  return context;
}

const ChartContainer = React.forwardRef<
  HTMLDivElement,
  React.ComponentProps<"div"> & {
    config: ChartConfig;
    children: React.ComponentProps<
      typeof RechartsPrimitive.ResponsiveContainer
    >["children"];
  }
>(({ id, className, children, config, ...props }, ref) => {
  const uniqueId = React.useId();
  const chartId = `chart-${id || uniqueId.replace(/:/g, "")}`;

  return (
    <ChartContext.Provider value={{ config }}>
      <div
        data-chart={chartId}
        ref={ref}
        className={cn(
          "flex aspect-video justify-center text-xs " +
            "[&_.recharts-cartesian-axis-tick_text]:fill-muted-foreground " +
            "[&_.recharts-cartesian-grid_line[stroke='#ccc']]:stroke-border/50 " +
            "[&_.recharts-curve.recharts-tooltip-cursor]:stroke-border " +
            "[&_.recharts-dot[stroke='#fff']]:stroke-transparent " +
            "[&_.recharts-layer]:outline-none " +
            "[&_.recharts-polar-grid_[stroke='#ccc']]:stroke-border " +
            "[&_.recharts-radial-bar-background-sector]:fill-muted " +
            "[&_.recharts-rectangle.recharts-tooltip-cursor]:fill-muted " +
            "[&_.recharts-reference-line_[stroke='#ccc']]:stroke-border " +
            "[&_.recharts-sector[stroke='#fff']]:stroke-transparent " +
            "[&_.recharts-sector]:outline-none " +
            "[&_.recharts-surface]:outline-none",
          className
        )}
        {...props}
      >
        <ChartStyle id={chartId} config={config} />
        <RechartsPrimitive.ResponsiveContainer>
          {children}
        </RechartsPrimitive.ResponsiveContainer>
      </div>
    </ChartContext.Provider>
  );
});
ChartContainer.displayName = "Chart";

const ChartStyle = ({
  id,
  config,
}: {
  id: string;
  config: ChartConfig;
}) => {
  const colorConfig = Object.entries(config).filter(
    ([_, cfg]) => cfg.theme || cfg.color
  );

  if (!colorConfig.length) return null;

  return (
    <style
      dangerouslySetInnerHTML={{
        __html: Object.entries(THEMES)
          .map(
            ([theme, prefix]) => `
${prefix} [data-chart=${id}] {
${colorConfig
  .map(([key, itemConfig]) => {
    const color =
      itemConfig.theme?.[theme as keyof typeof itemConfig.theme] ||
      itemConfig.color;
    return color ? `  --color-${key}: ${color};` : "";
  })
  .join("\n")}
}
`
          )
          .join("\n"),
      }}
    />
  );
};

/**
 * Expose the raw Recharts Tooltip component to be used in charts.
 * (We keep the raw component export for parity with shadcn patterns.)
 */
const ChartTooltip = RechartsPrimitive.Tooltip;

/* ---------------------------
   Custom Tooltip Content
   - Compatible with Recharts v3
   - Avoids importing removed types (TooltipPayload)
   - Uses a small local type describing what we need from Recharts
   --------------------------- */

type RechartsPayloadItem = {
  dataKey?: string | number;
  name?: string;
  value?: any;
  payload?: Record<string, any> | undefined;
  // Recharts provides 'color' at runtime for many series; unknown to types,
  // so treat as optional/any when reading.
  color?: string;
};

type ChartTooltipContentProps = {
  active?: boolean;
  label?: string | number | React.ReactNode;
  payload?: RechartsPayloadItem[];
  labelFormatter?: (label: any, payload?: RechartsPayloadItem[]) => React.ReactNode;
  formatter?: (value: any, name: any, item?: RechartsPayloadItem, index?: number, fullPayload?: any) => React.ReactNode;
  className?: string;
  labelClassName?: string;
  hideLabel?: boolean;
  hideIndicator?: boolean;
  indicator?: "line" | "dot" | "dashed";
  nameKey?: string;
  labelKey?: string;
  // any other props may exist; we don't depend on them
};

const ChartTooltipContent = React.forwardRef<HTMLDivElement, ChartTooltipContentProps>(
  (props, ref) => {
    const {
      active,
      className,
      indicator = "dot",
      hideLabel = false,
      hideIndicator = false,
      label,
      labelFormatter,
      labelClassName,
      formatter,
      nameKey,
      labelKey,
      payload = [],
    } = props;

    const { config } = useChart();

    const tooltipLabel = React.useMemo(() => {
      if (hideLabel || !payload?.length) return null;

      const item = payload[0];
      if (!item) return null;

      const key = `${labelKey || item.dataKey || item.name || "value"}`;
      const itemConfig = getPayloadConfigFromPayload(config, item, key);

      const value =
        !labelKey && typeof label === "string"
          ? (config[label as string]?.label ?? label)
          : itemConfig?.label;

      if (!value) return null;

      if (labelFormatter) {
        return (
          <div className={cn("font-medium", labelClassName)}>
            {labelFormatter(value, payload)}
          </div>
        );
      }

      return <div className={cn("font-medium", labelClassName)}>{value}</div>;
    }, [label, labelFormatter, payload, hideLabel, labelClassName, config, labelKey]);

    if (!active || !payload?.length) return null;

    const nestLabel = payload.length === 1 && indicator !== "dot";

    return (
      <div
        ref={ref}
        className={cn(
          "grid min-w-[8rem] items-start gap-1.5 rounded-lg border border-border/50 bg-background px-2.5 py-1.5 text-xs shadow-xl",
          className
        )}
      >
        {!nestLabel && tooltipLabel}
        <div className="grid gap-1.5">
          {payload.map((item, index) => {
            const key = `${nameKey || item.name || item.dataKey || "value"}`;
            const itemConfig = getPayloadConfigFromPayload(config, item, key);

            // Recharts v3 exposes `color` at runtime for many series, but types may not.
            // Read it defensively:
            const indicatorColor = (item && (item.color ?? item.payload?.fill)) ?? undefined;

            return (
              <div
                key={String(item.dataKey ?? index)}
                className={cn(
                  "flex w-full flex-wrap items-stretch gap-2 [&>svg]:h-2.5 [&>svg]:w-2.5 [&>svg]:text-muted-foreground",
                  indicator === "dot" && "items-center"
                )}
              >
                {formatter && item.value !== undefined && item.name ? (
                  formatter(item.value, item.name, item, index, item.payload)
                ) : (
                  <>
                    {itemConfig?.icon ? (
                      <itemConfig.icon />
                    ) : (
                      !hideIndicator && (
                        <div
                          className={cn("shrink-0 rounded-[2px] border-[--color-border] bg-[--color-bg]", {
                            "h-2.5 w-2.5": indicator === "dot",
                            "w-1": indicator === "line",
                            "w-0 border-[1.5px] border-dashed bg-transparent": indicator === "dashed",
                            "my-0.5": nestLabel && indicator === "dashed",
                          })}
                          style={
                            {
                              "--color-bg": indicatorColor,
                              "--color-border": indicatorColor,
                            } as React.CSSProperties
                          }
                        />
                      )
                    )}
                    <div
                      className={cn("flex flex-1 justify-between leading-none", nestLabel ? "items-end" : "items-center")}
                    >
                      <div className="grid gap-1.5">
                        {nestLabel && tooltipLabel}
                        <span className="text-muted-foreground">{itemConfig?.label ?? item.name}</span>
                      </div>

                      {item.value !== undefined && (
                        <span className="font-mono font-medium tabular-nums text-foreground">
                          {typeof item.value === "number" ? item.value.toLocaleString() : String(item.value)}
                        </span>
                      )}
                    </div>
                  </>
                )}
              </div>
            );
          })}
        </div>
      </div>
    );
  }
);
ChartTooltipContent.displayName = "ChartTooltip";

/* ---------------------------
   Legend
   - For Recharts v3 the Legend payload shape can differ; be defensive and use any[]
   --------------------------- */

const ChartLegend = RechartsPrimitive.Legend;

const ChartLegendContent = React.forwardRef<
  HTMLDivElement,
  React.ComponentProps<"div"> & {
    payload?: any[]; // Recharts v3 payload shape varies; use any[]
    hideIcon?: boolean;
    nameKey?: string;
    verticalAlign?: "top" | "bottom";
  }
>(({ className, hideIcon = false, payload, verticalAlign = "bottom", nameKey }, ref) => {
  const { config } = useChart();

  if (!payload?.length) return null;

  return (
    <div
      ref={ref}
      className={cn("flex items-center justify-center gap-4", verticalAlign === "top" ? "pb-3" : "pt-3", className)}
    >
      {payload.map((item: any) => {
        const key = `${nameKey || item.dataKey || "value"}`;
        const itemConfig = getPayloadConfigFromPayload(config, item, key);

        return (
          <div
            key={String(item.value ?? item.dataKey ?? Math.random())}
            className={cn("flex items-center gap-1.5 [&>svg]:h-3 [&>svg]:w-3 [&>svg]:text-muted-foreground")}
          >
            {itemConfig?.icon && !hideIcon ? (
              <itemConfig.icon />
            ) : (
              <div
                className="h-2 w-2 shrink-0 rounded-[2px]"
                style={{ backgroundColor: item.color ?? undefined }}
              />
            )}
            {itemConfig?.label ?? item.value ?? item.dataKey}
          </div>
        );
      })}
    </div>
  );
});
ChartLegendContent.displayName = "ChartLegend";

/* ---------------------------
   Helpers
   --------------------------- */

function getPayloadConfigFromPayload(config: ChartConfig, payload: any, key: string) {
  if (typeof payload !== "object" || payload === null) return undefined;

  const payloadPayload =
    "payload" in payload && typeof payload.payload === "object" && payload.payload !== null ? payload.payload : undefined;

  let configLabelKey: string = key;

  if (key in payload && typeof payload[key] === "string") {
    configLabelKey = payload[key];
  } else if (payloadPayload && key in payloadPayload && typeof payloadPayload[key] === "string") {
    configLabelKey = payloadPayload[key];
  }

  return (config as any)[configLabelKey] ?? (config as any)[key];
}

/* ---------------------------
   Exports
   --------------------------- */

export {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  ChartLegend,
  ChartLegendContent,
  ChartStyle,
};

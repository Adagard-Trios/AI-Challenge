"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

/**
 * Light/dark switch.
 *
 * Renders a fixed-size placeholder until the theme is known. The server cannot
 * know the device's colour scheme, so drawing an icon immediately would either
 * flash the wrong one or mismatch on hydration -- and a control that changes
 * size when it settles shifts the whole header.
 *
 * next-themes leaves `resolvedTheme` undefined until it has read the DOM, so
 * that IS the mounted signal. The usual `useState(false)` +
 * `useEffect(() => setMounted(true))` dance is redundant here, and it trips
 * react-hooks/set-state-in-effect.
 */
export default function ThemeToggle() {
    const { resolvedTheme, setTheme } = useTheme();

    const mounted = resolvedTheme !== undefined;
    const isDark = resolvedTheme === "dark";

    return (
        <button
            type="button"
            onClick={() => setTheme(isDark ? "light" : "dark")}
            aria-label={
                mounted
                    ? isDark
                        ? "Switch to light theme"
                        : "Switch to dark theme"
                    : "Switch theme"
            }
            title={mounted ? (isDark ? "Light theme" : "Dark theme") : undefined}
            className="inline-flex items-center justify-center rounded border border-border min-h-[44px] min-w-[44px] sm:min-h-0 sm:min-w-0 sm:h-7 sm:w-7 text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        >
            {mounted && (isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />)}
        </button>
    );
}

"use client";

/**
 * next-themes was already a dependency, and `ui/sonner.tsx` already called
 * useTheme() -- but no provider was ever mounted, so that call always returned
 * the "system" default and did nothing. This connects it.
 *
 * `attribute="class"` matches `darkMode: ["class"]` in tailwind.config.js:
 * the provider puts `.dark` on <html>, which is what the dark palette in
 * globals.css keys off.
 *
 * defaultTheme="system" so a phone in its usual light mode gets the light
 * theme without anyone choosing anything -- which is the point, given this is
 * read outdoors.
 */

import { ThemeProvider as NextThemesProvider } from "next-themes";
import type { ComponentProps } from "react";

export default function ThemeProvider({
    children,
    ...props
}: ComponentProps<typeof NextThemesProvider>) {
    return (
        <NextThemesProvider
            attribute="class"
            defaultTheme="system"
            enableSystem
            // The colour transition on every element while switching reads as a
            // glitch rather than a transition.
            disableTransitionOnChange
            {...props}
        >
            {children}
        </NextThemesProvider>
    );
}

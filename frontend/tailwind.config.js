const defaultTheme = require("tailwindcss/defaultTheme");

/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: [
    "./pages/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./app/**/*.{ts,tsx}",
    "./src/**/*.{ts,tsx}",
  ],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      // layout.tsx loads Geist via next/font and puts --font-geist-sans /
      // --font-geist-mono on <body>. Without this block nothing ever CONSUMES
      // those variables: `font-sans` and `font-mono` resolve to Tailwind's
      // defaults, so both families were downloaded, subsetted and discarded
      // while the app rendered in whatever the OS supplies -- Segoe UI on
      // Windows, SF on macOS, Roboto on Android. The typography was accidental
      // and different on every machine it was demoed on.
      fontFamily: {
        sans: ["var(--font-geist-sans)", ...defaultTheme.fontFamily.sans],
        mono: ["var(--font-geist-mono)", ...defaultTheme.fontFamily.mono],
      },

      // The type ramp.
      //
      // Measured on the populated dashboard, the default ramp produced 249 of
      // 354 text nodes (70%) at 12px, with 24px as the largest thing on a
      // 1400px-wide page. With no size contrast nothing recedes and nothing
      // advances, so weight was doing the job size should -- 156 elements at
      // font-weight >= 600, which is why bold had stopped meaning anything.
      //
      // Two changes, both here rather than across 237 call sites:
      //
      //   * The floor comes up. `xs` 12 -> 13 and `sm` 14 -> 15, so the text
      //     most of the interface is set in is readable at arm's length on a
      //     phone, outdoors -- which is where flood warnings get read.
      //   * The top opens up. xl/2xl/3xl go 20/24/30 -> 22/28/36, so a panel's
      //     one important number can actually dominate its own card.
      //
      // Line heights are set per step: the defaults are tuned for prose, and
      // a dashboard's dense label/value pairs need tighter leading than a
      // paragraph does.
      fontSize: {
        xs: ["0.8125rem", { lineHeight: "1.125rem" }],   // 13/18 captions, units, timestamps
        sm: ["0.9375rem", { lineHeight: "1.375rem" }],   // 15/22 body — the default
        base: ["1rem", { lineHeight: "1.5rem" }],        // 16/24 card headings
        lg: ["1.125rem", { lineHeight: "1.625rem" }],    // 18/26 section headings
        xl: ["1.375rem", { lineHeight: "1.75rem" }],     // 22/28
        "2xl": ["1.75rem", { lineHeight: "2.125rem" }],  // 28/34
        "3xl": ["2.25rem", { lineHeight: "2.5rem" }],    // 36/40 one number per panel
      },
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        info: {
          DEFAULT: "hsl(var(--info))",
          foreground: "hsl(var(--info-foreground))",
        },
        // The warning ladder (red / amber / yellow / blue). Kept separate from
        // destructive/warning/info so that changing a BUTTON's colour can never
        // silently change what a flood severity looks like.
        // See app/lib/severity.ts.
        severity: {
          critical: {
            DEFAULT: "hsl(var(--severity-critical))",
            foreground: "hsl(var(--severity-critical-foreground))",
          },
          high: {
            DEFAULT: "hsl(var(--severity-high))",
            foreground: "hsl(var(--severity-high-foreground))",
          },
          medium: {
            DEFAULT: "hsl(var(--severity-medium))",
            foreground: "hsl(var(--severity-medium-foreground))",
          },
          low: {
            DEFAULT: "hsl(var(--severity-low))",
            foreground: "hsl(var(--severity-low-foreground))",
          },
        },
        success: {
          DEFAULT: "hsl(var(--success))",
          foreground: "hsl(var(--success-foreground))",
        },
        warning: {
          DEFAULT: "hsl(var(--warning))",
          foreground: "hsl(var(--warning-foreground))",
        },
        sidebar: {
          DEFAULT: "hsl(var(--sidebar-background))",
          foreground: "hsl(var(--sidebar-foreground))",
          primary: "hsl(var(--sidebar-primary))",
          "primary-foreground": "hsl(var(--sidebar-primary-foreground))",
          accent: "hsl(var(--sidebar-accent))",
          "accent-foreground": "hsl(var(--sidebar-accent-foreground))",
          border: "hsl(var(--sidebar-border))",
          ring: "hsl(var(--sidebar-ring))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        // Every TabsContent in Index.tsx carries `animate-fade-in` and this
        // keyframe did not exist -- not here, not in globals.css, and not
        // generated by tailwindcss-animate (which only ships `animate-in` with
        // separate `fade-in` modifiers). The class was a no-op, so tab
        // switching was an instant unanimated swap. The intent was in the
        // markup; only the definition was missing.
        "fade-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "fade-in": "fade-in 0.2s ease-out",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
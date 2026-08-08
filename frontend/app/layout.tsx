import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import ThemeProvider from "./components/ThemeProvider";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

/**
 * Was title "Roger-Intelligence" / description "Crafted by Team Adagard" --
 * which describes who built it rather than what it does, so a shared link
 * previewed as nothing useful. These are the strings that show up in a browser
 * tab, a search result and a WhatsApp preview, which is how this actually gets
 * passed around.
 */
export const metadata: Metadata = {
  title: {
    default: "Roger — early warning for Sri Lanka",
    template: "%s · Roger",
  },
  description:
    "Continuous monitoring of Sri Lankan flood, power, water, health and economic sources, turned into district-level alerts with the reasoning attached.",
  applicationName: "Roger",
  openGraph: {
    title: "Roger — early warning for Sri Lanka",
    description:
      "District-level flood, outage and disruption alerts built from Sri Lanka's own public instrumentation.",
    siteName: "Roger",
    locale: "en_LK",
    type: "website",
  },
  twitter: {
    card: "summary",
    title: "Roger — early warning for Sri Lanka",
    description:
      "District-level flood, outage and disruption alerts built from Sri Lanka's own public instrumentation.",
  },
  // A situational-awareness console behind a login has nothing to gain from
  // being indexed, and the login page showing up in search results is worse
  // than neutral.
  robots: { index: false, follow: false },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    /*
      The font variables go on <html>, not <body>.

      Tailwind's preflight sets `font-family` on the `html` element from
      theme.fontFamily.sans -- which now resolves to var(--font-geist-sans).
      With the variable declared on <body> it is undefined at the point html
      uses it, the whole declaration is invalid, and the document falls back to
      the CSS initial value: Times New Roman. Declaring them one level up is
      what next/font's own examples do, and it makes `font-sans` and
      `font-mono` resolve everywhere.
    */
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable}`}
      suppressHydrationWarning
    >
      <body className="antialiased min-h-screen bg-background">
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}

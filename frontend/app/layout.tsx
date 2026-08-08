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

export const metadata: Metadata = {
  title: "Roger-Intelligence",
  description: "Crafted by Team Adagard",
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

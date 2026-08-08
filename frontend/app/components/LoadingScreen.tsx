"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Card } from "./ui/card";
import { Loader2, Zap } from "lucide-react";

/**
 * Shown while the first collection cycle is still running.
 *
 * Two things this used to do that a platform selling "the reasoning attached"
 * cannot:
 *
 *   1. A progress bar that measured nothing. It advanced 5% every 200ms and
 *      stopped at 95% -- so it always looked nearly finished, whatever was
 *      actually happening, and it reached "95%" in under four seconds on a
 *      cycle that takes minutes. Replaced with elapsed time, which is a real
 *      number, plus an indeterminate spinner.
 *
 *   2. A rotating list of invented status lines -- "Loading Social Media
 *      Monitor...", "Syncing with Database..." -- none of which were tied to
 *      any state. They are gone; the one honest thing to say here is what is
 *      being waited on.
 *
 * The figures at the bottom are the ones the README states consistently.
 * "47+ Data Sources" was here, which is the claim the README explicitly
 * retracts ("An earlier version of this README claimed '50+ data sources'.
 * That was not accurate and has been corrected."). Source counts are also the
 * one figure the README still contradicts itself on -- 19 in one place, 21 in
 * another -- so this deliberately quotes the three numbers that are
 * unambiguous everywhere: agents, gauges, districts.
 */
export default function LoadingScreen() {
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-background">
      <Card className="p-8 sm:p-12 bg-card border-border max-w-lg w-full mx-4">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="space-y-8"
        >
          {/* Logo */}
          <div className="flex items-center justify-center gap-3">
            <Zap className="w-10 h-10 text-primary" />
            <h1 className="text-3xl font-bold tracking-tight text-foreground">ROGER</h1>
          </div>

          {/* An indeterminate bar, because the duration genuinely is not known:
              a cycle fans out to five agents and finishes when the slowest
              source answers. */}
          <div className="space-y-3">
            <div
              className="h-1.5 bg-muted rounded-full overflow-hidden"
              role="progressbar"
              aria-label="Collecting intelligence"
            >
              <motion.div
                className="h-full w-1/3 bg-primary rounded-full"
                animate={{ x: ["-100%", "300%"] }}
                transition={{ duration: 1.8, repeat: Infinity, ease: "easeInOut" }}
              />
            </div>
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span className="font-mono">{seconds}s elapsed</span>
              <span>Waiting for the first collection cycle</span>
            </div>
          </div>

          <div className="flex items-center justify-center gap-2 text-muted-foreground">
            <Loader2 className="w-4 h-4 animate-spin" />
            <p className="text-sm">
              Five agents are collecting in parallel. This usually takes a few
              minutes.
            </p>
          </div>

          <div className="text-center space-y-2 pt-4 border-t border-border">
            <p className="text-sm text-muted-foreground">
              Early warning for Sri Lanka
            </p>
            <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground">
              <span>5 domain agents</span>
              <span aria-hidden="true">•</span>
              <span>30 river gauges</span>
              <span aria-hidden="true">•</span>
              <span>25 districts</span>
            </div>
          </div>
        </motion.div>
      </Card>
    </div>
  );
}

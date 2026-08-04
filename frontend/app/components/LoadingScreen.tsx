"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Card } from "./ui/card";
import { Loader2, Zap } from "lucide-react";

export default function LoadingScreen() {
  const [progress, setProgress] = useState(0);
  const [loadingText, setLoadingText] = useState("Initializing Roger Platform...");

  useEffect(() => {
    const interval = setInterval(() => {
      setProgress((prev) => {
        if (prev >= 95) {
          return prev;
        }
        return prev + 5;
      });
    }, 200);

    const textInterval = setInterval(() => {
      setLoadingText((prev) => {
        const texts = [
          "Initializing Roger Platform...",
          "Connecting to Intelligence Agents...",
          "Loading Social Media Monitor...",
          "Loading Political Intelligence...",
          "Loading Economic Analysis...",
          "Loading Meteorological Data...",
          "Establishing WebSocket Connection...",
          "Syncing with Database...",
          "Preparing Real-Time Dashboard..."
        ];
        const currentIndex = texts.indexOf(prev);
        return texts[(currentIndex + 1) % texts.length];
      });
    }, 1500);

    return () => {
      clearInterval(interval);
      clearInterval(textInterval);
    };
  }, []);

  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-gradient-to-br from-background via-background/95 to-primary/5">
      <Card className="p-12 bg-card/95 backdrop-blur border-border max-w-lg w-full mx-4">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="space-y-8"
        >
          {/* Logo/Icon */}
          <div className="flex items-center justify-center gap-3">
            <motion.div
              animate={{ rotate: 360 }}
              transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
            >
              <Zap className="w-12 h-12 text-primary" />
            </motion.div>
            <h1 className="text-3xl font-bold bg-gradient-to-r from-primary to-primary/60 bg-clip-text text-transparent">
              ROGER
            </h1>
          </div>

          {/* Progress Bar */}
          <div className="space-y-3">
            <div className="h-2 bg-muted rounded-full overflow-hidden">
              <motion.div
                className="h-full bg-gradient-to-r from-primary via-primary/80 to-primary/60"
                initial={{ width: 0 }}
                animate={{ width: `${progress}%` }}
                transition={{ duration: 0.3 }}
              />
            </div>
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>{progress}%</span>
              <span>Loading Intelligence Platform</span>
            </div>
          </div>

          {/* Loading Text */}
          <motion.div
            key={loadingText}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.5 }}
            className="text-center"
          >
            <div className="flex items-center justify-center gap-2 text-muted-foreground">
              <Loader2 className="w-4 h-4 animate-spin" />
              <p className="text-sm font-mono">{loadingText}</p>
            </div>
          </motion.div>

          {/* Info */}
          <div className="text-center space-y-2 pt-4 border-t border-border">
            <p className="text-xs text-muted-foreground">
              Real-Time Situational Awareness for Sri Lanka
            </p>
            <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground">
              <span>6 Domain Agents</span>
              <span>•</span>
              <span>47+ Data Sources</span>
              <span>•</span>
              <span>Live Updates</span>
            </div>
          </div>
        </motion.div>
      </Card>
    </div>
  );
}

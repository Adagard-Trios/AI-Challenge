"use client";

import { useState, useEffect } from "react";
import { Card } from "../ui/card";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Badge } from "../ui/badge";
import {
    Settings,
    Plus,
    X,
    Save,
    RefreshCw,
    Twitter,
    Linkedin,
    Facebook,
    Search,
    Package,
    User
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

// API base URL - adjust based on your backend
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface IntelConfig {
    user_profiles: {
        twitter: string[];
        facebook: string[];
        linkedin: string[];
    };
    user_keywords: string[];
    user_products: string[];
}

const defaultConfig: IntelConfig = {
    user_profiles: { twitter: [], facebook: [], linkedin: [] },
    user_keywords: [],
    user_products: [],
};

const IntelligenceSettings = () => {
    const [config, setConfig] = useState<IntelConfig>(defaultConfig);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [success, setSuccess] = useState<string | null>(null);

    // Input states
    const [newKeyword, setNewKeyword] = useState("");
    const [newProduct, setNewProduct] = useState("");
    const [newProfile, setNewProfile] = useState("");
    const [selectedPlatform, setSelectedPlatform] = useState<"twitter" | "facebook" | "linkedin">("twitter");

    // Fetch config on mount
    useEffect(() => {
        fetchConfig();
    }, []);

    const fetchConfig = async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await fetch(`${API_BASE}/api/intel/config`);
            const data = await res.json();
            if (data.status === "success" && data.config) {
                setConfig(data.config);
            } else if (data.config) {
                setConfig(data.config);
            }
        } catch (err) {
            setError("Failed to load configuration");
            console.error("Failed to fetch intel config:", err);
        } finally {
            setLoading(false);
        }
    };

    const saveConfig = async () => {
        setSaving(true);
        setError(null);
        setSuccess(null);
        try {
            const res = await fetch(`${API_BASE}/api/intel/config`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(config),
            });
            const data = await res.json();
            if (data.status === "updated") {
                setSuccess("Configuration saved! Changes will apply on next agent cycle.");
                setTimeout(() => setSuccess(null), 3000);
            } else {
                setError(data.error || "Failed to save");
            }
        } catch (err) {
            setError("Failed to save configuration");
            console.error("Failed to save intel config:", err);
        } finally {
            setSaving(false);
        }
    };

    const addKeyword = () => {
        if (newKeyword.trim() && !config.user_keywords.includes(newKeyword.trim())) {
            setConfig({
                ...config,
                user_keywords: [...config.user_keywords, newKeyword.trim()],
            });
            setNewKeyword("");
        }
    };

    const removeKeyword = (keyword: string) => {
        setConfig({
            ...config,
            user_keywords: config.user_keywords.filter((k) => k !== keyword),
        });
    };

    const addProduct = () => {
        if (newProduct.trim() && !config.user_products.includes(newProduct.trim())) {
            setConfig({
                ...config,
                user_products: [...config.user_products, newProduct.trim()],
            });
            setNewProduct("");
        }
    };

    const removeProduct = (product: string) => {
        setConfig({
            ...config,
            user_products: config.user_products.filter((p) => p !== product),
        });
    };

    const addProfile = () => {
        if (newProfile.trim() && !config.user_profiles[selectedPlatform].includes(newProfile.trim())) {
            setConfig({
                ...config,
                user_profiles: {
                    ...config.user_profiles,
                    [selectedPlatform]: [...config.user_profiles[selectedPlatform], newProfile.trim()],
                },
            });
            setNewProfile("");
        }
    };

    const removeProfile = (platform: "twitter" | "facebook" | "linkedin", profile: string) => {
        setConfig({
            ...config,
            user_profiles: {
                ...config.user_profiles,
                [platform]: config.user_profiles[platform].filter((p) => p !== profile),
            },
        });
    };

    const platformIcons = {
        twitter: <Twitter className="w-4 h-4" />,
        facebook: <Facebook className="w-4 h-4" />,
        linkedin: <Linkedin className="w-4 h-4" />,
    };

    const platformColors = {
        twitter: "bg-blue-500/20 text-blue-400 border-blue-500/30",
        facebook: "bg-indigo-500/20 text-indigo-400 border-indigo-500/30",
        linkedin: "bg-sky-500/20 text-sky-400 border-sky-500/30",
    };

    if (loading) {
        return (
            <Card className="p-6 bg-card border-border">
                <div className="flex items-center justify-center py-12">
                    <RefreshCw className="w-6 h-6 animate-spin text-primary" />
                    <span className="ml-2 text-muted-foreground">Loading configuration...</span>
                </div>
            </Card>
        );
    }

    return (
        <Card className="p-6 bg-card border-border">
            <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-2">
                    <Settings className="w-5 h-5 text-primary" />
                    <h2 className="text-lg font-bold">INTELLIGENCE SETTINGS</h2>
                </div>
                <div className="flex gap-2">
                    <Button variant="outline" size="sm" onClick={fetchConfig} disabled={loading}>
                        <RefreshCw className={`w-4 h-4 mr-1 ${loading ? "animate-spin" : ""}`} />
                        Refresh
                    </Button>
                    <Button size="sm" onClick={saveConfig} disabled={saving}>
                        <Save className={`w-4 h-4 mr-1 ${saving ? "animate-pulse" : ""}`} />
                        {saving ? "Saving..." : "Save Changes"}
                    </Button>
                </div>
            </div>

            {/* Status Messages */}
            <AnimatePresence>
                {error && (
                    <motion.div
                        initial={{ opacity: 0, y: -10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0 }}
                        className="mb-4 p-3 bg-destructive/20 border border-destructive/30 rounded-lg text-destructive text-sm"
                    >
                        {error}
                    </motion.div>
                )}
                {success && (
                    <motion.div
                        initial={{ opacity: 0, y: -10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0 }}
                        className="mb-4 p-3 bg-success/20 border border-success/30 rounded-lg text-success text-sm"
                    >
                        {success}
                    </motion.div>
                )}
            </AnimatePresence>

            <div className="space-y-6">
                {/* Keywords Section */}
                <div className="p-4 bg-muted/30 rounded-lg border border-border">
                    <div className="flex items-center gap-2 mb-3">
                        <Search className="w-4 h-4 text-primary" />
                        <h3 className="font-semibold">Custom Keywords</h3>
                        <Badge variant="secondary" className="ml-auto">
                            {config.user_keywords.length} keywords
                        </Badge>
                    </div>
                    <p className="text-xs text-muted-foreground mb-3">
                        Add keywords to monitor across all social platforms
                    </p>
                    <div className="flex gap-2 mb-3">
                        <Input
                            placeholder="Enter keyword (e.g., 'Colombo Port')"
                            value={newKeyword}
                            onChange={(e) => setNewKeyword(e.target.value)}
                            onKeyDown={(e) => e.key === "Enter" && addKeyword()}
                            className="flex-1"
                        />
                        <Button size="sm" onClick={addKeyword}>
                            <Plus className="w-4 h-4" />
                        </Button>
                    </div>
                    <div className="flex flex-wrap gap-2">
                        <AnimatePresence>
                            {config.user_keywords.map((keyword) => (
                                <motion.div
                                    key={keyword}
                                    initial={{ opacity: 0, scale: 0.8 }}
                                    animate={{ opacity: 1, scale: 1 }}
                                    exit={{ opacity: 0, scale: 0.8 }}
                                >
                                    <Badge className="flex items-center gap-1 pr-1 bg-primary/20 text-primary border border-primary/30">
                                        {keyword}
                                        <button
                                            onClick={() => removeKeyword(keyword)}
                                            className="ml-1 p-0.5 rounded hover:bg-destructive/20"
                                        >
                                            <X className="w-3 h-3" />
                                        </button>
                                    </Badge>
                                </motion.div>
                            ))}
                        </AnimatePresence>
                        {config.user_keywords.length === 0 && (
                            <span className="text-xs text-muted-foreground italic">No custom keywords added</span>
                        )}
                    </div>
                </div>

                {/* Products Section */}
                <div className="p-4 bg-muted/30 rounded-lg border border-border">
                    <div className="flex items-center gap-2 mb-3">
                        <Package className="w-4 h-4 text-warning" />
                        <h3 className="font-semibold">Products to Track</h3>
                        <Badge variant="secondary" className="ml-auto">
                            {config.user_products.length} products
                        </Badge>
                    </div>
                    <p className="text-xs text-muted-foreground mb-3">
                        Track mentions and reviews of specific products
                    </p>
                    <div className="flex gap-2 mb-3">
                        <Input
                            placeholder="Enter product name (e.g., 'iPhone 15')"
                            value={newProduct}
                            onChange={(e) => setNewProduct(e.target.value)}
                            onKeyDown={(e) => e.key === "Enter" && addProduct()}
                            className="flex-1"
                        />
                        <Button size="sm" onClick={addProduct}>
                            <Plus className="w-4 h-4" />
                        </Button>
                    </div>
                    <div className="flex flex-wrap gap-2">
                        <AnimatePresence>
                            {config.user_products.map((product) => (
                                <motion.div
                                    key={product}
                                    initial={{ opacity: 0, scale: 0.8 }}
                                    animate={{ opacity: 1, scale: 1 }}
                                    exit={{ opacity: 0, scale: 0.8 }}
                                >
                                    <Badge className="flex items-center gap-1 pr-1 bg-warning/20 text-warning border border-warning/30">
                                        {product}
                                        <button
                                            onClick={() => removeProduct(product)}
                                            className="ml-1 p-0.5 rounded hover:bg-destructive/20"
                                        >
                                            <X className="w-3 h-3" />
                                        </button>
                                    </Badge>
                                </motion.div>
                            ))}
                        </AnimatePresence>
                        {config.user_products.length === 0 && (
                            <span className="text-xs text-muted-foreground italic">No custom products added</span>
                        )}
                    </div>
                </div>

                {/* Profiles Section */}
                <div className="p-4 bg-muted/30 rounded-lg border border-border">
                    <div className="flex items-center gap-2 mb-3">
                        <User className="w-4 h-4 text-success" />
                        <h3 className="font-semibold">Profiles to Monitor</h3>
                        <Badge variant="secondary" className="ml-auto">
                            {Object.values(config.user_profiles).flat().length} profiles
                        </Badge>
                    </div>
                    <p className="text-xs text-muted-foreground mb-3">
                        Add social media profiles/pages to monitor
                    </p>

                    {/* Platform Selector */}
                    <div className="flex gap-2 mb-3">
                        {(["twitter", "facebook", "linkedin"] as const).map((platform) => (
                            <button
                                key={platform}
                                onClick={() => setSelectedPlatform(platform)}
                                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${selectedPlatform === platform
                                        ? platformColors[platform] + " border"
                                        : "bg-muted text-muted-foreground hover:bg-muted/80"
                                    }`}
                            >
                                {platformIcons[platform]}
                                {platform.charAt(0).toUpperCase() + platform.slice(1)}
                            </button>
                        ))}
                    </div>

                    <div className="flex gap-2 mb-3">
                        <Input
                            placeholder={`Enter ${selectedPlatform} username/page`}
                            value={newProfile}
                            onChange={(e) => setNewProfile(e.target.value)}
                            onKeyDown={(e) => e.key === "Enter" && addProfile()}
                            className="flex-1"
                        />
                        <Button size="sm" onClick={addProfile}>
                            <Plus className="w-4 h-4" />
                        </Button>
                    </div>

                    {/* Show profiles by platform */}
                    <div className="space-y-3">
                        {(["twitter", "facebook", "linkedin"] as const).map((platform) => (
                            <div key={platform}>
                                <div className="flex items-center gap-2 mb-2">
                                    {platformIcons[platform]}
                                    <span className="text-xs font-medium text-muted-foreground uppercase">
                                        {platform}
                                    </span>
                                    <span className="text-xs text-muted-foreground">
                                        ({config.user_profiles[platform].length})
                                    </span>
                                </div>
                                <div className="flex flex-wrap gap-2">
                                    <AnimatePresence>
                                        {config.user_profiles[platform].map((profile) => (
                                            <motion.div
                                                key={`${platform}-${profile}`}
                                                initial={{ opacity: 0, scale: 0.8 }}
                                                animate={{ opacity: 1, scale: 1 }}
                                                exit={{ opacity: 0, scale: 0.8 }}
                                            >
                                                <Badge className={`flex items-center gap-1 pr-1 border ${platformColors[platform]}`}>
                                                    @{profile}
                                                    <button
                                                        onClick={() => removeProfile(platform, profile)}
                                                        className="ml-1 p-0.5 rounded hover:bg-destructive/20"
                                                    >
                                                        <X className="w-3 h-3" />
                                                    </button>
                                                </Badge>
                                            </motion.div>
                                        ))}
                                    </AnimatePresence>
                                    {config.user_profiles[platform].length === 0 && (
                                        <span className="text-xs text-muted-foreground italic">None</span>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>

                {/* Info Box */}
                <div className="p-3 bg-primary/10 border border-primary/20 rounded-lg">
                    <p className="text-xs text-primary">
                        <strong>Note:</strong> Your custom targets will be monitored in addition to the default
                        competitor profiles (Dialog, SLT, Mobitel, Hutch). Changes take effect on the next
                        intelligence collection cycle.
                    </p>
                </div>
            </div>
        </Card>
    );
};

export default IntelligenceSettings;

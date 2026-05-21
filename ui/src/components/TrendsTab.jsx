import React, { useState, useEffect, useCallback } from 'react';
import {
    TrendingUp, Search, Loader2, AlertCircle, ExternalLink,
    Eye, ThumbsUp, MessageCircle, Clock, Globe, Filter,
    Flame, Zap, BarChart3, ChevronDown, RefreshCw, Play,
    Sparkles, X, ChevronRight, Bot, Target, DollarSign
} from 'lucide-react';

const REGIONS = [
    { code: 'US', name: 'United States' },
    { code: 'RU', name: 'Russia' },
    { code: 'GB', name: 'United Kingdom' },
    { code: 'DE', name: 'Germany' },
    { code: 'FR', name: 'France' },
    { code: 'JP', name: 'Japan' },
    { code: 'KR', name: 'South Korea' },
    { code: 'BR', name: 'Brazil' },
    { code: 'IN', name: 'India' },
    { code: 'CA', name: 'Canada' },
    { code: 'AU', name: 'Australia' },
    { code: 'ES', name: 'Spain' },
    { code: 'IT', name: 'Italy' },
    { code: 'MX', name: 'Mexico' },
    { code: 'TR', name: 'Turkey' },
    { code: 'UA', name: 'Ukraine' },
    { code: 'KZ', name: 'Kazakhstan' },
    { code: 'UZ', name: 'Uzbekistan' },
];

const PERIODS = [
    { value: 'today', label: 'Today' },
    { value: 'week', label: 'This Week' },
    { value: 'month', label: 'This Month' },
    { value: 'year', label: 'This Year' },
];

const SORT_OPTIONS = [
    { value: 'virality', label: 'Virality Score', icon: Flame },
    { value: 'views', label: 'View Count', icon: Eye },
    { value: 'date', label: 'Newest First', icon: Clock },
];

function formatNumber(num) {
    if (num >= 1_000_000_000) return (num / 1_000_000_000).toFixed(1) + 'B';
    if (num >= 1_000_000) return (num / 1_000_000).toFixed(1) + 'M';
    if (num >= 1_000) return (num / 1_000).toFixed(1) + 'K';
    return num.toString();
}

// ─── Virality Badge ──────────────────────────────────────────────
function ViralityBadge({ virality, size = 'normal' }) {
    const isSmall = size === 'small';
    const scoreSize = isSmall ? 'text-xs' : 'text-sm';
    const badgeSize = isSmall ? 'text-base' : 'text-lg';

    return (
        <div
            className="flex items-center gap-1.5 px-2 py-1 rounded-full font-bold"
            style={{
                backgroundColor: virality.color + '18',
                border: `1px solid ${virality.color}40`,
                color: virality.color,
            }}
        >
            <span className={badgeSize}>{virality.badge}</span>
            <span className={scoreSize}>{virality.score}</span>
        </div>
    );
}

// ─── Video Card ──────────────────────────────────────────────────
function VideoCard({ video }) {
    const { virality, stats } = video;

    return (
        <div className="group bg-surface border border-border rounded-xl overflow-hidden hover:border-white/20 transition-all duration-300 hover:shadow-lg hover:shadow-black/30 hover:-translate-y-0.5 flex flex-col">
            {/* Thumbnail */}
            <div className="relative aspect-video overflow-hidden bg-black/40">
                <img
                    src={video.thumbnail}
                    alt={video.title}
                    className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
                    loading="lazy"
                />
                {/* Virality overlay */}
                <div className="absolute top-2 right-2">
                    <ViralityBadge virality={virality} />
                </div>
                {/* Velocity overlay */}
                <div className="absolute bottom-2 left-2 bg-black/80 backdrop-blur-sm text-white text-xs px-2 py-1 rounded-md flex items-center gap-1">
                    <Zap size={10} className="text-yellow-400" />
                    {virality.velocity_text}
                </div>
                {/* Play overlay on hover */}
                <div className="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-all flex items-center justify-center opacity-0 group-hover:opacity-100">
                    <a
                        href={video.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="p-3 bg-red-600 rounded-full hover:bg-red-700 transition-colors shadow-xl"
                        onClick={(e) => e.stopPropagation()}
                    >
                        <Play size={20} className="text-white fill-white" />
                    </a>
                </div>
            </div>

            {/* Content */}
            <div className="p-3 flex flex-col gap-2 flex-1">
                {/* Title */}
                <h3 className="text-sm font-semibold text-white/90 leading-tight line-clamp-2 group-hover:text-white transition-colors">
                    {video.title}
                </h3>

                {/* Channel */}
                <p className="text-xs text-muted truncate">{video.channel}</p>

                {/* Stats Row */}
                <div className="flex items-center gap-3 text-xs text-muted mt-auto pt-1">
                    <span className="flex items-center gap-1">
                        <Eye size={12} /> {formatNumber(stats.views)}
                    </span>
                    {video.channel_stats?.subscribers && video.channel_stats.subscribers < 999999999 && (
                        <span className="flex items-center gap-1 text-white/50">
                            • {formatNumber(video.channel_stats.subscribers)} subs
                        </span>
                    )}
                    <span className="flex items-center gap-1 ml-auto">
                        <ThumbsUp size={12} /> {formatNumber(stats.likes)}
                    </span>
                </div>

                {/* Bottom: age + virality label / outlier */}
                <div className="flex items-center justify-between text-xs pt-1 border-t border-border/50">
                    <span className="text-muted flex items-center gap-1">
                        <Clock size={11} /> {virality.age_text}
                    </span>
                    {virality.outlier_ratio && virality.outlier_ratio >= 3.0 ? (
                        <span className="font-medium bg-fuchsia-500/20 text-fuchsia-300 px-2 py-0.5 rounded-md border border-fuchsia-500/30 flex items-center gap-1">
                            🚀 {Math.round(virality.outlier_ratio)}x Outlier
                        </span>
                    ) : (
                        <span
                            className="font-medium"
                            style={{ color: virality.color }}
                        >
                            {virality.label}
                        </span>
                    )}
                </div>
            </div>
        </div>
    );
}

// ─── Main Component ──────────────────────────────────────────────
export function TrendsTab() {
    const [mode, setMode] = useState('trending'); // 'trending' | 'search'
    const [videos, setVideos] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    // AI Niche Copilot State
    const [isAnalyzing, setIsAnalyzing] = useState(false);
    const [nicheReport, setNicheReport] = useState(null);

    // Filters
    const [region, setRegion] = useState('US');
    const [category, setCategory] = useState('0');
    const [categories, setCategories] = useState([]);
    const [period, setPeriod] = useState('week');
    const [sortBy, setSortBy] = useState('virality');
    const [outliersOnly, setOutliersOnly] = useState(false);
    const [keyword, setKeyword] = useState('');
    const [searchQuery, setSearchQuery] = useState('');

    // Load categories on region change
    useEffect(() => {
        const loadCategories = async () => {
            try {
                const resp = await fetch(`http://localhost:8000/youtube/categories?region=${region}`);
                if (resp.ok) {
                    const data = await resp.json();
                    setCategories(data.categories || []);
                }
            } catch {
                // Categories are optional, don't block on error
            }
        };
        loadCategories();
    }, [region]);

    // Fetch trending on mount
    useEffect(() => {
        fetchTrending();
    }, []);

    const fetchTrending = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const params = new URLSearchParams({ region, category, outliers_only: outliersOnly, max_results: '24' });
            const resp = await fetch(`http://localhost:8000/youtube/trending?${params}`);
            if (!resp.ok) {
                const errData = await resp.json().catch(() => ({}));
                let detail = errData.detail;
                if (Array.isArray(detail)) {
                    detail = detail.map(e => e.msg || JSON.stringify(e)).join(', ');
                } else if (typeof detail === 'object') {
                    detail = JSON.stringify(detail);
                }
                throw new Error(detail || `Failed: ${resp.statusText}`);
            }
            const data = await resp.json();
            setVideos(data.videos || []);
            setMode('trending');
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [region, category, outliersOnly]);

    const handleSearch = useCallback(async (e) => {
        if (e) e.preventDefault();
        if (!keyword.trim()) return;

        setLoading(true);
        setError(null);
        setSearchQuery(keyword);
        try {
            const params = new URLSearchParams({
                q: keyword,
                region,
                category,
                period,
                sort_by: sortBy,
                outliers_only: outliersOnly,
                max_results: '24',
            });
            const resp = await fetch(`http://localhost:8000/youtube/search?${params}`);
            if (!resp.ok) {
                const errData = await resp.json().catch(() => ({}));
                let detail = errData.detail;
                if (Array.isArray(detail)) {
                    detail = detail.map(e => e.msg || JSON.stringify(e)).join(', ');
                } else if (typeof detail === 'object') {
                    detail = JSON.stringify(detail);
                }
                throw new Error(detail || `Failed: ${resp.statusText}`);
            }
            const data = await resp.json();
            setVideos(data.videos || []);
            setMode('search');
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [keyword, region, category, period, sortBy, outliersOnly]);

    const handleAnalyzeNiches = async () => {
        if (!videos || videos.length === 0) return;
        setIsAnalyzing(true);
        setError(null);
        try {
            // Prepare context objects
            const payload = videos.map(v => ({
                title: v.title,
                channel: v.channel,
                views: v.stats.views,
                published_at: v.published_at,
                virality_score: v.virality.score
            }));

            const resp = await fetch('http://localhost:8000/youtube/analyze-niches', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ videos: payload })
            });

            if (!resp.ok) {
                const errData = await resp.json().catch(() => ({}));
                let detail = errData.detail;
                if (Array.isArray(detail)) {
                    detail = detail.map(e => e.msg || JSON.stringify(e)).join(', ');
                } else if (typeof detail === 'object') {
                    detail = JSON.stringify(detail);
                }
                throw new Error(detail || `Failed: ${resp.statusText}`);
            }

            const data = await resp.json();
            setNicheReport(data);
        } catch (err) {
            setError('AI Analysis failed: ' + err.message);
        } finally {
            setIsAnalyzing(false);
        }
    };

    return (
        <div className="h-full flex flex-col overflow-hidden relative">
            {/* Background decorations */}
            <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-red-500/8 rounded-full blur-[120px] -translate-y-1/2 translate-x-1/3 pointer-events-none"></div>
            <div className="absolute bottom-0 left-0 w-[400px] h-[400px] bg-orange-500/5 rounded-full blur-[100px] translate-y-1/2 -translate-x-1/3 pointer-events-none"></div>

            {/* Header */}
            <header className="px-8 pt-8 pb-4 z-10 flex items-center gap-3 flex-shrink-0">
                <div className="p-3 bg-gradient-to-br from-red-500/20 to-orange-500/20 rounded-xl border border-red-500/20">
                    <TrendingUp className="text-red-400" size={24} />
                </div>
                <div>
                    <h1 className="text-2xl font-bold tracking-tight">YouTube Trends</h1>
                    <p className="text-muted text-sm mt-0.5">Discover viral videos · Analyze view velocity · Find trending content</p>
                </div>
            </header>

            {/* Main layout */}
            <div className="flex-1 flex gap-0 min-h-0 z-10">

                {/* ──── Left Sidebar: Filters ──── */}
                <aside className="w-72 flex-shrink-0 border-r border-border bg-surface/50 flex flex-col overflow-y-auto custom-scrollbar p-5 gap-5">

                    {/* Search Input */}
                    <form onSubmit={handleSearch} className="flex flex-col gap-2">
                        <label className="text-xs font-semibold text-white/60 uppercase tracking-wider">Keyword Search</label>
                        <div className="flex gap-2">
                            <input
                                type="text"
                                placeholder="e.g. Mr Beast challenge..."
                                className="flex-1 bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-red-500/50 focus:ring-1 focus:ring-red-500/30 transition-all text-white placeholder-white/20"
                                value={keyword}
                                onChange={(e) => setKeyword(e.target.value)}
                            />
                        </div>
                        <button
                            type="submit"
                            disabled={!keyword.trim() || loading}
                            className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-red-600 to-orange-600 hover:from-red-700 hover:to-orange-700 text-white px-3 py-2 rounded-lg text-sm font-medium transition-all shadow-lg shadow-red-500/20 disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                            {loading && mode === 'search' ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
                            Search
                        </button>
                    </form>

                    <div className="h-px bg-border"></div>

                    {/* Outliers Filter */}
                    <div className="pt-4 border-t border-border mt-2">
                        <label className="flex items-center gap-2 cursor-pointer group">
                            <div className={`w-5 h-5 rounded border ${outliersOnly ? 'bg-purple-500 border-purple-500' : 'border-white/20 group-hover:border-white/40'} flex items-center justify-center transition-colors`}>
                                {outliersOnly && <div className="w-2 h-2 rounded-sm bg-white" />}
                            </div>
                            <input 
                                type="checkbox" 
                                className="hidden" 
                                checked={outliersOnly} 
                                onChange={(e) => setOutliersOnly(e.target.checked)} 
                            />
                            <div className="flex flex-col">
                                <span className={`text-sm font-medium transition-colors ${outliersOnly ? 'text-white' : 'text-white/70 group-hover:text-white'}`}>
                                    🚀 Outliers Only
                                </span>
                                <span className="text-[10px] text-muted">Views {'>'} 3x Subs ratio</span>
                            </div>
                        </label>
                    </div>

                    {/* Trending Button */}
                    <button
                        onClick={fetchTrending}
                        disabled={loading}
                        className={`w-full flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg text-sm font-medium transition-all border ${
                            mode === 'trending'
                                ? 'bg-red-500/10 border-red-500/30 text-red-400 shadow-[0_0_20px_rgba(239,68,68,0.1)]'
                                : 'bg-white/5 border-border text-white/70 hover:bg-white/10 hover:text-white'
                        }`}
                    >
                        {loading && mode === 'trending' ? <Loader2 size={14} className="animate-spin" /> : <Flame size={14} />}
                        🔥 Trending Now
                    </button>

                    <div className="h-px bg-border"></div>

                    {/* Region */}
                    <div className="flex flex-col gap-1.5">
                        <label className="text-xs font-semibold text-white/60 uppercase tracking-wider flex items-center gap-1.5">
                            <Globe size={12} /> Region
                        </label>
                        <select
                            value={region}
                            onChange={(e) => setRegion(e.target.value)}
                            className="bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-red-500/50 transition-all appearance-none cursor-pointer"
                        >
                            {REGIONS.map(r => (
                                <option key={r.code} value={r.code}>{r.name}</option>
                            ))}
                        </select>
                    </div>

                    {/* Category */}
                    <div className="flex flex-col gap-1.5">
                        <label className="text-xs font-semibold text-white/60 uppercase tracking-wider flex items-center gap-1.5">
                            <Filter size={12} /> Category
                        </label>
                        <select
                            value={category}
                            onChange={(e) => setCategory(e.target.value)}
                            className="bg-black/40 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-red-500/50 transition-all appearance-none cursor-pointer"
                        >
                            <option value="0">All Categories</option>
                            {categories.map(c => (
                                <option key={c.id} value={c.id}>{c.title}</option>
                            ))}
                        </select>
                    </div>

                    {/* Period (only for search) */}
                    <div className="flex flex-col gap-1.5">
                        <label className="text-xs font-semibold text-white/60 uppercase tracking-wider flex items-center gap-1.5">
                            <Clock size={12} /> Period
                        </label>
                        <div className="flex flex-col gap-1">
                            {PERIODS.map(p => (
                                <button
                                    key={p.value}
                                    onClick={() => setPeriod(p.value)}
                                    className={`text-left px-3 py-1.5 rounded-md text-sm transition-all ${
                                        period === p.value
                                            ? 'bg-red-500/15 text-red-400 border border-red-500/20'
                                            : 'text-white/60 hover:bg-white/5 hover:text-white/80 border border-transparent'
                                    }`}
                                >
                                    {p.label}
                                </button>
                            ))}
                        </div>
                    </div>

                    <div className="h-px bg-border"></div>

                    {/* Sort By */}
                    <div className="flex flex-col gap-1.5">
                        <label className="text-xs font-semibold text-white/60 uppercase tracking-wider flex items-center gap-1.5">
                            <BarChart3 size={12} /> Sort By
                        </label>
                        <div className="flex flex-col gap-1">
                            {SORT_OPTIONS.map(opt => {
                                const Icon = opt.icon;
                                return (
                                    <button
                                        key={opt.value}
                                        onClick={() => setSortBy(opt.value)}
                                        className={`text-left px-3 py-1.5 rounded-md text-sm transition-all flex items-center gap-2 ${
                                            sortBy === opt.value
                                                ? 'bg-red-500/15 text-red-400 border border-red-500/20'
                                                : 'text-white/60 hover:bg-white/5 hover:text-white/80 border border-transparent'
                                        }`}
                                    >
                                        <Icon size={13} />
                                        {opt.label}
                                    </button>
                                );
                            })}
                        </div>
                    </div>

                    {/* Stats footer */}
                    {videos.length > 0 && (
                        <div className="mt-auto pt-4 border-t border-border">
                            <div className="text-xs text-muted space-y-1">
                                <p><span className="text-white/70 font-medium">{videos.length}</span> videos loaded</p>
                                {mode === 'search' && searchQuery && (
                                    <p>Query: <span className="text-white/70">"{searchQuery}"</span></p>
                                )}
                                <p>Region: <span className="text-white/70">{REGIONS.find(r => r.code === region)?.name}</span></p>
                            </div>
                        </div>
                    )}
                </aside>

                {/* ──── Right: Video Grid ──── */}
                <div className="flex-1 flex flex-col overflow-hidden">

                    {/* Results header bar */}
                    <div className="flex items-center justify-between px-6 py-3 border-b border-border bg-white/[0.02] flex-shrink-0">
                        <div className="flex items-center gap-3">
                            <h2 className="text-sm font-semibold text-white/80">
                                {mode === 'trending'
                                    ? `🔥 Trending in ${REGIONS.find(r => r.code === region)?.name || region}`
                                    : `🔍 Results for "${searchQuery}"`
                                }
                            </h2>
                            {videos.length > 0 && (
                                <span className="text-xs text-muted bg-white/5 px-2 py-0.5 rounded-full">
                                    {videos.length} videos
                                </span>
                            )}
                        </div>
                        <div className="flex items-center gap-4">
                            {videos.length > 0 && (
                                <button
                                    onClick={handleAnalyzeNiches}
                                    disabled={isAnalyzing}
                                    className="flex items-center gap-2 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white px-3 py-1.5 rounded-lg text-sm font-medium transition-all shadow-lg shadow-purple-500/20 disabled:opacity-50"
                                >
                                    {isAnalyzing ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                                    AI Niche Copilot
                                </button>
                            )}
                            <button
                                onClick={mode === 'trending' ? fetchTrending : () => handleSearch()}
                                disabled={loading}
                                className="flex items-center gap-1.5 text-xs text-muted hover:text-white transition-colors disabled:opacity-50"
                            >
                                <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
                                Refresh
                            </button>
                        </div>
                    </div>

                    {/* Grid */}
                    <div className="flex-1 overflow-y-auto custom-scrollbar p-6">
                        {/* Loading state */}
                        {loading && videos.length === 0 && (
                            <div className="flex flex-col items-center justify-center h-full text-muted">
                                <div className="relative">
                                    <Loader2 size={40} className="animate-spin text-red-400" />
                                    <Flame size={18} className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 text-orange-400 animate-pulse" />
                                </div>
                                <p className="text-sm mt-4 animate-pulse">
                                    {mode === 'trending' ? 'Loading trending videos...' : `Searching "${keyword}"...`}
                                </p>
                            </div>
                        )}

                        {/* Error state */}
                        {error && (
                            <div className="mx-auto max-w-lg p-5 bg-red-500/10 border border-red-500/20 text-red-400 rounded-xl text-sm flex gap-3 items-start">
                                <AlertCircle size={18} className="mt-0.5 shrink-0" />
                                <div>
                                    <p className="font-medium mb-1">Failed to load videos</p>
                                    <p className="text-red-300/70">{error}</p>
                                </div>
                            </div>
                        )}

                        {/* Empty state */}
                        {!loading && !error && videos.length === 0 && (
                            <div className="flex flex-col items-center justify-center h-full text-muted opacity-60">
                                <TrendingUp size={48} className="mb-4 opacity-30" />
                                <p className="text-base font-medium mb-1">No videos found</p>
                                <p className="text-sm">Try searching for keywords or click "Trending Now"</p>
                            </div>
                        )}

                        {/* Video grid */}
                        {videos.length > 0 && (
                            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-4">
                                {videos.map((video) => (
                                    <VideoCard key={video.video_id} video={video} />
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            </div>

            {/* AI NICHE REPORT MODAL */}
            {nicheReport && (
                <div className="absolute inset-0 z-50 bg-background/80 backdrop-blur-sm flex items-center justify-center p-8">
                    <div className="bg-surface border border-purple-500/30 rounded-2xl w-full max-w-4xl h-full max-h-[85vh] shadow-[0_0_50px_rgba(168,85,247,0.15)] flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-200">
                        <header className="p-6 border-b border-white/5 bg-white/[0.02] flex items-center justify-between flex-shrink-0">
                            <div className="flex items-center gap-3">
                                <div className="p-2 bg-gradient-to-br from-purple-500 to-indigo-600 rounded-lg shadow-lg">
                                    <Bot className="text-white" size={24} />
                                </div>
                                <div>
                                    <h2 className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-purple-400 to-indigo-300">
                                        AI Niche Intelligence Report
                                    </h2>
                                    <p className="text-sm text-muted">Extracted from {videos.length} trending videos</p>
                                </div>
                            </div>
                            <button
                                onClick={() => setNicheReport(null)}
                                className="p-2 text-muted hover:text-white hover:bg-white/10 rounded-lg transition-colors"
                            >
                                <X size={20} />
                            </button>
                        </header>

                        <div className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-6">
                            {nicheReport.niches?.map((niche, idx) => (
                                <div key={idx} className="bg-black/20 border border-white/5 rounded-xl p-5 hover:border-purple-500/20 transition-all group">
                                    <div className="flex items-start justify-between mb-4">
                                        <h3 className="text-lg font-semibold text-white group-hover:text-purple-300 transition-colors flex items-center gap-2">
                                            <Target size={18} className="text-purple-400" />
                                            {niche.name}
                                        </h3>
                                        {niche.faceless && (
                                            <span className="text-xs font-medium bg-indigo-500/10 text-indigo-300 px-2.5 py-1 rounded-full border border-indigo-500/20">
                                                Faceless Possible
                                            </span>
                                        )}
                                    </div>

                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                                        <div className="bg-white/[0.02] rounded-lg p-4 border border-white/5">
                                            <p className="text-xs text-muted uppercase tracking-wider font-semibold mb-2 flex items-center gap-1.5">
                                                <Flame size={14} className="text-orange-400" /> Why it works
                                            </p>
                                            <p className="text-sm text-white/80 leading-relaxed">{niche.hook_secret}</p>
                                        </div>
                                        <div className="flex flex-col gap-4">
                                            <div className="bg-white/[0.02] rounded-lg p-4 border border-white/5 flex-1">
                                                <p className="text-xs text-muted uppercase tracking-wider font-semibold mb-2 flex items-center gap-1.5">
                                                    <DollarSign size={14} className="text-green-400" /> Monetization
                                                </p>
                                                <p className="text-sm text-white/80 leading-relaxed">{niche.monetization}</p>
                                            </div>
                                            <div className="flex items-center justify-between text-sm">
                                                <span className="text-muted">Production Difficulty:</span>
                                                <span className={`font-semibold ${niche.difficulty === 'Low' ? 'text-green-400' : niche.difficulty === 'Medium' ? 'text-yellow-400' : 'text-red-400'}`}>
                                                    {niche.difficulty}
                                                </span>
                                            </div>
                                        </div>
                                    </div>

                                    <div className="pt-4 border-t border-white/5">
                                        <p className="text-xs text-muted uppercase tracking-wider font-semibold mb-3 flex items-center gap-1.5">
                                            <Sparkles size={14} className="text-purple-400" /> Actionable Ideas
                                        </p>
                                        <ul className="space-y-2">
                                            {niche.ideas?.map((idea, i) => (
                                                <li key={i} className="text-sm text-white/90 flex items-start gap-2">
                                                    <ChevronRight size={16} className="text-purple-500/50 mt-0.5 shrink-0" />
                                                    {idea}
                                                </li>
                                            ))}
                                        </ul>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}


import { useState, useEffect, useRef } from 'react';
import { Brain, Target, Map, Zap, CheckCircle, XCircle, ArrowRight, Loader2, Plus, History, FileText, Upload, Trash2, ScrollText, Film } from 'lucide-react';

export function DecisionList({ alias }) {
    const [analyses, setAnalyses] = useState([]);
    const [selectedId, setSelectedId] = useState(null);
    const [isCreating, setIsCreating] = useState(true);

    // Form State
    const [character, setCharacter] = useState('Bruce Wayne');
    const [goal, setGoal] = useState('');

    // Data State
    const [decisions, setDecisions] = useState([]);
    const [currentMeta, setCurrentMeta] = useState(null); // { character, goal, source, timestamp }

    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    // Screenplay State
    const [screenplayStatus, setScreenplayStatus] = useState(null); // { exists, chars, lines, preview }
    const [uploadingScreenplay, setUploadingScreenplay] = useState(false);
    const fileInputRef = useRef(null);

    useEffect(() => {
        fetchAnalyses();
        fetchScreenplayStatus();
    }, [alias]);

    const fetchScreenplayStatus = async () => {
        try {
            const res = await fetch(`http://localhost:8000/library/${alias}/screenplay/status`);
            if (res.ok) {
                const data = await res.json();
                setScreenplayStatus(data);
            }
        } catch (e) {
            console.error("Failed to fetch screenplay status", e);
        }
    };

    const handleScreenplayUpload = async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;

        setUploadingScreenplay(true);
        try {
            const formData = new FormData();
            formData.append('file', file);

            const res = await fetch(`http://localhost:8000/library/${alias}/screenplay`, {
                method: 'POST',
                body: formData
            });

            if (res.ok) {
                await fetchScreenplayStatus();
            } else {
                const err = await res.json();
                setError(err.error || 'Upload failed');
            }
        } catch (e) {
            setError('Upload failed: ' + e.message);
        } finally {
            setUploadingScreenplay(false);
            if (fileInputRef.current) fileInputRef.current.value = '';
        }
    };

    const handleScreenplayDelete = async () => {
        try {
            const res = await fetch(`http://localhost:8000/library/${alias}/screenplay`, {
                method: 'DELETE'
            });
            if (res.ok) {
                setScreenplayStatus({ exists: false });
            }
        } catch (e) {
            console.error("Failed to delete screenplay", e);
        }
    };

    const fetchAnalyses = async () => {
        try {
            const res = await fetch(`http://localhost:8000/library/${alias}/decisions`);
            if (res.ok) {
                const data = await res.json();
                if (Array.isArray(data)) {
                    setAnalyses(data);
                    // If we have history, show the specific one or the latest
                    if (data.length > 0 && !selectedId && !isCreating) {
                        handleSelect(data[0].id);
                    }
                }
            }
        } catch (e) {
            console.error("Failed to fetch analyses list", e);
        }
    };

    const handleSelect = async (id) => {
        setIsCreating(false);
        setSelectedId(id);
        setLoading(true);
        setError('');

        try {
            const res = await fetch(`http://localhost:8000/library/${alias}/decisions/${id}`);
            if (res.ok) {
                const data = await res.json();
                setDecisions(data.decisions || []);
                setCurrentMeta({
                    character: data.character,
                    goal: data.goal,
                    source: data.source || 'episodes',
                    timestamp: data.timestamp
                });
            } else {
                setError("Failed to load analysis");
            }
        } catch (e) {
            setError("Network error");
        } finally {
            setLoading(false);
        }
    };

    const handleNewClick = () => {
        setIsCreating(true);
        setSelectedId(null);
        setDecisions([]);
        setCurrentMeta(null);
        setCharacter('');
        setGoal('');
    };

    const handleAnalyze = async () => {
        if (!character || !goal) return;

        setLoading(true);
        setError('');
        setDecisions([]);

        try {
            const res = await fetch(`http://localhost:8000/library/${alias}/decisions/analyze`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ character, goal })
            });

            if (res.ok) {
                const data = await res.json();
                setDecisions(data.decisions);
                setCurrentMeta({
                    character: data.character,
                    goal: data.goal,
                    source: data.source || 'episodes',
                    timestamp: data.timestamp
                });
                setIsCreating(false);
                // Refresh list to show new file
                fetchAnalyses();
            } else {
                const err = await res.json();
                setError(err.error || 'Analysis failed');
            }
        } catch (e) {
            setError('Network error');
        } finally {
            setLoading(false);
        }
    };

    const formatDate = (ts) => {
        if (!ts) return '';
        return new Date(ts * 1000).toLocaleDateString() + ' ' + new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    };

    const SourceBadge = ({ source }) => {
        if (source === 'screenplay') {
            return (
                <span className="inline-flex items-center gap-1 text-xs font-mono px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">
                    <ScrollText size={11} /> Script
                </span>
            );
        }
        return (
            <span className="inline-flex items-center gap-1 text-xs font-mono px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20">
                <Film size={11} /> Episodes
            </span>
        );
    };

    return (
        <div className="flex h-[calc(100vh-200px)] gap-6 animate-in fade-in duration-500">

            {/* SIDEBAR: HISTORY */}
            <div className="w-64 bg-surface border border-border rounded-xl flex flex-col overflow-hidden flex-shrink-0">
                <div className="p-4 border-b border-white/5 bg-black/20">
                    <button
                        onClick={handleNewClick}
                        className={`w-full flex items-center justify-center gap-2 py-2 rounded-lg text-sm font-bold transition-all ${isCreating
                            ? 'bg-purple-600 text-white shadow-lg shadow-purple-900/20'
                            : 'bg-white/5 hover:bg-white/10 text-zinc-300'
                            }`}
                    >
                        <Plus size={16} /> New Analysis
                    </button>
                </div>

                <div className="flex-1 overflow-y-auto p-2 space-y-1">
                    {analyses.length === 0 ? (
                        <div className="text-center py-8 text-muted text-xs">
                            No saved analyses
                        </div>
                    ) : (
                        analyses.map(item => (
                            <button
                                key={item.id}
                                onClick={() => handleSelect(item.id)}
                                className={`w-full text-left p-3 rounded-lg text-sm transition-colors border border-transparent ${selectedId === item.id
                                    ? 'bg-purple-500/10 border-purple-500/30 text-white'
                                    : 'hover:bg-white/5 text-zinc-400 hover:text-zinc-200'
                                    }`}
                            >
                                <div className="flex items-center gap-2">
                                    <span className="font-bold truncate flex-1">{item.character}</span>
                                    <SourceBadge source={item.source} />
                                </div>
                                <div className="text-xs text-muted truncate opacity-70">{item.goal}</div>
                                <div className="text-[10px] text-zinc-600 mt-1">{formatDate(item.timestamp)}</div>
                            </button>
                        ))
                    )}
                </div>
            </div>

            {/* MAIN CONTENT */}
            <div className="flex-1 overflow-y-auto pr-2">

                {isCreating ? (
                    /* CREATE MODE */
                    <div className="max-w-2xl mx-auto mt-10">
                        {/* Screenplay Status Panel */}
                        <div className="bg-surface border border-border rounded-xl p-5 mb-6">
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-3">
                                    <div className={`p-2 rounded-lg ${screenplayStatus?.exists ? 'bg-amber-500/10 text-amber-400' : 'bg-white/5 text-zinc-500'}`}>
                                        <ScrollText size={20} />
                                    </div>
                                    <div>
                                        <h4 className="text-sm font-bold text-white">Screenplay</h4>
                                        {screenplayStatus?.exists ? (
                                            <p className="text-xs text-zinc-400">
                                                {screenplayStatus.lines?.toLocaleString()} lines, {screenplayStatus.chars?.toLocaleString()} chars
                                                <span className="text-amber-400 ml-2">• Priority source</span>
                                            </p>
                                        ) : (
                                            <p className="text-xs text-zinc-500">
                                                No screenplay uploaded — will use episodes
                                            </p>
                                        )}
                                    </div>
                                </div>

                                <div className="flex items-center gap-2">
                                    {screenplayStatus?.exists && (
                                        <button
                                            onClick={handleScreenplayDelete}
                                            className="p-2 rounded-lg hover:bg-red-500/10 text-zinc-500 hover:text-red-400 transition-colors"
                                            title="Remove screenplay"
                                        >
                                            <Trash2 size={16} />
                                        </button>
                                    )}
                                    <label className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium cursor-pointer transition-all ${uploadingScreenplay
                                        ? 'bg-white/5 text-zinc-500 cursor-wait'
                                        : screenplayStatus?.exists
                                            ? 'bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white'
                                            : 'bg-amber-600/20 hover:bg-amber-600/30 text-amber-400 border border-amber-500/20'
                                        }`}>
                                        {uploadingScreenplay ? (
                                            <Loader2 size={14} className="animate-spin" />
                                        ) : (
                                            <Upload size={14} />
                                        )}
                                        {screenplayStatus?.exists ? 'Replace' : 'Upload'}
                                        <input
                                            ref={fileInputRef}
                                            type="file"
                                            accept=".txt,.pdf"
                                            className="hidden"
                                            onChange={handleScreenplayUpload}
                                            disabled={uploadingScreenplay}
                                        />
                                    </label>
                                </div>
                            </div>

                            {screenplayStatus?.exists && screenplayStatus.preview && (
                                <div className="mt-3 p-3 bg-black/30 rounded-lg border border-white/5">
                                    <p className="text-[11px] text-zinc-500 font-mono leading-relaxed whitespace-pre-wrap">
                                        {screenplayStatus.preview}
                                    </p>
                                </div>
                            )}
                        </div>

                        {/* Analysis Form */}
                        <div className="bg-surface border border-border p-8 rounded-xl shadow-lg">
                            <h3 className="text-xl font-bold mb-6 flex items-center gap-2 text-white">
                                <Brain className="text-purple-400" />
                                Start New Analysis
                            </h3>

                            {/* Active source indicator */}
                            <div className="mb-6 p-3 rounded-lg bg-black/20 border border-white/5 flex items-center gap-2 text-xs">
                                <span className="text-zinc-500">Source:</span>
                                {screenplayStatus?.exists ? (
                                    <span className="text-amber-400 flex items-center gap-1">
                                        <ScrollText size={12} /> Full Screenplay (priority)
                                    </span>
                                ) : (
                                    <span className="text-blue-400 flex items-center gap-1">
                                        <Film size={12} /> Episode List (fallback)
                                    </span>
                                )}
                            </div>

                            <div className="space-y-6">
                                <div>
                                    <label className="block text-xs font-medium text-muted uppercase mb-1">Character Name</label>
                                    <input
                                        type="text"
                                        autoFocus
                                        className="w-full bg-black/40 border border-border rounded-lg px-4 py-3 text-white focus:outline-none focus:border-purple-500 transition-colors placeholder:text-zinc-600 text-lg"
                                        placeholder="e.g. Bruce Wayne"
                                        value={character}
                                        onChange={(e) => setCharacter(e.target.value)}
                                    />
                                </div>
                                <div>
                                    <label className="block text-xs font-medium text-muted uppercase mb-1">Goal / Motivation</label>
                                    <input
                                        type="text"
                                        className="w-full bg-black/40 border border-border rounded-lg px-4 py-3 text-white focus:outline-none focus:border-purple-500 transition-colors placeholder:text-zinc-600 text-lg"
                                        placeholder="e.g. Save Gotham from fear"
                                        value={goal}
                                        onChange={(e) => setGoal(e.target.value)}
                                    />
                                </div>

                                <button
                                    onClick={handleAnalyze}
                                    disabled={loading || !character || !goal}
                                    className="w-full bg-purple-600 hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed text-white py-4 rounded-xl flex items-center justify-center gap-2 font-bold text-lg shadow-xl shadow-purple-900/20 transition-all hover:scale-[1.02]"
                                >
                                    {loading ? <Loader2 className="animate-spin" /> : <SparklesIcon />}
                                    Run Decision Analysis
                                </button>

                                {error && (
                                    <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-center text-sm">
                                        {error}
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                ) : (
                    /* VIEW MODE */
                    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-300">
                        {/* Header info */}
                        <div className="flex items-start justify-between border-b border-white/5 pb-6">
                            <div>
                                <div className="flex items-center gap-3 mb-2">
                                    <h2 className="text-3xl font-bold text-white">{currentMeta?.character}</h2>
                                    <SourceBadge source={currentMeta?.source} />
                                </div>
                                <div className="flex items-center gap-2 text-muted">
                                    <Target size={16} />
                                    <span>Goal: <span className="text-zinc-300">{currentMeta?.goal}</span></span>
                                </div>
                            </div>
                            {currentMeta?.timestamp && (
                                <div className="text-right text-xs text-zinc-600 font-mono">
                                    Analyzed on<br />
                                    {formatDate(currentMeta.timestamp)}
                                </div>
                            )}
                        </div>

                        {/* Decisions List */}
                        <div className="space-y-4">
                            {decisions.map((d, i) => (
                                <div
                                    key={i}
                                    className="bg-surface border border-white/5 rounded-xl p-5 hover:border-white/10 transition-colors group relative overflow-hidden"
                                >
                                    {/* Background Gradient based on Impact */}
                                    <div className={`absolute left-0 top-0 bottom-0 w-1 ${d.impact === 'positive' ? 'bg-green-500' : 'bg-red-500'}`} />

                                    <div className="flex gap-4 items-start pl-2">
                                        {/* ICON */}
                                        <div className={`p-3 rounded-lg flex-shrink-0 ${d.type.toLowerCase() === 'global'
                                            ? 'bg-blue-500/10 text-blue-400'
                                            : 'bg-amber-500/10 text-amber-400'
                                            }`}>
                                            {d.type.toLowerCase() === 'global' ? <Map size={24} /> : <Zap size={24} />}
                                        </div>

                                        <div className="flex-1 space-y-2">
                                            <div className="flex justify-between items-start">
                                                <h4 className="font-bold text-white text-lg leading-tight">{d.decision}</h4>
                                                <span className={`text-xs font-mono px-2 py-1 rounded uppercase border ${d.impact === 'positive'
                                                    ? 'text-green-400 border-green-500/30 bg-green-500/10'
                                                    : 'text-red-400 border-red-500/30 bg-red-500/10'
                                                    }`}>
                                                    {d.impact}
                                                </span>
                                            </div>
                                            <p className="text-muted text-sm leading-relaxed">{d.reasoning}</p>

                                            <div className="flex items-center gap-2 pt-2">
                                                <span className="text-xs text-zinc-500 uppercase font-bold tracking-wider">{d.type} Decision</span>
                                                {d.episode_id && (
                                                    <span className="text-xs text-zinc-600 font-mono bg-black/30 px-2 py-0.5 rounded">
                                                        {d.episode_id}
                                                    </span>
                                                )}
                                                {d.scene_ref && (
                                                    <span className="text-xs text-amber-600 font-mono bg-amber-500/5 px-2 py-0.5 rounded">
                                                        {d.scene_ref}
                                                    </span>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}

function SparklesIcon() {
    return (
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z" /><path d="M5 3v4" /><path d="M19 17v4" /><path d="M3 5h4" /><path d="M17 19h4" /></svg>
    )
}

import { useEffect, useMemo, useState } from 'react';
import {
    AlertCircle,
    Check,
    Copy,
    Folder,
    Loader2,
    Music,
    Play,
    RefreshCw,
    Sparkles,
    Trash2,
    Wand2
} from 'lucide-react';
import { electronAPI } from '../lib/electron';

function formatDuration(seconds) {
    const value = Number(seconds) || 0;
    const min = Math.floor(value / 60);
    const sec = Math.round(value % 60);
    return `${min}:${String(sec).padStart(2, '0')}`;
}

function formatSize(bytes) {
    if (!bytes) return '0 MB';
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function getBlockAccent(id) {
    const colors = [
        'border-blue-400/40 bg-blue-500/10 text-blue-200',
        'border-emerald-400/40 bg-emerald-500/10 text-emerald-200',
        'border-amber-400/40 bg-amber-500/10 text-amber-200',
        'border-pink-400/40 bg-pink-500/10 text-pink-200',
        'border-cyan-400/40 bg-cyan-500/10 text-cyan-200',
    ];
    return colors[(id - 1) % colors.length];
}

export function AudioStudio() {
    const [scriptText, setScriptText] = useState('');
    const [projectHint, setProjectHint] = useState('');
    const [targetBlocks, setTargetBlocks] = useState(8);
    const [blocks, setBlocks] = useState([]);
    const [selectedBlockId, setSelectedBlockId] = useState(null);
    const [isPlanning, setIsPlanning] = useState(false);
    const [error, setError] = useState(null);
    const [copiedKey, setCopiedKey] = useState(null);

    const [studioTracks, setStudioTracks] = useState([]);
    const [tracksLoading, setTracksLoading] = useState(false);
    const [sunoCookies, setSunoCookies] = useState(null);
    const [generatingBlockId, setGeneratingBlockId] = useState(null);
    const [generationStatus, setGenerationStatus] = useState(null);

    const selectedBlock = useMemo(() => {
        return blocks.find(block => block.id === selectedBlockId) || blocks[0] || null;
    }, [blocks, selectedBlockId]);

    useEffect(() => {
        refreshStudioTracks();
    }, []);

    useEffect(() => {
        if (!generationStatus || generationStatus.percent <= 0 || generationStatus.percent >= 100) return;

        const interval = setInterval(async () => {
            try {
                const res = await fetch('http://localhost:8000/music/__STUDIO__/status');
                const data = await res.json();
                setGenerationStatus(data);

                if (data.percent === -1) {
                    setError(data.status || 'Suno generation failed.');
                    setGeneratingBlockId(null);
                    setGenerationStatus(null);
                    refreshStudioTracks();
                } else if (data.percent >= 100) {
                    setGeneratingBlockId(null);
                    setGenerationStatus(null);
                    refreshStudioTracks();
                }
            } catch (e) {
                setGenerationStatus({ percent: -1, status: e.message });
                setGeneratingBlockId(null);
            }
        }, 3000);

        return () => clearInterval(interval);
    }, [generationStatus]);

    const refreshStudioTracks = async () => {
        setTracksLoading(true);
        try {
            const res = await fetch('http://localhost:8000/music/studio/tracks');
            const data = await res.json();
            setStudioTracks(Array.isArray(data) ? data : []);
        } catch (e) {
            console.error('Failed to load Studio music tracks', e);
        } finally {
            setTracksLoading(false);
        }
    };

    const openStudioFolder = async () => {
        const response = await fetch('http://localhost:8000/system/paths');
        if (!response.ok) return;
        const data = await response.json();
        await fetch('http://localhost:8000/system/open_path', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: data.studio })
        });
    };

    const handlePlanMusic = async () => {
        if (!scriptText.trim()) return;

        setIsPlanning(true);
        setError(null);

        try {
            const res = await fetch('http://localhost:8000/music/script_plan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    script_text: scriptText,
                    project_hint: projectHint,
                    target_blocks: targetBlocks
                })
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Music analysis failed');
            }

            const data = await res.json();
            const nextBlocks = Array.isArray(data.blocks) ? data.blocks : [];
            setBlocks(nextBlocks);
            setSelectedBlockId(nextBlocks[0]?.id || null);
        } catch (e) {
            setError(e.message);
        } finally {
            setIsPlanning(false);
        }
    };

    const copyText = async (text, key) => {
        if (!text) return;
        await navigator.clipboard.writeText(text);
        setCopiedKey(key);
        setTimeout(() => setCopiedKey(null), 1800);
    };

    const handleGenerateBlock = async (block) => {
        if (!block?.suno_tags) return;

        let cookies = sunoCookies;
        if (!cookies) {
            cookies = await electronAPI.sunoAuth();
            if (cookies) setSunoCookies(cookies);
        }

        if (!cookies) {
            setError('Suno authentication failed or was cancelled.');
            return;
        }

        setGeneratingBlockId(block.id);
        setGenerationStatus({ percent: 1, status: 'Starting Suno generation...' });
        setError(null);

        try {
            const res = await fetch('http://localhost:8000/music/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    tags: block.suno_tags,
                    prompt: block.suno_prompt,
                    duration_seconds: block.estimated_duration_seconds || 60,
                    project_name: '__STUDIO__',
                    cookies
                })
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Generation failed to start');
            }
        } catch (e) {
            setError(e.message);
            setGeneratingBlockId(null);
            setGenerationStatus(null);
        }
    };

    const deleteTrack = async (filename) => {
        if (!confirm(`Delete ${filename}?`)) return;
        const res = await fetch(`http://localhost:8000/music/studio/tracks/${encodeURIComponent(filename)}`, {
            method: 'DELETE'
        });
        if (res.ok) refreshStudioTracks();
    };

    return (
        <div className="h-full overflow-y-auto bg-background p-8 text-primary custom-scrollbar">
            <div className="mx-auto flex max-w-7xl flex-col gap-6">
                <header className="flex flex-col gap-4 border-b border-border pb-5 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                        <h2 className="flex items-center gap-3 text-2xl font-bold text-white">
                            <Music className="text-pink-400" size={24} />
                            Music Studio
                        </h2>
                        <p className="mt-1 text-sm text-muted">
                            Paste a script, split it into semantic cues, then generate Suno-ready instrumental directions for each part.
                        </p>
                    </div>

                    <button
                        onClick={openStudioFolder}
                        className="flex items-center gap-2 self-start rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-zinc-400 transition-all hover:border-white/30 hover:text-white sm:self-auto"
                    >
                        <Folder size={14} /> Open Studio Folder
                    </button>
                </header>

                {error && (
                    <div className="flex items-center gap-3 rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
                        <AlertCircle size={18} />
                        <span>{error}</span>
                        <button onClick={() => setError(null)} className="ml-auto text-red-200/70 hover:text-white">
                            Dismiss
                        </button>
                    </div>
                )}

                <section className="grid min-h-[560px] grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.05fr)_minmax(420px,0.95fr)]">
                    <div className="flex min-h-[560px] flex-col overflow-hidden rounded-xl border border-border bg-surface shadow-lg">
                        <div className="border-b border-white/5 bg-black/20 px-5 py-4">
                            <div className="flex items-center justify-between gap-3">
                                <label className="text-xs font-bold uppercase tracking-wider text-zinc-500">Script Source</label>
                                <span className="text-xs text-zinc-600">{scriptText.trim().length.toLocaleString()} chars</span>
                            </div>
                        </div>

                        <textarea
                            value={scriptText}
                            onChange={(e) => setScriptText(e.target.value)}
                            placeholder="Paste your full video script here..."
                            className="min-h-[360px] flex-1 resize-none bg-transparent p-5 text-base leading-relaxed text-zinc-200 placeholder-zinc-700 focus:outline-none custom-scrollbar"
                        />

                        <div className="grid gap-3 border-t border-white/5 bg-black/20 p-5 md:grid-cols-[1fr_150px]">
                            <div>
                                <label className="mb-1 block text-xs font-bold uppercase tracking-wider text-zinc-500">Video Context</label>
                                <input
                                    value={projectHint}
                                    onChange={(e) => setProjectHint(e.target.value)}
                                    placeholder="e.g. Hans Landa video essay, Spider-Man character analysis"
                                    className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white placeholder-zinc-700 outline-none transition-colors focus:border-pink-500/50"
                                />
                            </div>

                            <div>
                                <label className="mb-1 block text-xs font-bold uppercase tracking-wider text-zinc-500">Blocks</label>
                                <select
                                    value={targetBlocks}
                                    onChange={(e) => setTargetBlocks(Number(e.target.value))}
                                    className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2.5 text-sm text-white outline-none transition-colors focus:border-pink-500/50"
                                >
                                    {[4, 6, 8, 10, 12, 14].map(value => (
                                        <option key={value} value={value}>{value} cues</option>
                                    ))}
                                </select>
                            </div>

                            <button
                                onClick={handlePlanMusic}
                                disabled={isPlanning || scriptText.trim().length < 80}
                                className="md:col-span-2 flex items-center justify-center gap-2 rounded-xl bg-pink-600 px-5 py-3 text-sm font-bold text-white shadow-[0_0_20px_rgba(219,39,119,0.25)] transition-all hover:bg-pink-500 disabled:cursor-not-allowed disabled:bg-zinc-800 disabled:text-zinc-600"
                            >
                                {isPlanning ? <Loader2 className="animate-spin" size={18} /> : <Wand2 size={18} />}
                                Build Music Cue Sheet
                            </button>
                        </div>
                    </div>

                    <div className="flex min-h-[560px] flex-col overflow-hidden rounded-xl border border-border bg-surface shadow-lg">
                        <div className="border-b border-white/5 bg-black/20 px-5 py-4">
                            <h3 className="flex items-center gap-2 text-sm font-bold text-white">
                                <Sparkles size={16} className="text-pink-400" />
                                Selected Cue
                            </h3>
                        </div>

                        {selectedBlock ? (
                            <div className="flex flex-1 flex-col overflow-y-auto p-5 custom-scrollbar">
                                <div className={`mb-4 rounded-lg border p-3 ${getBlockAccent(selectedBlock.id)}`}>
                                    <div className="text-xs font-bold uppercase tracking-wider opacity-70">Cue {selectedBlock.id}</div>
                                    <h4 className="mt-1 text-lg font-bold text-white">{selectedBlock.title}</h4>
                                    <p className="mt-2 text-sm leading-relaxed text-zinc-300">{selectedBlock.narrative_summary}</p>
                                </div>

                                <div className="space-y-4">
                                    <div>
                                        <div className="mb-1 text-xs font-bold uppercase tracking-wider text-zinc-500">Script Excerpt</div>
                                        <p className="rounded-lg border border-white/10 bg-black/20 p-3 text-sm leading-relaxed text-zinc-300">
                                            {selectedBlock.script_excerpt}
                                        </p>
                                    </div>

                                    <div className="grid gap-3 md:grid-cols-2">
                                        <div className="rounded-lg border border-white/10 bg-black/20 p-3">
                                            <div className="text-xs font-bold uppercase tracking-wider text-zinc-500">Emotion</div>
                                            <p className="mt-1 text-sm text-zinc-300">{selectedBlock.emotional_function}</p>
                                        </div>
                                        <div className="rounded-lg border border-white/10 bg-black/20 p-3">
                                            <div className="text-xs font-bold uppercase tracking-wider text-zinc-500">Direction</div>
                                            <p className="mt-1 text-sm text-zinc-300">{selectedBlock.musical_direction}</p>
                                        </div>
                                    </div>

                                    <div>
                                        <div className="mb-2 flex items-center justify-between">
                                            <label className="text-xs font-bold uppercase tracking-wider text-zinc-500">Suno Tags</label>
                                            <button
                                                onClick={() => copyText(selectedBlock.suno_tags, `tags-${selectedBlock.id}`)}
                                                className="flex items-center gap-1 text-xs text-zinc-500 hover:text-white"
                                            >
                                                {copiedKey === `tags-${selectedBlock.id}` ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                                                Copy
                                            </button>
                                        </div>
                                        <textarea
                                            value={selectedBlock.suno_tags}
                                            readOnly
                                            className="h-20 w-full resize-none rounded-lg border border-white/10 bg-black/30 p-3 text-sm text-pink-100 outline-none custom-scrollbar"
                                        />
                                    </div>

                                    <div>
                                        <div className="mb-2 flex items-center justify-between">
                                            <label className="text-xs font-bold uppercase tracking-wider text-zinc-500">Suno Prompt</label>
                                            <button
                                                onClick={() => copyText(selectedBlock.suno_prompt, `prompt-${selectedBlock.id}`)}
                                                className="flex items-center gap-1 text-xs text-zinc-500 hover:text-white"
                                            >
                                                {copiedKey === `prompt-${selectedBlock.id}` ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                                                Copy
                                            </button>
                                        </div>
                                        <textarea
                                            value={selectedBlock.suno_prompt}
                                            readOnly
                                            className="h-28 w-full resize-none rounded-lg border border-white/10 bg-black/30 p-3 text-sm leading-relaxed text-zinc-200 outline-none custom-scrollbar"
                                        />
                                    </div>
                                </div>

                                <div className="mt-auto pt-5">
                                    {generationStatus && generatingBlockId === selectedBlock.id && (
                                        <div className="mb-3 rounded-lg border border-blue-500/20 bg-blue-500/10 p-3 text-sm text-blue-200">
                                            <div className="mb-2 flex items-center justify-between gap-3">
                                                <span>{generationStatus.status}</span>
                                                <span className="font-mono text-xs">{generationStatus.percent}%</span>
                                            </div>
                                            <div className="h-1.5 overflow-hidden rounded-full bg-black/40">
                                                <div
                                                    className="h-full bg-blue-400 transition-all"
                                                    style={{ width: `${Math.max(0, Math.min(100, generationStatus.percent))}%` }}
                                                />
                                            </div>
                                        </div>
                                    )}

                                    <button
                                        onClick={() => handleGenerateBlock(selectedBlock)}
                                        disabled={Boolean(generatingBlockId)}
                                        className="flex w-full items-center justify-center gap-2 rounded-xl bg-pink-600 px-5 py-3 text-sm font-bold text-white transition-colors hover:bg-pink-500 disabled:cursor-not-allowed disabled:bg-zinc-800 disabled:text-zinc-600"
                                    >
                                        {generatingBlockId === selectedBlock.id ? <Loader2 className="animate-spin" size={18} /> : <Music size={18} />}
                                        {generatingBlockId === selectedBlock.id ? 'Generating Track...' : `Generate ${formatDuration(selectedBlock.estimated_duration_seconds)} Track via Suno`}
                                    </button>
                                </div>
                            </div>
                        ) : (
                            <div className="flex flex-1 items-center justify-center p-8 text-center text-muted">
                                <div>
                                    <Music size={48} className="mx-auto mb-4 opacity-20" />
                                    <p>Generate a cue sheet to see Suno prompts here.</p>
                                </div>
                            </div>
                        )}
                    </div>
                </section>

                <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
                    <div className="rounded-xl border border-border bg-surface shadow-lg">
                        <div className="flex items-center justify-between border-b border-white/5 bg-black/20 px-5 py-4">
                            <h3 className="font-bold text-white">Cue Sheet</h3>
                            <span className="text-xs text-muted">{blocks.length} blocks</span>
                        </div>

                        {blocks.length === 0 ? (
                            <div className="p-10 text-center text-sm text-muted">No cues generated yet.</div>
                        ) : (
                            <div className="grid gap-3 p-4 md:grid-cols-2">
                                {blocks.map(block => (
                                    <button
                                        key={block.id}
                                        onClick={() => setSelectedBlockId(block.id)}
                                        className={`rounded-lg border p-4 text-left transition-all hover:border-white/30 ${
                                            selectedBlock?.id === block.id
                                                ? 'border-pink-400/50 bg-pink-500/10'
                                                : 'border-white/10 bg-black/20 hover:bg-white/5'
                                        }`}
                                    >
                                        <div className="mb-2 flex items-center justify-between gap-2">
                                            <span className="text-xs font-mono text-zinc-500">Cue {block.id}</span>
                                            <span className="text-xs text-zinc-500">{formatDuration(block.estimated_duration_seconds)}</span>
                                        </div>
                                        <h4 className="line-clamp-1 font-bold text-white">{block.title}</h4>
                                        <p className="mt-2 line-clamp-3 text-sm leading-relaxed text-zinc-400">{block.narrative_summary}</p>
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>

                    <div className="rounded-xl border border-border bg-surface shadow-lg">
                        <div className="flex items-center justify-between border-b border-white/5 bg-black/20 px-5 py-4">
                            <h3 className="font-bold text-white">Generated Tracks</h3>
                            <button onClick={refreshStudioTracks} className="text-zinc-500 hover:text-white">
                                <RefreshCw size={15} className={tracksLoading ? 'animate-spin' : ''} />
                            </button>
                        </div>

                        {studioTracks.length === 0 ? (
                            <div className="p-10 text-center text-sm text-muted">No Studio music tracks yet.</div>
                        ) : (
                            <div className="max-h-[520px] space-y-3 overflow-y-auto p-4 custom-scrollbar">
                                {studioTracks.map(track => (
                                    <div key={track.filename} className="rounded-lg border border-white/10 bg-black/20 p-3">
                                        <div className="mb-3 flex items-start gap-3">
                                            <div className="mt-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-pink-500/10 text-pink-300">
                                                <Play size={15} />
                                            </div>
                                            <div className="min-w-0 flex-1">
                                                <div className="truncate text-sm font-bold text-white">{track.filename}</div>
                                                <div className="mt-0.5 text-xs text-zinc-500">{formatSize(track.size)}</div>
                                            </div>
                                            <button
                                                onClick={() => deleteTrack(track.filename)}
                                                className="rounded p-1 text-zinc-600 hover:bg-red-500/10 hover:text-red-300"
                                            >
                                                <Trash2 size={14} />
                                            </button>
                                        </div>
                                        <audio
                                            controls
                                            preload="none"
                                            className="h-8 w-full"
                                            src={`http://localhost:8000/music/studio/tracks/${encodeURIComponent(track.filename)}/play`}
                                        />
                                        {track.tags && (
                                            <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-zinc-500">{track.tags}</p>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </section>
            </div>
        </div>
    );
}

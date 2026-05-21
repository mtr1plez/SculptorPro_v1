import { useState, useEffect, useRef } from 'react';
import { ArrowLeft, Clock, Plus, Trash2, Film, CheckCircle, FolderOpen, Pencil, Sparkles, Loader2, List, Brain, Users, FileText, Upload, X } from 'lucide-react';
import { DecisionList } from './DecisionList';
import { electronAPI } from '../lib/electron';

export function SourceDetail({ source, onBack }) {
    const [episodes, setEpisodes] = useState([]);
    const [details, setDetails] = useState(source);
    const [loading, setLoading] = useState(true);
    const [activeTab, setActiveTab] = useState('episodes'); // 'episodes' | 'characters' | 'decisions'
    const [characters, setCharacters] = useState([]);
    const [charsLoading, setCharsLoading] = useState(false);

    // Add Modal State
    const [isAddOpen, setIsAddOpen] = useState(false);
    const [newEpName, setNewEpName] = useState('');
    const [newEpStart, setNewEpStart] = useState('');
    const [newEpEnd, setNewEpEnd] = useState('');
    const [usePrevEnd, setUsePrevEnd] = useState(false);

    // Edit Modal State
    const [isEditOpen, setIsEditOpen] = useState(false);
    const [editEpisode, setEditEpisode] = useState(null);
    const [editName, setEditName] = useState('');
    const [editStart, setEditStart] = useState('');
    const [editEnd, setEditEnd] = useState('');

    // Auto-segmentation State
    const [autoSegLoading, setAutoSegLoading] = useState(false);
    const [autoSegStatus, setAutoSegStatus] = useState('');
    const [autoSegPercent, setAutoSegPercent] = useState(0);
    const [showAutoConfirm, setShowAutoConfirm] = useState(false);
    const [autoSegStart, setAutoSegStart] = useState('00:00:00');
    const [autoSegEnd, setAutoSegEnd] = useState('');
    const pollRef = useRef(null);

    // Screenplay State
    const [screenplayStatus, setScreenplayStatus] = useState(null);
    const [screenplayUploading, setScreenplayUploading] = useState(false);
    const screenplayInputRef = useRef(null);

    const fetchCharacters = async () => {
        setCharsLoading(true);
        try {
            const res = await fetch(`http://localhost:8000/library/${source.alias}/characters`);
            if (res.ok) {
                const data = await res.json();
                setCharacters(data);
            }
        } catch (e) {
            console.error("Failed to fetch characters", e);
        } finally {
            setCharsLoading(false);
        }
    };

    useEffect(() => {
        fetchEpisodes();
        fetchDetails();
        fetchCharacters();
        fetchScreenplayStatus();
    }, [source.alias]);

    useEffect(() => {
        return electronAPI.onSelectedFile((path) => {
            updateSourcePath(path);
        });
    }, [source.alias]);

    useEffect(() => {
        if (isAddOpen && usePrevEnd && episodes.length > 0) {
            const lastEnd = Math.max(...episodes.map(e => e.end_time));
            const newStartSec = lastEnd + 1;
            setNewEpStart(fmtTime(newStartSec));
        }
    }, [isAddOpen, usePrevEnd, episodes]);

    const fetchDetails = async () => {
        try {
            const res = await fetch(`http://localhost:8000/library/${source.alias}/details`);
            if (res.ok) {
                const data = await res.json();
                setDetails(prev => ({ ...prev, ...data }));
            }
        } catch (e) { console.error("Failed details fetch", e); }
    };

    const fetchEpisodes = async () => {
        try {
            const res = await fetch(`http://localhost:8000/library/${source.alias}/episodes`);
            if (res.ok) {
                const data = await res.json();
                setEpisodes(data);
            }
        } catch (e) {
            console.error("Failed to fetch episodes", e);
        } finally {
            setLoading(false);
        }
    };

    const fetchScreenplayStatus = async () => {
        try {
            const res = await fetch(`http://localhost:8000/library/${source.alias}/screenplay/status`);
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

        setScreenplayUploading(true);
        try {
            const formData = new FormData();
            formData.append('file', file);

            const res = await fetch(`http://localhost:8000/library/${source.alias}/screenplay`, {
                method: 'POST',
                body: formData
            });
            if (res.ok) {
                fetchScreenplayStatus();
            }
        } catch (e) {
            console.error("Failed to upload screenplay", e);
        } finally {
            setScreenplayUploading(false);
            if (screenplayInputRef.current) screenplayInputRef.current.value = '';
        }
    };

    const handleScreenplayDelete = async () => {
        try {
            await fetch(`http://localhost:8000/library/${source.alias}/screenplay`, { method: 'DELETE' });
            fetchScreenplayStatus();
        } catch (e) {
            console.error("Failed to delete screenplay", e);
        }
    };

    const handleLocateFile = async () => {
        try {
            const path = await electronAPI.openFileDialog();
            if (path) updateSourcePath(path);
        } catch (error) {
            alert(`File picker is unavailable: ${error.message}`);
        }
    };

    const updateSourcePath = async (newPath) => {
        try {
            const res = await fetch(`http://localhost:8000/library/${source.alias}/locate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ new_path: newPath })
            });
            if (res.ok) {
                fetchDetails();
            }
        } catch (e) { alert("Failed to update path"); }
    };

    // Helper: HH:MM:SS -> Seconds
    const toSeconds = (str) => {
        if (typeof str !== 'string') return 0;
        const p = str.split(':').map(Number);
        let sec = 0;
        if (p.length === 3) sec = p[0] * 3600 + p[1] * 60 + p[2];
        else if (p.length === 2) sec = p[0] * 60 + p[1];
        else sec = p[0];
        return sec;
    };

    const handleAddEpisode = async () => {
        if (!newEpName) return;

        const payload = {
            name: newEpName,
            start_time: toSeconds(newEpStart),
            end_time: toSeconds(newEpEnd)
        };

        try {
            const res = await fetch(`http://localhost:8000/library/${source.alias}/episodes`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (res.ok) {
                setIsAddOpen(false);
                setNewEpName('');
                setNewEpStart('');
                setNewEpEnd('');
                fetchEpisodes();
            }
        } catch (e) {
            alert("Failed to add episode");
        }
    };

    const handleDeleteEpisode = async (id) => {
        if (!confirm("Delete this episode?")) return;
        try {
            await fetch(`http://localhost:8000/library/${source.alias}/episodes/${id}`, { method: 'DELETE' });
            fetchEpisodes();
        } catch (e) {
            alert("Failed to delete");
        }
    };

    const openEditModal = (ep) => {
        setEditEpisode(ep);
        setEditName(ep.name);
        setEditStart(fmtTime(ep.start_time));
        setEditEnd(fmtTime(ep.end_time));
        setIsEditOpen(true);
    };

    const handleUpdateEpisode = async () => {
        if (!editEpisode) return;

        const payload = {
            name: editName,
            start_time: toSeconds(editStart),
            end_time: toSeconds(editEnd)
        };

        try {
            const res = await fetch(`http://localhost:8000/library/${source.alias}/episodes/${editEpisode.id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (res.ok) {
                setIsEditOpen(false);
                setEditEpisode(null);
                fetchEpisodes();
            } else {
                alert("Failed to update episode");
            }
        } catch (e) {
            alert("Failed to update episode");
        }
    };

    // === AUTO-SEGMENTATION ===
    const handleAutoSegment = async (force = false) => {
        const startSeconds = toSeconds(autoSegStart);
        const endSeconds = toSeconds(autoSegEnd);
        if (endSeconds <= startSeconds) {
            alert('Auto-segmentation end time must be after start time.');
            return;
        }

        setShowAutoConfirm(false);
        setAutoSegLoading(true);
        setAutoSegStatus('Starting...');
        setAutoSegPercent(0);

        // Trigger API
        try {
            await fetch(`http://localhost:8000/library/${source.alias}/auto-episodes`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    force,
                    start_time: startSeconds,
                    end_time: endSeconds
                })
            });
        } catch (e) {
            setAutoSegLoading(false);
            setAutoSegStatus('Failed to start');
            alert('Failed to start auto-segmentation');
            return;
        }

        // Poll for progress every 2 seconds
        const pollId = setInterval(async () => {
            try {
                const res = await fetch(`http://localhost:8000/library/${source.alias}/auto-episodes/status`);
                if (res.ok) {
                    const data = await res.json();
                    if (data.percent >= 0) {
                        setAutoSegPercent(data.percent);
                        setAutoSegStatus(data.status || '');
                    }
                    if (data.percent >= 100) {
                        clearInterval(pollId);
                        setAutoSegLoading(false);
                        fetchEpisodes();
                    }
                    if (data.status && data.status.startsWith('Error')) {
                        clearInterval(pollId);
                        setAutoSegLoading(false);
                    }
                }
            } catch {
                // Polling can fail transiently while the backend task spins up.
            }
        }, 2000);

        // Store interval ID for cleanup
        pollRef.current = pollId;
    };

    const onAutoSegClick = () => {
        setAutoSegStart('00:00:00');
        setAutoSegEnd(fmtTime(details?.duration || 0));
        setShowAutoConfirm(true);
    };

    // Cleanup polling on unmount
    useEffect(() => {
        return () => {
            if (pollRef.current) {
                clearInterval(pollRef.current);
            }
        };
    }, []);

    const fmtTime = (s) => {
        if (!s && s !== 0) return "00:00:00";
        const h = Math.floor(s / 3600);
        const m = Math.floor((s % 3600) / 60);
        const sec = Math.floor(s % 60);
        return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`;
    };

    const formatDuration = (s) => {
        if (!s) return "Unknown Duration";
        const h = Math.floor(s / 3600);
        const m = Math.floor((s % 3600) / 60);
        if (h > 0) return `${h}h ${m}m`;
        return `${m}m`;
    };

    return (
        <div className="flex flex-col h-full bg-background text-primary animate-in fade-in slide-in-from-right-4 duration-300">

            {/* HEADER */}
            <div className="bg-surface border-b border-border p-6 shadow-md flex items-start gap-6 relative overflow-hidden">
                {details.thumbnail && (
                    <div
                        className="absolute inset-0 opacity-10 bg-cover bg-center blur-2xl pointer-events-none"
                        style={{ backgroundImage: `url(${details.thumbnail})` }}
                    ></div>
                )}

                <button
                    onClick={onBack}
                    className="z-10 p-2 hover:bg-white/10 rounded-full transition-colors"
                >
                    <ArrowLeft size={24} />
                </button>

                <div className="z-10 flex gap-6 w-full max-w-4xl">
                    <div className="w-32 h-48 bg-black rounded-lg shadow-2xl overflow-hidden flex-shrink-0 border border-white/10">
                        {details.thumbnail ? (
                            <img src={details.thumbnail} className="w-full h-full object-cover" />
                        ) : (
                            <Film className="w-12 h-12 m-auto text-zinc-700 mt-16" />
                        )}
                    </div>

                    <div className="flex-1 pt-2">
                        <h1 className="text-3xl font-bold text-white mb-2">{details.alias}</h1>
                        <div className="flex items-center gap-4 text-sm text-muted">
                            <span className="flex items-center gap-1">
                                <Clock size={14} />
                                {formatDuration(details.duration)}
                            </span>
                            <span className="flex items-center gap-1"><CheckCircle size={14} className="text-green-500" /> Indexed</span>

                            <button
                                onClick={handleLocateFile}
                                className="flex items-center gap-2 px-2 py-1 bg-white/5 hover:bg-white/10 rounded text-xs transition-colors border border-transparent hover:border-white/20"
                                title="Locate File"
                            >
                                <FolderOpen size={12} className="text-accent" />
                                <span className="font-mono truncate max-w-[300px]">{details.path || "Unknown path"}</span>
                            </button>
                        </div>

                        <p className="mt-4 text-gray-400 max-w-xl text-sm leading-relaxed">
                            Manage manual segmentation for this film based on plot points.
                        </p>
                    </div>
                </div>
            </div>

            {/* CONTENT */}
            <div className="flex-1 p-8 overflow-y-auto">
                <div className="max-w-4xl mx-auto">
                    <div className="flex justify-between items-center mb-6">
                        <h2 className="text-xl font-bold flex items-center gap-2">
                            Episodes
                            <span className="text-sm font-normal text-muted bg-surface px-2 py-1 rounded-full border border-border">
                                {episodes.length}
                            </span>
                        </h2>
                        <div className="flex items-center gap-3">
                            {autoSegLoading && (
                                <div className="flex items-center gap-2 text-sm text-purple-300 bg-purple-500/10 border border-purple-500/20 px-3 py-2 rounded-lg">
                                    <Loader2 size={14} className="animate-spin" />
                                    <span>{autoSegStatus || 'Processing...'}</span>
                                    {autoSegPercent > 0 && autoSegPercent < 100 && (
                                        <span className="font-mono text-xs opacity-60">{autoSegPercent}%</span>
                                    )}
                                </div>
                            )}
                            <button
                                onClick={onAutoSegClick}
                                disabled={autoSegLoading}
                                className="bg-purple-600 hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed text-white px-4 py-2 rounded-lg flex items-center gap-2 text-sm font-medium shadow-lg shadow-purple-500/20 transition-all hover:scale-105"
                                title="Auto-detect episodes using AI"
                            >
                                <Sparkles size={16} /> Auto-Segment
                            </button>
                            <button
                                onClick={() => setIsAddOpen(true)}
                                className="bg-accent hover:bg-blue-600 text-white px-4 py-2 rounded-lg flex items-center gap-2 text-sm font-medium shadow-lg shadow-blue-500/20 transition-all hover:scale-105"
                            >
                                <Plus size={16} /> Add Episode
                            </button>
                        </div>
                    </div>

                    {/* SCREENPLAY STATUS BAR */}
                    <div className="mb-4 flex items-center gap-3 p-3 rounded-lg border border-white/5 bg-surface/50">
                        <div className={`p-1.5 rounded-md ${screenplayStatus?.exists ? 'bg-amber-500/15' : 'bg-white/5'}`}>
                            <FileText size={16} className={screenplayStatus?.exists ? 'text-amber-400' : 'text-zinc-600'} />
                        </div>
                        <div className="flex-1 min-w-0">
                            {screenplayStatus?.exists ? (
                                <div className="flex items-center gap-2">
                                    <span className="text-sm text-amber-300 font-medium">Screenplay loaded</span>
                                    <span className="text-xs text-zinc-500">
                                        {screenplayStatus.lines?.toLocaleString()} lines · {screenplayStatus.chars?.toLocaleString()} chars
                                    </span>
                                </div>
                            ) : (
                                <span className="text-sm text-zinc-500">No screenplay — will use scene data only for segmentation</span>
                            )}
                        </div>
                        <div className="flex items-center gap-2">
                            {screenplayStatus?.exists && (
                                <button
                                    onClick={handleScreenplayDelete}
                                    className="p-1.5 text-zinc-500 hover:text-red-400 hover:bg-red-500/10 rounded-md transition-colors"
                                    title="Remove screenplay"
                                >
                                    <X size={14} />
                                </button>
                            )}
                            <input
                                ref={screenplayInputRef}
                                type="file"
                                accept=".txt,.pdf"
                                className="hidden"
                                onChange={handleScreenplayUpload}
                            />
                            <button
                                onClick={() => screenplayInputRef.current?.click()}
                                disabled={screenplayUploading}
                                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all flex items-center gap-1.5 ${screenplayStatus?.exists
                                        ? 'bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white border border-white/10'
                                        : 'bg-amber-600/80 hover:bg-amber-600 text-white shadow-sm'
                                    }`}
                            >
                                {screenplayUploading ? (
                                    <Loader2 size={12} className="animate-spin" />
                                ) : (
                                    <Upload size={12} />
                                )}
                                {screenplayStatus?.exists ? 'Replace' : 'Upload Script'}
                            </button>
                        </div>
                    </div>

                    {/* TABS */}
                    <div className="flex gap-4 mb-4 border-b border-white/5 pb-1">
                        <button
                            onClick={() => setActiveTab('episodes')}
                            className={`px-4 py-2 text-sm font-medium transition-colors flex items-center gap-2 border-b-2 ${activeTab === 'episodes'
                                ? 'text-white border-purple-500'
                                : 'text-muted hover:text-white border-transparent'
                                }`}
                        >
                            <List size={16} /> Episodes
                        </button>
                        <button
                            onClick={() => setActiveTab('characters')}
                            className={`px-4 py-2 text-sm font-medium transition-colors flex items-center gap-2 border-b-2 ${activeTab === 'characters'
                                ? 'text-white border-purple-500'
                                : 'text-muted hover:text-white border-transparent'
                                }`}
                        >
                            <Users size={16} /> Characters
                            {characters.length > 0 && (
                                <span className="text-xs bg-white/10 px-1.5 py-0.5 rounded-full">{characters.length}</span>
                            )}
                        </button>
                        <button
                            onClick={() => setActiveTab('decisions')}
                            className={`px-4 py-2 text-sm font-medium transition-colors flex items-center gap-2 border-b-2 ${activeTab === 'decisions'
                                ? 'text-white border-purple-500'
                                : 'text-muted hover:text-white border-transparent'
                                }`}
                        >
                            <Brain size={16} /> Decisions
                        </button>
                    </div>

                    {activeTab === 'decisions' ? (
                        <DecisionList alias={source.alias} />
                    ) : activeTab === 'characters' ? (
                        charsLoading ? (
                            <div className="text-center py-20 text-muted">Loading characters...</div>
                        ) : characters.length === 0 ? (
                            <div className="text-center py-20 border border-dashed border-border rounded-xl bg-surface/30">
                                <Users size={32} className="mx-auto text-zinc-600 mb-3" />
                                <p className="text-muted">No characters detected for this film.</p>
                                <p className="text-xs text-zinc-600 mt-1">Characters are detected during the ingest process.</p>
                            </div>
                        ) : (
                            <div className="bg-surface border border-border rounded-xl shadow-sm overflow-hidden">
                                <table className="w-full text-left">
                                    <thead className="bg-black/20 text-xs uppercase text-muted font-medium border-b border-white/5">
                                        <tr>
                                            <th className="px-6 py-4 w-12">#</th>
                                            <th className="px-6 py-4">Character</th>
                                            <th className="px-6 py-4 text-center">Scenes</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-white/5">
                                        {characters.map((char, i) => (
                                            <tr key={char.name} className="hover:bg-white/5 transition-colors">
                                                <td className="px-6 py-4 text-muted text-sm">{i + 1}</td>
                                                <td className="px-6 py-4 font-medium text-white">{char.name}</td>
                                                <td className="px-6 py-4 text-center">
                                                    <span className="bg-purple-500/20 text-purple-300 px-3 py-1 rounded-full text-sm font-mono">
                                                        {char.scene_count}
                                                    </span>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )
                    ) : (
                        loading ? (
                            <div className="text-center py-20 text-muted">Loading episodes...</div>
                        ) : episodes.length === 0 ? (
                            <div className="text-center py-20 border border-dashed border-border rounded-xl bg-surface/30">
                                <p className="text-muted mb-2">No episodes defined yet.</p>
                                <button onClick={() => setIsAddOpen(true)} className="text-accent hover:underline text-sm">Create the first one</button>
                            </div>
                        ) : (
                            <div className="bg-surface border border-border rounded-xl shadow-sm overflow-hidden">
                                <table className="w-full text-left">
                                    <thead className="bg-black/20 text-xs uppercase text-muted font-medium border-b border-white/5">
                                        <tr>
                                            <th className="px-6 py-4 w-12">#</th>
                                            <th className="px-6 py-4">Title</th>
                                            <th className="px-6 py-4 font-mono text-center">Start</th>
                                            <th className="px-6 py-4 font-mono text-center">End</th>
                                            <th className="px-6 py-4 font-mono text-center">Duration</th>
                                            <th className="px-6 py-4 text-right">Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-white/5">
                                        {episodes.map((ep, i) => (
                                            <tr key={ep.id} className="hover:bg-white/5 transition-colors group">
                                                <td className="px-6 py-4 text-muted text-sm">{i + 1}</td>
                                                <td className="px-6 py-4 font-medium text-white">{ep.name}</td>
                                                <td className="px-6 py-4 font-mono text-sm text-center text-blue-300">{fmtTime(ep.start_time)}</td>
                                                <td className="px-6 py-4 font-mono text-sm text-center text-blue-300">{fmtTime(ep.end_time)}</td>
                                                <td className="px-6 py-4 font-mono text-sm text-center text-muted">
                                                    {fmtTime(ep.end_time - ep.start_time)}
                                                </td>
                                                <td className="px-6 py-4 text-right flex gap-1 justify-end">
                                                    <button
                                                        onClick={() => openEditModal(ep)}
                                                        className="p-2 text-muted hover:text-blue-400 hover:bg-blue-500/10 rounded-md transition-colors opacity-0 group-hover:opacity-100"
                                                        title="Edit Episode"
                                                    >
                                                        <Pencil size={16} />
                                                    </button>
                                                    <button
                                                        onClick={() => handleDeleteEpisode(ep.id)}
                                                        className="p-2 text-muted hover:text-red-400 hover:bg-red-500/10 rounded-md transition-colors opacity-0 group-hover:opacity-100"
                                                        title="Delete Episode"
                                                    >
                                                        <Trash2 size={16} />
                                                    </button>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )
                    )}
                </div>
            </div>

            {/* ADD MODAL */}
            {
                isAddOpen && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
                        <div className="bg-surface border border-border p-6 rounded-xl w-full max-w-md shadow-2xl scale-100 animate-in zoom-in-95 duration-200">
                            <h3 className="text-xl font-bold mb-6 text-white">Add New Episode</h3>

                            <div className="space-y-6">
                                <div>
                                    <label className="block text-xs font-medium text-muted uppercase mb-1">Episode Name</label>
                                    <input
                                        autoFocus
                                        type="text"
                                        className="w-full bg-black/40 border border-border rounded-lg px-3 py-3 text-white focus:outline-none focus:border-accent"
                                        placeholder="e.g. Battle of Arrakeen"
                                        value={newEpName}
                                        onChange={(e) => setNewEpName(e.target.value)}
                                    />
                                </div>

                                <div className="grid grid-cols-2 gap-4">
                                    <div>
                                        <label className="block text-xs font-medium text-muted uppercase mb-1">Start Time</label>
                                        <input
                                            type="text"
                                            className={`w-full bg-black/40 border border-border rounded-lg px-3 py-3 text-white font-mono focus:outline-none focus:border-accent text-center ${usePrevEnd ? 'opacity-50 cursor-not-allowed' : ''}`}
                                            placeholder="00:00:00"
                                            value={newEpStart}
                                            onChange={(e) => setNewEpStart(e.target.value)}
                                            disabled={usePrevEnd}
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-xs font-medium text-muted uppercase mb-1">End Time</label>
                                        <input
                                            type="text"
                                            className="w-full bg-black/40 border border-border rounded-lg px-3 py-3 text-white font-mono focus:outline-none focus:border-accent text-center"
                                            placeholder="00:05:30"
                                            value={newEpEnd}
                                            onChange={(e) => setNewEpEnd(e.target.value)}
                                        />
                                    </div>
                                </div>

                                <div className="flex items-center gap-3 px-1">
                                    <input
                                        type="checkbox"
                                        id="autoStart"
                                        checked={usePrevEnd}
                                        onChange={e => setUsePrevEnd(e.target.checked)}
                                        className="w-4 h-4 rounded border-zinc-600 bg-zinc-800 text-accent focus:ring-accent cursor-pointer"
                                    />
                                    <label htmlFor="autoStart" className="text-sm text-zinc-400 select-none cursor-pointer">
                                        Start 1s after previous episode
                                    </label>
                                </div>
                            </div>

                            <div className="flex justify-end gap-3 mt-8 pt-4 border-t border-white/5">
                                <button
                                    onClick={() => setIsAddOpen(false)}
                                    className="px-4 py-2 text-sm text-zinc-400 hover:text-white transition-colors"
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={handleAddEpisode}
                                    disabled={!newEpName}
                                    className="bg-accent hover:bg-blue-600 text-white px-6 py-2 rounded-lg text-sm font-bold transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                >
                                    Create Episode
                                </button>
                            </div>
                        </div>
                    </div>
                )
            }

            {/* EDIT MODAL */}
            {
                isEditOpen && editEpisode && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
                        <div className="bg-surface border border-border p-6 rounded-xl w-full max-w-md shadow-2xl scale-100 animate-in zoom-in-95 duration-200">
                            <h3 className="text-xl font-bold mb-6 text-white">Edit Episode</h3>

                            <div className="space-y-6">
                                <div>
                                    <label className="block text-xs font-medium text-muted uppercase mb-1">Episode Name</label>
                                    <input
                                        autoFocus
                                        type="text"
                                        className="w-full bg-black/40 border border-border rounded-lg px-3 py-3 text-white focus:outline-none focus:border-accent"
                                        value={editName}
                                        onChange={(e) => setEditName(e.target.value)}
                                    />
                                </div>

                                <div className="grid grid-cols-2 gap-4">
                                    <div>
                                        <label className="block text-xs font-medium text-muted uppercase mb-1">Start Time</label>
                                        <input
                                            type="text"
                                            className="w-full bg-black/40 border border-border rounded-lg px-3 py-3 text-white font-mono focus:outline-none focus:border-accent text-center"
                                            placeholder="00:00:00"
                                            value={editStart}
                                            onChange={(e) => setEditStart(e.target.value)}
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-xs font-medium text-muted uppercase mb-1">End Time</label>
                                        <input
                                            type="text"
                                            className="w-full bg-black/40 border border-border rounded-lg px-3 py-3 text-white font-mono focus:outline-none focus:border-accent text-center"
                                            placeholder="00:05:30"
                                            value={editEnd}
                                            onChange={(e) => setEditEnd(e.target.value)}
                                        />
                                    </div>
                                </div>
                            </div>

                            <div className="flex justify-end gap-3 mt-8 pt-4 border-t border-white/5">
                                <button
                                    onClick={() => { setIsEditOpen(false); setEditEpisode(null); }}
                                    className="px-4 py-2 text-sm text-zinc-400 hover:text-white transition-colors"
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={handleUpdateEpisode}
                                    disabled={!editName}
                                    className="bg-accent hover:bg-blue-600 text-white px-6 py-2 rounded-lg text-sm font-bold transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                >
                                    Save Changes
                                </button>
                            </div>
                        </div>
                    </div>
                )
            }

            {/* AUTO-SEGMENT CONFIG MODAL */}
            {
                showAutoConfirm && (
                    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
                        <div className="bg-surface border border-border p-6 rounded-xl w-full max-w-lg shadow-2xl animate-in zoom-in-95 duration-200">
                            <div className="flex items-center gap-3 mb-4">
                                <div className="p-2 bg-yellow-500/10 rounded-lg">
                                    <Sparkles size={20} className="text-yellow-400" />
                                </div>
                                <h3 className="text-xl font-bold text-white">Auto-Segment Range</h3>
                            </div>
                            <p className="text-zinc-400 text-sm mb-5">
                                Set the real film content range. Logos, intro cards, and credits outside this range will be ignored, and a separate <span className="text-white font-medium">Full Movie</span> episode will be added for the same range.
                            </p>

                            <div className="grid grid-cols-2 gap-4 mb-5">
                                <div>
                                    <label className="block text-xs font-medium text-muted uppercase mb-1">Film Start</label>
                                    <input
                                        type="text"
                                        className="w-full bg-black/40 border border-border rounded-lg px-3 py-3 text-white font-mono focus:outline-none focus:border-accent text-center"
                                        placeholder="00:00:00"
                                        value={autoSegStart}
                                        onChange={(e) => setAutoSegStart(e.target.value)}
                                    />
                                </div>
                                <div>
                                    <label className="block text-xs font-medium text-muted uppercase mb-1">Film End</label>
                                    <input
                                        type="text"
                                        className="w-full bg-black/40 border border-border rounded-lg px-3 py-3 text-white font-mono focus:outline-none focus:border-accent text-center"
                                        placeholder="02:00:00"
                                        value={autoSegEnd}
                                        onChange={(e) => setAutoSegEnd(e.target.value)}
                                    />
                                </div>
                            </div>

                            {episodes.length > 0 && (
                                <p className="text-zinc-400 text-sm mb-6">
                                    This source already has <span className="text-white font-medium">{episodes.length} episodes</span>. AI auto-segmentation will <span className="text-yellow-400">replace all existing episodes</span>.
                                </p>
                            )}
                            <div className="flex justify-end gap-3 pt-4 border-t border-white/5">
                                <button
                                    onClick={() => setShowAutoConfirm(false)}
                                    className="px-4 py-2 text-sm text-zinc-400 hover:text-white transition-colors"
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={() => handleAutoSegment(episodes.length > 0)}
                                    className="bg-purple-600 hover:bg-purple-700 text-white px-6 py-2 rounded-lg text-sm font-bold transition-colors"
                                >
                                    {episodes.length > 0 ? 'Replace & Auto-Segment' : 'Auto-Segment'}
                                </button>
                            </div>
                        </div>
                    </div>
                )
            }

        </div >
    );
}

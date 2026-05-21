import { useState, useEffect } from 'react';
import { X, Film, Loader2, ChevronDown, ChevronRight, Users, List, Trash2, FolderPlus } from 'lucide-react';

export function GroupModal({ isOpen, onClose, onSaved, editGroup = null }) {
    const [groupName, setGroupName] = useState('');
    const [items, setItems] = useState([]);
    const [library, setLibrary] = useState([]);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [expandedSources, setExpandedSources] = useState({});
    const [sourceEpisodes, setSourceEpisodes] = useState({});
    const [sourceCharacters, setSourceCharacters] = useState({});
    const [sourceTab, setSourceTab] = useState({});

    useEffect(() => {
        if (!isOpen) return;
        setLoading(true);

        if (editGroup) {
            setGroupName(editGroup.name);
            setItems(editGroup.items || []);
        } else {
            setGroupName('');
            setItems([]);
        }

        fetch('http://localhost:8000/library')
            .then(r => r.json())
            .then(data => {
                setLibrary(data.filter(m => m.ready));
                setLoading(false);
            })
            .catch(() => setLoading(false));
    }, [isOpen, editGroup]);

    const toggleSource = async (alias) => {
        if (expandedSources[alias]) {
            setExpandedSources(prev => ({ ...prev, [alias]: false }));
            return;
        }
        setExpandedSources(prev => ({ ...prev, [alias]: true }));
        if (!sourceEpisodes[alias]) {
            fetch(`http://localhost:8000/library/${encodeURIComponent(alias)}/episodes`)
                .then(r => r.ok ? r.json() : [])
                .then(eps => setSourceEpisodes(prev => ({ ...prev, [alias]: eps })))
                .catch(() => { });
        }
        if (!sourceCharacters[alias]) {
            fetch(`http://localhost:8000/library/${encodeURIComponent(alias)}/characters`)
                .then(r => r.ok ? r.json() : [])
                .then(chars => setSourceCharacters(prev => ({ ...prev, [alias]: chars })))
                .catch(() => { });
        }
        if (!sourceTab[alias]) {
            setSourceTab(prev => ({ ...prev, [alias]: 'episodes' }));
        }
    };

    const addItem = (sourceAlias, type, name, episodeId = null) => {
        const exists = items.some(it =>
            it.source_alias === sourceAlias && it.type === type && it.name === name
        );
        if (exists) return;
        setItems(prev => [...prev, {
            source_alias: sourceAlias,
            type,
            name,
            episode_id: episodeId
        }]);
    };

    const removeItem = (index) => {
        setItems(prev => prev.filter((_, i) => i !== index));
    };

    const handleSave = async () => {
        if (!groupName.trim() || items.length === 0) return;
        setSaving(true);

        try {
            const url = editGroup
                ? `http://localhost:8000/groups/${editGroup.id}`
                : 'http://localhost:8000/groups';
            const method = editGroup ? 'PUT' : 'POST';

            const res = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: groupName.trim(), items })
            });

            if (res.ok) {
                if (onSaved) onSaved();
                onClose();
            } else {
                alert('Failed to save group');
            }
        } catch (e) {
            alert('Error saving group');
        } finally {
            setSaving(false);
        }
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
            <div className="bg-surface border border-border w-full max-w-4xl h-[85vh] rounded-xl shadow-2xl flex flex-col relative animate-in fade-in zoom-in duration-200">

                {/* Header */}
                <div className="p-6 border-b border-border flex justify-between items-center flex-shrink-0">
                    <div>
                        <h2 className="text-xl font-bold text-primary flex items-center gap-2">
                            <FolderPlus className="text-emerald-400" size={24} />
                            {editGroup ? 'Edit Group' : 'Create Group'}
                        </h2>
                        <p className="text-sm text-muted">Select episodes & characters from different movies</p>
                    </div>
                    <button onClick={onClose} className="text-muted hover:text-white transition-colors">
                        <X size={20} />
                    </button>
                </div>

                {/* Group Name */}
                <div className="px-6 py-3 border-b border-border flex-shrink-0">
                    <label className="block text-xs font-medium text-muted uppercase mb-1">Group Name</label>
                    <input
                        autoFocus
                        type="text"
                        placeholder="e.g. Villains Mix, Action Scenes..."
                        className="w-full bg-black/40 border border-border rounded-lg px-3 py-2.5 text-white text-sm focus:outline-none focus:border-emerald-500 transition-colors"
                        value={groupName}
                        onChange={(e) => setGroupName(e.target.value)}
                    />
                </div>

                {/* Main Content: Library (left) + Selected Items (right) */}
                <div className="flex-1 flex overflow-hidden">

                    {/* Left: Library picker */}
                    <div className="w-1/2 border-r border-border flex flex-col">
                        <div className="px-4 py-2 text-xs text-muted uppercase tracking-wider font-bold border-b border-border bg-black/20">
                            Library
                        </div>
                        <div className="flex-1 overflow-y-auto p-2 space-y-1">
                            {loading ? (
                                <div className="flex justify-center py-10"><Loader2 className="animate-spin text-muted" /></div>
                            ) : library.length === 0 ? (
                                <div className="text-center text-muted py-10 text-sm">No ready movies</div>
                            ) : (
                                library.map(source => {
                                    const alias = source.alias;
                                    const isExpanded = expandedSources[alias];
                                    const episodes = sourceEpisodes[alias] || [];
                                    const characters = sourceCharacters[alias] || [];

                                    return (
                                        <div key={alias} className="rounded-lg border border-border overflow-hidden">
                                            <button
                                                onClick={() => toggleSource(alias)}
                                                className="w-full flex items-center gap-2 px-3 py-2.5 bg-surface hover:bg-white/5 transition-colors text-left"
                                            >
                                                {isExpanded
                                                    ? <ChevronDown size={14} className="text-emerald-400 flex-shrink-0" />
                                                    : <ChevronRight size={14} className="text-muted flex-shrink-0" />
                                                }
                                                {source.thumbnail && (
                                                    <img src={source.thumbnail} alt="" className="w-6 h-8 object-cover rounded-sm flex-shrink-0 opacity-80" />
                                                )}
                                                <span className="text-xs font-bold truncate">{alias}</span>
                                            </button>

                                            {isExpanded && (
                                                <div className="bg-black/30 border-t border-border">
                                                    {/* Tabs */}
                                                    <div className="flex border-b border-border">
                                                        <button
                                                            onClick={() => setSourceTab(prev => ({ ...prev, [alias]: 'episodes' }))}
                                                            className={`flex-1 py-1.5 text-[10px] font-bold tracking-wider uppercase ${sourceTab[alias] !== 'characters' ? 'bg-white/10 text-white' : 'text-muted hover:bg-white/5'}`}
                                                        >
                                                            Episodes
                                                        </button>
                                                        <button
                                                            onClick={() => setSourceTab(prev => ({ ...prev, [alias]: 'characters' }))}
                                                            className={`flex-1 py-1.5 text-[10px] font-bold tracking-wider uppercase ${sourceTab[alias] === 'characters' ? 'bg-white/10 text-white' : 'text-muted hover:bg-white/5'}`}
                                                        >
                                                            Characters
                                                        </button>
                                                    </div>

                                                    <div className="p-1.5 space-y-0.5 max-h-[200px] overflow-y-auto">
                                                        {sourceTab[alias] === 'characters' ? (
                                                            characters.length === 0 ? (
                                                                <div className="text-[10px] text-muted p-2 text-center">No characters found</div>
                                                            ) : (
                                                                characters.map(charObj => {
                                                                    const isAdded = items.some(it => it.source_alias === alias && it.type === 'character' && it.name === charObj.name);
                                                                    return (
                                                                        <button
                                                                            key={`char-${charObj.name}`}
                                                                            onClick={() => addItem(alias, 'character', charObj.name)}
                                                                            disabled={isAdded}
                                                                            className={`w-full text-left px-3 py-1.5 rounded-md text-xs transition-colors flex items-center justify-between border border-transparent hover:border-white/10 ${isAdded ? 'opacity-40 cursor-not-allowed' : 'hover:bg-emerald-500/10 cursor-pointer'}`}
                                                                        >
                                                                            <div className="flex items-center gap-2 truncate">
                                                                                <Users size={11} className="text-orange-400 flex-shrink-0" />
                                                                                <span className="truncate">{charObj.name}</span>
                                                                            </div>
                                                                            <span className="text-[10px] text-muted">{charObj.scene_count} scenes</span>
                                                                        </button>
                                                                    );
                                                                })
                                                            )
                                                        ) : (
                                                            episodes.length === 0 ? (
                                                                <div className="flex items-center justify-center py-3">
                                                                    <Loader2 className="animate-spin text-muted" size={14} />
                                                                    <span className="text-[10px] text-muted ml-2">Loading...</span>
                                                                </div>
                                                            ) : (
                                                                episodes.map(ep => {
                                                                    const isAdded = items.some(it => it.source_alias === alias && it.type === 'episode' && it.episode_id === ep.id);
                                                                    return (
                                                                        <button
                                                                            key={ep.id}
                                                                            onClick={() => addItem(alias, 'episode', ep.name, ep.id)}
                                                                            disabled={isAdded}
                                                                            className={`w-full text-left px-3 py-1.5 rounded-md text-xs transition-colors flex items-center justify-between border border-transparent hover:border-white/10 ${isAdded ? 'opacity-40 cursor-not-allowed' : 'hover:bg-emerald-500/10 cursor-pointer'}`}
                                                                        >
                                                                            <div className="flex items-center gap-2 truncate">
                                                                                <List size={11} className="text-purple-400 flex-shrink-0" />
                                                                                <span className="truncate">{ep.name}</span>
                                                                            </div>
                                                                            <span className="text-[10px] text-muted">{Math.round((ep.end_time || 0) - (ep.start_time || 0))}s</span>
                                                                        </button>
                                                                    );
                                                                })
                                                            )
                                                        )}
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    );
                                })
                            )}
                        </div>
                    </div>

                    {/* Right: Selected Items */}
                    <div className="w-1/2 flex flex-col">
                        <div className="px-4 py-2 text-xs text-muted uppercase tracking-wider font-bold border-b border-border bg-black/20 flex justify-between items-center">
                            <span>Selected Items</span>
                            <span className="bg-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded-full text-[10px] font-mono">{items.length}</span>
                        </div>
                        <div className="flex-1 overflow-y-auto p-3 space-y-1">
                            {items.length === 0 ? (
                                <div className="text-center py-10 text-muted text-sm">
                                    <FolderPlus size={32} className="mx-auto mb-2 opacity-30" />
                                    Click items on the left to add them
                                </div>
                            ) : (
                                items.map((item, i) => (
                                    <div
                                        key={`${item.source_alias}-${item.type}-${item.name}-${i}`}
                                        className="flex items-center gap-2 px-3 py-2 bg-white/5 rounded-lg border border-white/10 group"
                                    >
                                        {item.type === 'character'
                                            ? <Users size={12} className="text-orange-400 flex-shrink-0" />
                                            : <List size={12} className="text-purple-400 flex-shrink-0" />
                                        }
                                        <div className="flex-1 min-w-0">
                                            <div className="text-xs font-medium text-white truncate">{item.name}</div>
                                            <div className="text-[10px] text-zinc-500">{item.source_alias}</div>
                                        </div>
                                        <span className="text-[9px] uppercase px-1.5 py-0.5 rounded bg-white/5 text-zinc-500 font-bold">
                                            {item.type}
                                        </span>
                                        <button
                                            onClick={() => removeItem(i)}
                                            className="p-1 text-zinc-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all"
                                        >
                                            <Trash2 size={12} />
                                        </button>
                                    </div>
                                ))
                            )}
                        </div>
                    </div>
                </div>

                {/* Footer */}
                <div className="p-4 border-t border-border flex justify-end gap-3 flex-shrink-0 bg-zinc-900/50">
                    <button onClick={onClose} className="px-4 py-2 text-sm text-muted hover:text-white transition-colors">
                        Cancel
                    </button>
                    <button
                        onClick={handleSave}
                        disabled={saving || !groupName.trim() || items.length === 0}
                        className="px-6 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-sm font-bold transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-emerald-900/20 flex items-center gap-2"
                    >
                        {saving ? <Loader2 className="animate-spin" size={16} /> : <FolderPlus size={16} />}
                        {editGroup ? 'Update Group' : `Create Group (${items.length})`}
                    </button>
                </div>
            </div>
        </div>
    );
}

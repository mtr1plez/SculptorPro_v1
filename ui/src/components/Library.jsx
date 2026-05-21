import { useState, useEffect, useMemo, useRef } from 'react';
import { Film, CheckCircle, AlertCircle, Loader2, Trash2, FolderPlus, Users, List, Pencil, Search, X } from 'lucide-react';
import { IngestModal } from './IngestModal';
import { GroupModal } from './GroupModal';
import { CircularProgress } from './CircularProgress';

export function Library({ onOpenSource }) {
  const [movies, setMovies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isIngestOpen, setIsIngestOpen] = useState(false);
  const [progressMap, setProgressMap] = useState({});
  const [contextMenu, setContextMenu] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');

  // Groups state
  const [groups, setGroups] = useState([]);
  const [isGroupOpen, setIsGroupOpen] = useState(false);
  const [editingGroup, setEditingGroup] = useState(null);

  const fetchLibraryRef = useRef(null);

  // === 1. ФУНКЦИЯ ЗАГРУЗКИ БИБЛИОТЕКИ ===
  const fetchLibrary = () => {
    fetch('http://localhost:8000/library')
      .then(res => res.json())
      .then(data => {
        setMovies(data);

        // === НОВОЕ: Восстанавливаем статус обработки ===
        const restoredProgress = {};
        data.forEach(movie => {
          if (movie.ingest_status === 'processing' && movie.percent < 100) {
            restoredProgress[movie.alias] = {
              percent: movie.percent,
              status: movie.progress_text
            };
          }
        });

        if (Object.keys(restoredProgress).length > 0) {
          setProgressMap(restoredProgress);
        }

        setLoading(false);
      })
      .catch(err => {
        console.error(err);
        setError(true);
        setLoading(false);
      });
  };

  const fetchGroups = () => {
    fetch('http://localhost:8000/groups')
      .then(res => res.json())
      .then(data => setGroups(data))
      .catch(err => console.error('Failed to load groups:', err));
  };

  const normalizedSearch = searchQuery.trim().toLowerCase();
  const filteredMovies = useMemo(() => {
    if (!normalizedSearch) return movies;

    return movies.filter(movie => {
      const activeProgress = progressMap[movie.alias];
      const searchable = [
        movie.alias,
        movie.path,
        movie.ready ? 'ready' : 'processing',
        activeProgress?.status,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();

      return searchable.includes(normalizedSearch);
    });
  }, [movies, normalizedSearch, progressMap]);

  const filteredGroups = useMemo(() => {
    if (!normalizedSearch) return groups;

    return groups.filter(group => {
      const itemText = (group.items || [])
        .map(item => `${item.name || ''} ${item.source_alias || ''} ${item.type || ''}`)
        .join(' ');
      const searchable = `${group.name || ''} ${itemText}`.toLowerCase();
      return searchable.includes(normalizedSearch);
    });
  }, [groups, normalizedSearch]);

  const hasSearch = normalizedSearch.length > 0;

  fetchLibraryRef.current = fetchLibrary;

  useEffect(() => {
    fetchLibrary();
    fetchGroups();
  }, []);

  // === 2. ЗАКРЫТИЕ МЕНЮ ПО КЛИКУ ===
  useEffect(() => {
    const handleClick = () => setContextMenu(null);
    window.addEventListener('click', handleClick);
    return () => window.removeEventListener('click', handleClick);
  }, []);

  // === 3. WEBSOCKET ===
  useEffect(() => {
    const ws = new WebSocket('ws://localhost:8000/ws/logs');

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        if (data.type === 'progress') {
          setProgressMap(prev => ({
            ...prev,
            [data.alias]: { percent: data.percent, status: data.status }
          }));

          if (data.percent === 100) {
            setTimeout(() => {
              if (fetchLibraryRef.current) fetchLibraryRef.current();
              setProgressMap(prev => {
                const newState = { ...prev };
                delete newState[data.alias];
                return newState;
              });
            }, 1000);
          }
        }
      } catch {
        // Ignore malformed websocket payloads.
      }
    };

    return () => ws.close();
  }, []);

  // === 4. ОБРАБОТЧИКИ (DELETE / CONTEXT MENU) ===
  const handleContextMenu = (e, movie) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({
      x: e.pageX,
      y: e.pageY,
      movie: movie
    });
  };

  const handleDelete = async (alias) => {
    if (!confirm(`Are you sure you want to delete "${alias}" from Library? This cannot be undone.`)) return;

    try {
      await fetch(`http://localhost:8000/library/${alias}`, { method: 'DELETE' });
      fetchLibrary();
    } catch (e) {
      alert("Failed to delete movie");
    }
  };

  const handleDeleteGroup = async (groupId) => {
    if (!confirm('Delete this group?')) return;
    try {
      await fetch(`http://localhost:8000/groups/${groupId}`, { method: 'DELETE' });
      fetchGroups();
    } catch (e) {
      alert("Failed to delete group");
    }
  };

  const handleEditGroup = (group) => {
    setEditingGroup(group);
    setIsGroupOpen(true);
  };


  // === РЕНДЕР ===

  if (loading) return (
    <div className="flex h-full items-center justify-center text-muted gap-2">
      <Loader2 className="animate-spin" /> Loading Library...
    </div>
  );

  if (error) return (
    <div className="flex h-full items-center justify-center text-red-400 gap-2">
      <AlertCircle /> Connection failed. Is python server running?
    </div>
  );

  return (
    <div className="p-8 h-full overflow-y-auto relative min-h-screen">
      <IngestModal
        isOpen={isIngestOpen}
        onClose={() => setIsIngestOpen(false)}
        onIngestSuccess={() => {
          setIsIngestOpen(false);
          fetchLibrary();
        }}
      />

      <GroupModal
        isOpen={isGroupOpen}
        onClose={() => { setIsGroupOpen(false); setEditingGroup(null); }}
        onSaved={() => { fetchGroups(); setEditingGroup(null); }}
        editGroup={editingGroup}
      />

      {/* === КОНТЕКСТНОЕ МЕНЮ === */}
      {contextMenu && (
        <div
          className="fixed z-50 bg-zinc-800 border border-zinc-700 shadow-xl rounded-lg py-1 min-w-[160px] animate-in fade-in zoom-in-95 duration-100"
          style={{ top: contextMenu.y, left: contextMenu.x }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="px-3 py-2 text-xs text-zinc-500 border-b border-zinc-700 mb-1">
            {contextMenu.movie.alias}
          </div>
          <button
            onClick={() => {
              handleDelete(contextMenu.movie.alias);
              setContextMenu(null);
            }}
            className="w-full text-left px-4 py-2 text-sm text-red-400 hover:bg-red-500/10 hover:text-red-300 flex items-center gap-2 transition-colors"
          >
            <Trash2 size={14} /> Delete Movie
          </button>
        </div>
      )}

      <header className="mb-8 flex justify-between items-center">
        <div>
          <h2 className="text-3xl font-bold text-primary">Media Library</h2>
          <p className="text-muted text-sm mt-1">Manage your source footage</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => { setEditingGroup(null); setIsGroupOpen(true); }}
            className="bg-emerald-600 hover:bg-emerald-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors shadow-lg shadow-emerald-900/20 flex items-center gap-2"
          >
            <FolderPlus size={16} /> Group
          </button>
          <button
            onClick={() => setIsIngestOpen(true)}
            className="bg-accent hover:bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors shadow-lg shadow-blue-900/20"
          >
            + Ingest Movie
          </button>
        </div>
      </header>

      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative w-full sm:max-w-md">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none" />
          <input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search movies, paths, groups..."
            className="w-full h-10 bg-zinc-950/70 border border-border rounded-lg pl-9 pr-10 text-sm text-white placeholder:text-zinc-600 focus:outline-none focus:border-accent/70 focus:ring-1 focus:ring-accent/30 transition-colors"
          />
          {hasSearch && (
            <button
              type="button"
              onClick={() => setSearchQuery('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-zinc-500 hover:text-white hover:bg-white/10 rounded-md transition-colors"
              title="Clear search"
              aria-label="Clear search"
            >
              <X size={14} />
            </button>
          )}
        </div>
        <div className="text-xs text-muted">
          {hasSearch
            ? `${filteredMovies.length} of ${movies.length} movies`
            : `${movies.length} movies`}
        </div>
      </div>

      {movies.length === 0 ? (
        <div className="text-center py-20 border border-dashed border-border rounded-xl">
          <Film className="w-12 h-12 text-muted mx-auto mb-3 opacity-20" />
          <p className="text-muted">Library is empty</p>
        </div>
      ) : filteredMovies.length === 0 ? (
        <div className="text-center py-20 border border-dashed border-border rounded-xl">
          <Search className="w-12 h-12 text-muted mx-auto mb-3 opacity-20" />
          <p className="text-muted">No movies match "{searchQuery.trim()}"</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6 pb-4">
          {filteredMovies.map((movie) => {
            const activeProgress = progressMap[movie.alias];
            const isProcessing = !movie.ready || activeProgress;
            const percent = activeProgress?.percent || 0;
            const statusText = activeProgress?.status || "Queued...";

            return (
              <div
                key={movie.alias}
                onClick={() => onOpenSource && onOpenSource(movie)} // <--- CLICK HANDLER
                onContextMenu={(e) => handleContextMenu(e, movie)} // <--- ДОБАВИЛИ ОБРАБОТЧИК
                className="group bg-surface border border-border rounded-xl overflow-hidden hover:border-accent/50 transition-all cursor-pointer relative shadow-lg"
              >

                <div className="h-64 bg-zinc-900 flex items-center justify-center relative overflow-hidden">
                  {movie.thumbnail ? (
                    <img
                      src={movie.thumbnail}
                      alt={movie.alias}
                      className={`w-full h-full object-cover transition-all duration-500 
                        ${isProcessing ? 'opacity-30 blur-sm scale-105' : 'opacity-90 group-hover:opacity-100 group-hover:scale-105'}
                      `}
                      onError={(e) => { e.target.style.display = 'none'; }}
                    />
                  ) : (
                    <Film className="text-zinc-700 w-16 h-16" />
                  )}

                  {isProcessing && (
                    <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-black/40 backdrop-blur-[2px]">
                      <CircularProgress percent={percent} size={60} />
                      <span className="text-xs font-medium text-yellow-400 mt-3 px-2 py-1 bg-black/60 rounded-full border border-yellow-500/20">
                        {statusText}
                      </span>
                    </div>
                  )}

                  {!isProcessing && (
                    <div className="absolute top-3 right-3 z-10">
                      <span className="bg-black/60 backdrop-blur-md text-green-400 text-xs px-2 py-1 rounded-md flex items-center gap-1 border border-green-500/30 font-medium shadow-sm">
                        <CheckCircle size={12} /> Ready
                      </span>
                    </div>
                  )}

                  <div className="absolute bottom-0 left-0 w-full h-2/3 bg-gradient-to-t from-black via-black/50 to-transparent opacity-80 pointer-events-none"></div>
                </div>

                <div className="absolute bottom-0 left-0 w-full p-4 z-20">
                  <h3 className="font-bold text-xl text-white drop-shadow-md truncate">{movie.alias}</h3>
                  <p className="text-xs text-gray-300 mt-1 truncate opacity-80">{movie.path}</p>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* === GROUPS SECTION === */}
      {filteredGroups.length > 0 && (
        <div className="mt-8 pb-20">
          <h3 className="text-xl font-bold text-primary mb-4 flex items-center gap-2">
            <FolderPlus size={20} className="text-emerald-400" />
            Groups
            <span className="text-sm font-normal text-muted bg-surface px-2 py-0.5 rounded-full border border-border">{filteredGroups.length}</span>
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {filteredGroups.map(group => (
              <div
                key={group.id}
                className="bg-surface border border-border rounded-xl p-4 hover:border-emerald-500/40 transition-all group/card"
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <FolderPlus size={16} className="text-emerald-400" />
                    <h4 className="font-bold text-white text-sm truncate">{group.name}</h4>
                  </div>
                  <div className="flex items-center gap-1 opacity-0 group-hover/card:opacity-100 transition-opacity">
                    <button
                      onClick={() => handleEditGroup(group)}
                      className="p-1.5 text-zinc-500 hover:text-blue-400 hover:bg-blue-500/10 rounded-md transition-colors"
                      title="Edit group"
                    >
                      <Pencil size={12} />
                    </button>
                    <button
                      onClick={() => handleDeleteGroup(group.id)}
                      className="p-1.5 text-zinc-500 hover:text-red-400 hover:bg-red-500/10 rounded-md transition-colors"
                      title="Delete group"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                </div>
                <div className="space-y-1">
                  {(group.items || []).slice(0, 4).map((item, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs text-zinc-400">
                      {item.type === 'character'
                        ? <Users size={10} className="text-orange-400 flex-shrink-0" />
                        : <List size={10} className="text-purple-400 flex-shrink-0" />
                      }
                      <span className="truncate">{item.name}</span>
                      <span className="text-[10px] text-zinc-600 ml-auto flex-shrink-0">{item.source_alias}</span>
                    </div>
                  ))}
                  {(group.items || []).length > 4 && (
                    <div className="text-[10px] text-zinc-600 pl-4">+{group.items.length - 4} more</div>
                  )}
                </div>
                <div className="mt-3 pt-2 border-t border-white/5">
                  <span className="text-[10px] text-zinc-600">{(group.items || []).length} items from {new Set((group.items || []).map(it => it.source_alias)).size} sources</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

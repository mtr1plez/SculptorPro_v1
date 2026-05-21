import { useState, useEffect, useCallback } from 'react';
import { LayoutTemplate, Folder, Calendar, Plus, Trash2 } from 'lucide-react';
import { CreateProjectModal } from './CreateProjectModal';

export function Projects({ onOpenProject, activeBuilds = {} }) {
  const [projects, setProjects] = useState([]);
  const [isModalOpen, setIsModalOpen] = useState(false);

  // Состояние для контекстного меню: { x, y, project } или null
  const [contextMenu, setContextMenu] = useState(null);

  // === Multi-Delete State ===
  const [isSelectionMode, setIsSelectionMode] = useState(false);
  const [selectedProjects, setSelectedProjects] = useState(new Set());

  const fetchProjects = useCallback(() => {
    fetch('http://localhost:8000/projects')
      .then(res => {
        if (!res.ok) throw new Error("Err");
        return res.json();
      })
      .then(data => setProjects(data))
      .catch(() => setProjects([]));
  }, []);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  // Закрываем меню при клике в любое место
  useEffect(() => {
    const handleClick = () => setContextMenu(null);
    window.addEventListener('click', handleClick);
    return () => window.removeEventListener('click', handleClick);
  }, []);

  // Обработчик ПКМ (Правой Кнопки Мыши)
  const handleContextMenu = (e, project) => {
    e.preventDefault(); // Блокируем стандартное меню браузера
    e.stopPropagation(); // Чтобы клик не ушел выше

    setContextMenu({
      x: e.pageX,
      y: e.pageY,
      project: project
    });
  };

  const handleDelete = async (projectName) => {
    // Спрашиваем подтверждение
    if (!confirm(`Are you sure you want to delete "${projectName}"?`)) return;

    try {
      await fetch(`http://localhost:8000/projects/${projectName}`, { method: 'DELETE' });
      fetchProjects(); // Обновляем список

      // Remove from selected set if it was selected
      if (selectedProjects.has(projectName)) {
        const newSelected = new Set(selectedProjects);
        newSelected.delete(projectName);
        setSelectedProjects(newSelected);
      }
    } catch (e) {
      alert("Failed to delete project");
    }
  };

  const handleBulkDelete = async () => {
    if (selectedProjects.size === 0) return;
    if (!confirm(`Are you sure you want to delete ${selectedProjects.size} selected projects?`)) return;

    try {
      // Create an array of delete promises
      const deletePromises = Array.from(selectedProjects).map(projectName =>
        fetch(`http://localhost:8000/projects/${projectName}`, { method: 'DELETE' })
      );

      await Promise.all(deletePromises);
      fetchProjects(); // Update list once all deletions complete
      setSelectedProjects(new Set()); // Clear selection
      setIsSelectionMode(false); // Exit selection mode
    } catch (e) {
      alert("Failed to delete some or all selected projects");
    }
  };

  const toggleSelectionMode = () => {
    setIsSelectionMode(!isSelectionMode);
    setSelectedProjects(new Set()); // Reset selection when toggling
  };

  const toggleProjectSelection = (e, projectName) => {
    e.stopPropagation(); // Prevent triggering the project open action
    const newSelected = new Set(selectedProjects);
    if (newSelected.has(projectName)) {
      newSelected.delete(projectName);
    } else {
      newSelected.add(projectName);
    }
    setSelectedProjects(newSelected);
  };

  return (
    <div className="p-8 h-full overflow-y-auto relative min-h-screen">

      <CreateProjectModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSuccess={fetchProjects}
      />

      {/* === КОНТЕКСТНОЕ МЕНЮ (Рендерим только если оно есть) === */}
      {contextMenu && (
        <div
          className="fixed z-50 bg-zinc-800 border border-zinc-700 shadow-xl rounded-lg py-1 min-w-[160px] animate-in fade-in zoom-in-95 duration-100"
          style={{ top: contextMenu.y, left: contextMenu.x }}
          onClick={(e) => e.stopPropagation()} // Чтобы клик по меню не закрывал его сразу
        >
          <div className="px-3 py-2 text-xs text-zinc-500 border-b border-zinc-700 mb-1">
            {contextMenu.project.name}
          </div>
          <button
            onClick={() => {
              handleDelete(contextMenu.project.name);
              setContextMenu(null);
            }}
            className="w-full text-left px-4 py-2 text-sm text-red-400 hover:bg-red-500/10 hover:text-red-300 flex items-center gap-2 transition-colors"
          >
            <Trash2 size={14} /> Delete Project
          </button>
        </div>
      )}

      {/* HEADER */}
      <header className="mb-8 flex justify-between items-center">
        <div>
          <h2 className="text-3xl font-bold text-primary">Projects</h2>
          <p className="text-muted text-sm mt-1">Your editing workspaces</p>
        </div>

        <div className="flex items-center gap-3">
          {projects.length > 0 && (
            <>
              {isSelectionMode ? (
                <>
                  <button
                    onClick={handleBulkDelete}
                    disabled={selectedProjects.size === 0}
                    className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2 ${selectedProjects.size > 0
                        ? 'bg-red-600 hover:bg-red-500 text-white shadow-lg shadow-red-900/20'
                        : 'bg-zinc-800 text-zinc-500 cursor-not-allowed'
                      }`}
                  >
                    <Trash2 size={16} />
                    Delete Selected ({selectedProjects.size})
                  </button>
                  <button
                    onClick={toggleSelectionMode}
                    className="bg-zinc-800 hover:bg-zinc-700 text-zinc-300 px-4 py-2 rounded-lg text-sm font-medium transition-colors"
                  >
                    Cancel
                  </button>
                </>
              ) : (
                <button
                  onClick={toggleSelectionMode}
                  className="bg-zinc-800 hover:bg-zinc-700 text-zinc-300 px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                >
                  <Trash2 size={16} />
                  Manage
                </button>
              )}
            </>
          )}

          <button
            onClick={() => setIsSelectionMode(false) || setIsModalOpen(true)}
            className="bg-purple-600 hover:bg-purple-500 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors shadow-lg shadow-purple-900/20 flex items-center gap-2"
          >
            <Plus size={16} /> New Project
          </button>
        </div>
      </header>

      {/* GRID */}
      {projects.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 border border-dashed border-zinc-800 rounded-xl bg-zinc-900/20">
          <div className="w-16 h-16 bg-zinc-800 rounded-full flex items-center justify-center mb-4">
            <LayoutTemplate className="w-8 h-8 text-zinc-600" />
          </div>
          <h3 className="text-lg font-medium text-zinc-300">No projects yet</h3>
          <p className="text-zinc-500 text-sm mt-1 mb-6">Create your first project to start editing.</p>
          <button
            onClick={() => setIsModalOpen(true)}
            className="text-purple-400 hover:text-purple-300 text-sm font-medium hover:underline"
          >
            Create New Project
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 pb-20">
          {projects.map((proj) => {
            const build = activeBuilds[proj.name];
            const isBuilding = build && build.percent > 0 && build.percent < 100;

            return (
              <div
                key={proj.name}
                onClick={() => {
                  if (isSelectionMode) {
                    toggleProjectSelection({ stopPropagation: () => { } }, proj.name);
                  } else {
                    onOpenProject(proj);
                  }
                }}
                onContextMenu={(e) => {
                  if (!isSelectionMode) handleContextMenu(e, proj);
                }}
                className={`group bg-surface border p-5 rounded-xl transition-all cursor-pointer relative shadow-sm overflow-hidden ${isBuilding
                    ? 'border-yellow-500/50 shadow-yellow-900/20'
                    : isSelectionMode && selectedProjects.has(proj.name)
                      ? 'border-red-500 bg-red-500/5 shadow-red-900/20'
                      : isSelectionMode
                        ? 'border-zinc-800 hover:border-red-500/30'
                        : 'border-border hover:border-purple-500/50 hover:shadow-purple-900/10 hover:bg-zinc-900'
                  }`}
              >
                <div className="flex items-start justify-between mb-4">
                  <div className={`w-10 h-10 rounded-lg flex items-center justify-center transition-colors ${isBuilding
                      ? 'bg-yellow-500/10 text-yellow-400'
                      : isSelectionMode && selectedProjects.has(proj.name)
                        ? 'bg-red-500/20 text-red-500'
                        : 'bg-zinc-800 group-hover:bg-purple-500/10 group-hover:text-purple-400'
                    }`}>
                    {isBuilding ? (
                      <div className="w-5 h-5 border-2 border-yellow-400 border-t-transparent rounded-full animate-spin" />
                    ) : (
                      <Folder size={20} />
                    )}
                  </div>

                  {isSelectionMode && (
                    <div
                      className={`w-5 h-5 rounded border flex items-center justify-center transition-colors ${selectedProjects.has(proj.name)
                          ? 'border-red-500 bg-red-500 text-white'
                          : 'border-zinc-600 bg-zinc-800/50'
                        }`}
                      onClick={(e) => toggleProjectSelection(e, proj.name)}
                    >
                      {selectedProjects.has(proj.name) && (
                        <svg viewBox="0 0 24 24" fill="none" className="w-3.5 h-3.5" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                          <polyline points="20 6 9 17 4 12"></polyline>
                        </svg>
                      )}
                    </div>
                  )}
                </div>

                <h3 className="font-bold text-lg text-gray-200 group-hover:text-white transition-colors truncate pr-2">
                  {proj.name}
                </h3>

                <div className="mt-4 flex items-center gap-4 text-xs text-muted">
                  <div className="flex items-center gap-1.5">
                    <Calendar size={12} />
                    <span>Local Project</span>
                  </div>
                </div>

                {/* Build Progress Overlay */}
                {isBuilding && (
                  <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/90 via-black/70 to-transparent p-4 pt-8">
                    <div className="flex items-center justify-between text-xs mb-2">
                      <span className="text-yellow-400 font-medium">Building...</span>
                      <span className="text-yellow-300 font-mono">{build.percent}%</span>
                    </div>
                    <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-yellow-500 to-amber-400 transition-all duration-300 ease-out"
                        style={{ width: `${build.percent}%` }}
                      />
                    </div>
                    {build.status && (
                      <p className="text-[10px] text-zinc-400 mt-1.5 truncate">{build.status}</p>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
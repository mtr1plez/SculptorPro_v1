import { useState, useEffect } from 'react';
import { X, Film, CheckCircle, Loader2 } from 'lucide-react';

export function SourceSelector({ isOpen, onClose, onConfirm, alreadySelected = [] }) {
  const [movies, setMovies] = useState([]);
  const [selected, setSelected] = useState(new Set(alreadySelected));
  const [loading, setLoading] = useState(true);

  // Загружаем библиотеку при открытии
  useEffect(() => {
    if (isOpen) {
      setLoading(true);
      fetch('http://localhost:8000/library')
        .then(res => res.json())
        .then(data => {
          // Показываем только готовые фильмы (Ready)
          setMovies(data.filter(m => m.ready));
          setLoading(false);
        })
        .catch(() => setLoading(false));
    }
  }, [isOpen]);

  const toggleSelection = (alias) => {
    const newSet = new Set(selected);
    if (newSet.has(alias)) {
      newSet.delete(alias);
    } else {
      newSet.add(alias);
    }
    setSelected(newSet);
  };

  const handleConfirm = () => {
    onConfirm(Array.from(selected));
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-surface border border-border w-full max-w-4xl h-[80vh] rounded-xl shadow-2xl flex flex-col relative animate-in fade-in zoom-in duration-200">
        
        {/* Header */}
        <div className="p-6 border-b border-border flex justify-between items-center">
          <div>
            <h2 className="text-xl font-bold text-primary">Select Source Footage</h2>
            <p className="text-sm text-muted">Choose movies to use in this project</p>
          </div>
          <button onClick={onClose} className="text-muted hover:text-white">
            <X size={24} />
          </button>
        </div>

        {/* Grid */}
        <div className="flex-1 overflow-y-auto p-6">
          {loading ? (
            <div className="flex justify-center py-20"><Loader2 className="animate-spin text-accent" /></div>
          ) : movies.length === 0 ? (
            <div className="text-center text-muted py-20">No ready movies found in Library.</div>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {movies.map(movie => {
                const isSelected = selected.has(movie.alias);
                return (
                  <div 
                    key={movie.alias}
                    onClick={() => toggleSelection(movie.alias)}
                    className={`
                      relative rounded-lg overflow-hidden cursor-pointer border-2 transition-all group
                      ${isSelected ? 'border-accent ring-2 ring-accent/20' : 'border-transparent hover:border-zinc-600'}
                    `}
                  >
                    <div className="aspect-video bg-zinc-900 relative">
                      {movie.thumbnail ? (
                        <img src={movie.thumbnail} className="w-full h-full object-cover opacity-80" />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center"><Film className="text-zinc-700" /></div>
                      )}
                      
                      {/* Checkbox overlay */}
                      <div className={`absolute inset-0 bg-black/40 flex items-center justify-center transition-opacity ${isSelected ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}>
                         {isSelected && <CheckCircle className="text-accent w-10 h-10 drop-shadow-lg" fill="black" />}
                      </div>
                    </div>
                    <div className="p-3 bg-zinc-900">
                      <p className="font-medium text-sm text-white truncate">{movie.alias}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-6 border-t border-border flex justify-end gap-3 bg-zinc-900/50">
          <button onClick={onClose} className="px-4 py-2 text-sm text-muted hover:text-white">Cancel</button>
          <button 
            onClick={handleConfirm}
            className="px-6 py-2 bg-accent hover:bg-blue-600 text-white rounded-lg text-sm font-medium transition-colors"
          >
            Add Selected ({selected.size})
          </button>
        </div>

      </div>
    </div>
  );
}

import { useState } from 'react';
import { X, LayoutTemplate, Loader2 } from 'lucide-react';

export function CreateProjectModal({ isOpen, onClose, onSuccess }) {
  const [name, setName] = useState('');
  const [matchingMode, setMatchingMode] = useState('chaotic');
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;

    setIsSubmitting(true);
    try {
      const response = await fetch('http://localhost:8000/projects/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name,
          matching_mode: matchingMode
        })
      });

      if (response.ok) {
        setName(''); // Очищаем поле
        onSuccess(); // Обновляем список
        onClose();   // Закрываем окно
      } else {
        alert("Failed to create project");
      }
    } catch (e) {
      alert("Error connecting to server");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-40 flex items-center justify-center p-4">
      <div className="bg-surface border border-border w-full max-w-md rounded-xl shadow-2xl p-6 relative animate-in fade-in zoom-in duration-200">

        <button onClick={onClose} className="absolute top-4 right-4 text-muted hover:text-white transition-colors">
          <X size={20} />
        </button>

        <header className="mb-6">
          <div className="w-12 h-12 bg-purple-500/10 rounded-full flex items-center justify-center mb-3">
            <LayoutTemplate className="text-purple-400" size={24} />
          </div>
          <h2 className="text-xl font-bold text-primary">New Project</h2>
          <p className="text-sm text-muted">Create a workspace for your edit.</p>
        </header>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-muted mb-1 uppercase">Project Name</label>
            <input
              type="text"
              placeholder="My Masterpiece"
              className="w-full bg-background border border-border rounded-lg p-3 text-sm text-white focus:outline-none focus:border-purple-500 transition-colors"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
              required
            />
          </div>



          <div className="mt-4">
            <label className="block text-xs font-medium text-muted mb-2 uppercase">
              Matching Mode
            </label>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => setMatchingMode('chaotic')}
                className={`flex-1 py-3 rounded-lg border text-sm font-medium transition-all ${matchingMode === 'chaotic'
                  ? 'bg-purple-500/20 border-purple-500 text-purple-400'
                  : 'bg-surface border-border text-muted hover:border-purple-500/50'
                  }`}
              >
                🎲 Chaotic
                <span className="block text-xs opacity-60 mt-0.5">For video essays</span>
              </button>
              <button
                type="button"
                onClick={() => setMatchingMode('sequential')}
                className={`flex-1 py-3 rounded-lg border text-sm font-medium transition-all ${matchingMode === 'sequential'
                  ? 'bg-blue-500/20 border-blue-500 text-blue-400'
                  : 'bg-surface border-border text-muted hover:border-blue-500/50'
                  }`}
              >
                📖 Sequential
                <span className="block text-xs opacity-60 mt-0.5">Coming soon</span>
              </button>
            </div>
          </div>

          <div className="pt-2">
            <button
              type="submit"
              disabled={isSubmitting || !name.trim()}
              className="w-full bg-purple-600 hover:bg-purple-500 text-white font-medium py-3 rounded-lg flex items-center justify-center gap-2 transition-all active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-purple-900/20"
            >
              {isSubmitting ? <Loader2 className="animate-spin" /> : <LayoutTemplate size={18} />}
              {isSubmitting ? 'Creating...' : 'Create Project'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
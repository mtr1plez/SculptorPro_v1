import { useState, useEffect } from 'react';
import { X, Film, Loader2, FolderOpen } from 'lucide-react';
import { electronAPI } from '../lib/electron';

export function IngestModal({ isOpen, onClose, onIngestSuccess }) {
  const [formData, setFormData] = useState({
    file_path: '',
    alias: '',
    fullname: ''
  });
  const [isSubmitting, setIsSubmitting] = useState(false);

  const applySelectedFile = (path) => {
    if (!path) return;

    const fileName = path.split(/[/\\]/).pop(); // вытаскиваем имя из пути
    const nameWithoutExt = fileName.replace(/\.[^/.]+$/, "");
    const cleanName = nameWithoutExt.replace(/[._]/g, " ");

    setFormData({
      file_path: path, // Теперь тут ГАРАНТИРОВАННО полный путь
      alias: nameWithoutExt.replace(/\s/g, "_"),
      fullname: cleanName
    });
  };

  // Слушаем старый event-ответ от Electron'а для совместимости с уже запущенным main process.
  useEffect(() => {
    if (!isOpen) return;

    const unsubscribe = electronAPI.onSelectedFile(applySelectedFile);
    return () => unsubscribe();
  }, [isOpen]);

  // Функция вызова диалога
  const handleBrowseClick = async () => {
    try {
      const path = await electronAPI.openFileDialog();
      applySelectedFile(path);
    } catch (error) {
      alert(`File picker is unavailable: ${error.message}`);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsSubmitting(true);

    try {
      const response = await fetch('http://localhost:8000/ingest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData)
      });

      if (response.ok) {
        if (onIngestSuccess) onIngestSuccess();
        onClose();
      } else {
        alert("Failed to start ingest");
      }
    } catch (error) {
      alert("Error connecting to server");
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-40 flex items-center justify-center p-4">
      <div className="bg-surface border border-border w-full max-w-lg rounded-xl shadow-2xl p-6 relative animate-in fade-in zoom-in duration-200">

        <button onClick={onClose} className="absolute top-4 right-4 text-muted hover:text-white transition-colors">
          <X size={20} />
        </button>

        <header className="mb-6">
          <h2 className="text-xl font-bold text-primary flex items-center gap-2">
            <Film className="text-accent" size={24} />
            Ingest New Movie
          </h2>
          <p className="text-sm text-muted">Select a video file from your drive.</p>
        </header>

        <form onSubmit={handleSubmit} className="space-y-6">

          {/* === ВЫБОР ФАЙЛА (BROWSE) === */}
          <div>
            <label className="block text-xs font-medium text-muted mb-1 uppercase">Video File</label>
            <div className="flex gap-2">
              <input
                type="text"
                placeholder="No file selected..."
                className="flex-1 bg-zinc-900 border border-zinc-700 rounded-lg p-3 text-sm text-gray-300 focus:outline-none cursor-not-allowed"
                value={formData.file_path}
                readOnly
              />
              <button
                type="button" // Важно, чтобы не сабмитил форму
                onClick={handleBrowseClick}
                className="bg-zinc-800 hover:bg-zinc-700 text-white px-4 rounded-lg border border-zinc-600 transition-colors flex items-center gap-2"
              >
                <FolderOpen size={18} />
                Browse
              </button>
            </div>
            <p className="text-[10px] text-zinc-500 mt-2">
              Supports MP4, MKV, MOV. Full path will be detected automatically.
            </p>
          </div>

          {/* === AUTO-FILLED FIELDS === */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-muted mb-1 uppercase">Alias (Folder Name)</label>
              <input
                type="text"
                className="w-full bg-background border border-border rounded-lg p-3 text-sm text-white focus:outline-none focus:border-accent transition-colors"
                value={formData.alias}
                onChange={(e) => setFormData({ ...formData, alias: e.target.value })}
                required
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-muted mb-1 uppercase">TMDB Name</label>
              <input
                type="text"
                className="w-full bg-background border border-border rounded-lg p-3 text-sm text-white focus:outline-none focus:border-accent transition-colors"
                value={formData.fullname}
                onChange={(e) => setFormData({ ...formData, fullname: e.target.value })}
              />
            </div>
          </div>

          <div className="pt-2">
            <button
              type="submit"
              disabled={isSubmitting || !formData.file_path}
              className="w-full bg-accent hover:bg-blue-600 text-white font-medium py-3 rounded-lg flex items-center justify-center gap-2 transition-all active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-blue-900/20"
            >
              {isSubmitting ? <Loader2 className="animate-spin" /> : <Film size={18} />}
              {isSubmitting ? 'Starting Process...' : 'Start Indexing'}
            </button>
          </div>

        </form>
      </div>
    </div>
  );
}

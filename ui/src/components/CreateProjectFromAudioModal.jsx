import { useState } from 'react';
import { X, LayoutTemplate, Loader2, FileAudio } from 'lucide-react';

export function CreateProjectFromAudioModal({ isOpen, onClose, onSuccess, audioFilename }) {
    const [name, setName] = useState('');
    const matchingMode = 'chaotic';
    const [isSubmitting, setIsSubmitting] = useState(false);

    if (!isOpen) return null;

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!name.trim()) return;

        setIsSubmitting(true);
        try {
            const response = await fetch('http://localhost:8000/projects/create_from_studio', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: name,
                    matching_mode: matchingMode,
                    audio_filename: audioFilename
                })
            });

            if (response.ok) {
                const data = await response.json();
                setName('');
                onSuccess({ name: data.name }); // Pass the new project back
                onClose();
            } else {
                const err = await response.json();
                alert(`Failed to create project: ${err.error || 'Unknown error'}`);
            }
        } catch (e) {
            alert("Error connecting to server");
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-[200] flex items-center justify-center p-4">
            <div className="bg-surface border border-border w-full max-w-md rounded-xl shadow-2xl p-6 relative animate-in fade-in zoom-in duration-200">

                <button onClick={onClose} className="absolute top-4 right-4 text-muted hover:text-white transition-colors">
                    <X size={20} />
                </button>

                <header className="mb-6">
                    <div className="w-12 h-12 bg-purple-500/10 rounded-full flex items-center justify-center mb-3">
                        <LayoutTemplate className="text-purple-400" size={24} />
                    </div>
                    <h2 className="text-xl font-bold text-primary">Create Project from Audio</h2>
                    <p className="text-sm text-muted">Create a new workspace using the selected studio audio.</p>
                </header>

                <div className="mb-4 p-3 bg-black/20 border border-white/5 rounded-lg flex items-center gap-3">
                    <FileAudio className="text-accent" size={20} />
                    <span className="text-sm font-mono text-zinc-300 truncate">{audioFilename}</span>
                </div>

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

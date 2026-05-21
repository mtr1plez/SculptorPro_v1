import React, { useState } from 'react';
import { Lightbulb, Send, Loader2, Sparkles, AlertCircle } from 'lucide-react';

export function BrainstormTab() {
    const [movieTitle, setMovieTitle] = useState('');
    const [ideas, setIdeas] = useState([]);
    const [selectedIdea, setSelectedIdea] = useState(null);
    const [script, setScript] = useState('');

    const [isLoadingIdeas, setIsLoadingIdeas] = useState(false);
    const [isLoadingScript, setIsLoadingScript] = useState(false);
    const [error, setError] = useState(null);

    const handleGenerateIdeas = async (e) => {
        e.preventDefault();
        if (!movieTitle.trim()) return;

        setIsLoadingIdeas(true);
        setError(null);
        setIdeas([]);
        setSelectedIdea(null);
        setScript('');

        try {
            const resp = await fetch('http://localhost:8000/brainstorm/ideas', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ movie_title: movieTitle })
            });

            if (!resp.ok) {
                throw new Error(`Failed to generate ideas: ${resp.statusText}`);
            }

            const data = await resp.json();
            setIdeas(data.ideas || []);
        } catch (err) {
            setError(err.message);
        } finally {
            setIsLoadingIdeas(false);
        }
    };

    const handleSelectIdea = async (idea) => {
        setSelectedIdea(idea);
        setIsLoadingScript(true);
        setError(null);
        setScript('');

        try {
            const resp = await fetch('http://localhost:8000/brainstorm/script', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    idea_title: idea.title,
                    idea_synopsis: idea.synopsis
                })
            });

            if (!resp.ok) {
                throw new Error(`Failed to generate script: ${resp.statusText}`);
            }

            const data = await resp.json();
            setScript(data.script || '');
        } catch (err) {
            setError(err.message);
        } finally {
            setIsLoadingScript(false);
        }
    };

    return (
        <div className="h-full flex flex-col p-8 overflow-hidden relative">
            {/* Background decoration */}
            <div className="absolute top-0 right-0 w-96 h-96 bg-purple-500/10 rounded-full blur-3xl -translate-y-1/2 translate-x-1/2 pointer-events-none"></div>

            <header className="mb-8 z-10 flex items-center gap-3">
                <div className="p-3 bg-white/5 rounded-xl border border-white/10">
                    <Lightbulb className="text-purple-400" size={24} />
                </div>
                <div>
                    <h1 className="text-2xl font-bold tracking-tight">Brainstorm Shorts</h1>
                    <p className="text-muted text-sm mt-1">Generate non-obvious, controversial ideas and scripts for your next Short.</p>
                </div>
            </header>

            {/* Main Content Area */}
            <div className="flex-1 flex gap-6 min-h-0 z-10">

                {/* Left Column: Input + Ideas List */}
                <div className="w-1/3 flex flex-col gap-6 min-w-[350px]">
                    {/* Input Form */}
                    <form onSubmit={handleGenerateIdeas} className="bg-surface border border-border rounded-xl p-5 shadow-lg flex flex-col gap-4">
                        <h2 className="text-lg font-medium text-white/90">Movie Title</h2>
                        <div className="flex gap-2">
                            <input
                                type="text"
                                placeholder="e.g. Fight Club, Inception..."
                                className="flex-1 bg-black/40 border border-white/10 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/50 transition-all text-white placeholder-white/20"
                                value={movieTitle}
                                onChange={(e) => setMovieTitle(e.target.value)}
                            />
                        </div>
                        <button
                            type="submit"
                            disabled={!movieTitle.trim() || isLoadingIdeas}
                            className="w-full flex items-center justify-center gap-2 bg-purple-600 hover:bg-purple-700 text-white px-4 py-2.5 rounded-lg text-sm font-medium transition-all shadow-lg shadow-purple-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {isLoadingIdeas ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
                            Generate Ideas
                        </button>
                    </form>

                    {/* Ideas List */}
                    <div className="flex-1 flex flex-col gap-3 overflow-y-auto pr-2 custom-scrollbar">
                        {isLoadingIdeas && (
                            <div className="flex flex-col items-center justify-center p-8 text-muted border border-border border-dashed rounded-xl h-48">
                                <Loader2 size={24} className="animate-spin mb-3 text-purple-400" />
                                <p className="text-sm">Brainstorming spicy takes...</p>
                            </div>
                        )}

                        {!isLoadingIdeas && ideas.length > 0 && (
                            <div className="space-y-3">
                                {ideas.map((idea, idx) => (
                                    <button
                                        key={idx}
                                        onClick={() => handleSelectIdea(idea)}
                                        className={`w-full text-left p-4 rounded-xl border transition-all duration-200 group ${selectedIdea?.title === idea.title
                                                ? 'bg-purple-500/10 border-purple-500/50 shadow-[0_0_15px_rgba(168,85,247,0.1)]'
                                                : 'bg-surface border-border hover:border-white/20 hover:bg-white/5'
                                            }`}
                                    >
                                        <div className="flex items-start gap-3">
                                            <div className={`mt-0.5 w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${selectedIdea?.title === idea.title ? 'bg-purple-600 text-white' : 'bg-white/10 text-white/60'
                                                }`}>
                                                {idx + 1}
                                            </div>
                                            <div>
                                                <h3 className={`font-semibold mb-1 leading-tight ${selectedIdea?.title === idea.title ? 'text-purple-300' : 'text-white/90 group-hover:text-white'
                                                    }`}>{idea.title}</h3>
                                                <p className="text-xs text-muted leading-relaxed line-clamp-3">{idea.synopsis}</p>
                                            </div>
                                        </div>
                                    </button>
                                ))}
                            </div>
                        )}

                        {!isLoadingIdeas && ideas.length === 0 && !error && (
                            <div className="flex flex-col items-center justify-center p-8 text-muted border border-border border-dashed rounded-xl h-48 opacity-50">
                                <Lightbulb size={24} className="mb-3 opacity-50" />
                                <p className="text-sm text-center">Enter a movie title to generate ideas</p>
                            </div>
                        )}

                        {error && (
                            <div className="p-4 bg-red-500/10 border border-red-500/20 text-red-400 rounded-xl text-sm flex gap-3 items-start">
                                <AlertCircle size={16} className="mt-0.5 shrink-0" />
                                <p>{error}</p>
                            </div>
                        )}
                    </div>
                </div>

                {/* Right Column: Script View */}
                <div className="flex-1 bg-surface border border-border rounded-xl shadow-lg flex flex-col overflow-hidden">
                    <div className="p-4 border-b border-border bg-white/5 flex items-center gap-3">
                        <Send size={18} className="text-muted" />
                        <h2 className="font-medium text-white/90">Short Script</h2>
                    </div>

                    <div className="flex-1 p-6 overflow-y-auto">
                        {!selectedIdea && !isLoadingScript && (
                            <div className="h-full flex flex-col items-center justify-center text-muted opacity-50">
                                <Send size={32} className="mb-4 opacity-20" />
                                <p>Select an idea from the list to generate its script</p>
                            </div>
                        )}

                        {isLoadingScript && (
                            <div className="h-full flex flex-col items-center justify-center text-muted">
                                <Loader2 size={32} className="animate-spin mb-4 text-purple-400" />
                                <p className="text-sm animate-pulse">Drafting the hook, argument, and conclusion...</p>
                            </div>
                        )}

                        {!isLoadingScript && script && (
                            <div className="max-w-2xl mx-auto space-y-6">
                                <div className="bg-purple-500/5 border border-purple-500/20 rounded-lg p-4">
                                    <h3 className="text-lg font-bold text-purple-300 mb-2">{selectedIdea?.title}</h3>
                                    <p className="text-sm text-purple-200/60 italic">{selectedIdea?.synopsis}</p>
                                </div>

                                <div className="prose prose-invert max-w-none text-lg leading-relaxed text-white/90">
                                    {script.split('\n').map((paragraph, index) => (
                                        paragraph.trim() ? <p key={index} className="mb-4">{paragraph}</p> : null
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}

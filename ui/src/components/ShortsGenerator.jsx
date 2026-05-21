import { useState, useEffect, useRef } from 'react';
import { Upload, Scissors, Settings, Play, Download, Trash2, RefreshCw, ChevronLeft, Film, Loader2, CheckCircle, AlertCircle, X, Clock, Sparkles } from 'lucide-react';

const API = 'http://localhost:8000';

// ===== Subtitle style previews  =====
const SUBTITLE_STYLES = [
    { id: 'bold_white', label: 'Classic White', preview: 'text-white font-black text-shadow-lg' },
    { id: 'yellow_pop', label: 'Yellow Pop', preview: 'text-yellow-400 font-black text-shadow-lg' },
    { id: 'neon_green', label: 'Neon Green', preview: 'text-green-400 font-black text-shadow-lg' },
];

// ===== Helper: format file size  =====
function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
}

function formatDuration(sec) {
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
}

// ===== Helper: format ASS Color =====
// Converts #RRGGBB or #RRGGBBAA to ASS &HAABBGGRR
function hexToAss(hexStr) {
    if (!hexStr) return null;
    let hex = hexStr.replace('#', '');
    if (hex.length === 6) hex += 'FF'; // Default to full opacity
    if (hex.length !== 8) return null;

    const r = hex.substring(0, 2);
    const g = hex.substring(2, 4);
    const b = hex.substring(4, 6);
    // ASS format: &HAABBGGRR (AA is transparency: 00=opaque, FF=transparent)
    return `&H00${b}${g}${r}`;
}

// ============================================
// MAIN COMPONENT
// ============================================
export function ShortsGenerator() {
    const [screen, setScreen] = useState('upload'); // upload | settings | processing | results | history
    const [uploadedFile, setUploadedFile] = useState(null); // { path, filename, size }
    const [settings, setSettings] = useState({
        clip_count: 5,
        min_duration: 30,
        max_duration: 90,
        subtitles: true,
        subtitle_style: 'bold_white',
        words_per_line: 3,
        language: null,

        // Custom Options
        use_custom_style: false,
        custom_color: '#FFFFFF',
        custom_outline_color: '#000000',
        custom_fontsize: 18,
        custom_margin_v: 60,
        custom_outline: 3,
        custom_shadow: 1,
    });
    const [currentJobId, setCurrentJobId] = useState(null);
    const [jobStatus, setJobStatus] = useState(null);
    const [jobResult, setJobResult] = useState(null);
    const [jobs, setJobs] = useState([]);
    const [dragging, setDragging] = useState(false);
    const [uploading, setUploading] = useState(false);
    const [error, setError] = useState(null);
    const pollRef = useRef(null);

    // ---- Load job history on mount ----
    useEffect(() => {
        loadJobs();
    }, []);

    const loadJobs = async () => {
        try {
            const res = await fetch(`${API}/shorts/jobs`);
            const data = await res.json();
            setJobs(data || []);
        } catch { /* ignore */ }
    };

    // ---- Polling for job status ----
    useEffect(() => {
        if (!currentJobId || screen !== 'processing') return;

        const poll = async () => {
            try {
                const res = await fetch(`${API}/shorts/status/${currentJobId}`);
                const data = await res.json();
                setJobStatus(data);

                if (data.status === 'done' || data.status === 'error') {
                    clearInterval(pollRef.current);
                    // Load full result
                    const fullRes = await fetch(`${API}/shorts/job/${currentJobId}`);
                    const fullData = await fullRes.json();
                    setJobResult(fullData);
                    if (data.status === 'done') {
                        setScreen('results');
                    }
                    loadJobs();
                }
            } catch { /* ignore */ }
        };

        poll();
        pollRef.current = setInterval(poll, 2000);
        return () => clearInterval(pollRef.current);
    }, [currentJobId, screen]);

    // ---- Upload handler ----
    const handleUpload = async (file) => {
        setError(null);
        setUploading(true);
        try {
            const formData = new FormData();
            formData.append('file', file);
            const res = await fetch(`${API}/shorts/upload`, { method: 'POST', body: formData });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Upload failed');
            }
            const data = await res.json();
            setUploadedFile(data);
            setScreen('settings');
        } catch (e) {
            setError(e.message);
        } finally {
            setUploading(false);
        }
    };

    // ---- Generate handler ----
    const handleGenerate = async () => {
        setError(null);
        try {
            const body = {
                video_path: uploadedFile.path,
                clip_count: settings.clip_count,
                min_duration: settings.min_duration,
                max_duration: settings.max_duration,
                subtitles: settings.subtitles,
                subtitle_style: settings.subtitle_style,
                words_per_line: settings.words_per_line,
                language: settings.language,
            };

            if (settings.use_custom_style) {
                body.custom_subtitle_style = {
                    primary_color: hexToAss(settings.custom_color),
                    outline_color: hexToAss(settings.custom_outline_color),
                    fontsize: settings.custom_fontsize,
                    margin_v: settings.custom_margin_v,
                    outline: settings.custom_outline,
                    shadow: settings.custom_shadow,
                };
            }

            const res = await fetch(`${API}/shorts/generate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Generation failed');
            }
            const data = await res.json();
            setCurrentJobId(data.job_id);
            setJobStatus({ status: 'processing', progress: 0, progress_text: 'Запуск…' });
            setScreen('processing');
        } catch (e) {
            setError(e.message);
        }
    };

    // ---- Delete job ----
    const handleDeleteJob = async (jobId) => {
        try {
            await fetch(`${API}/shorts/job/${jobId}`, { method: 'DELETE' });
            loadJobs();
            if (currentJobId === jobId) {
                setScreen('upload');
                setCurrentJobId(null);
                setJobResult(null);
            }
        } catch { /* ignore */ }
    };

    // ---- View existing job ----
    const handleViewJob = async (jobId) => {
        try {
            const res = await fetch(`${API}/shorts/job/${jobId}`);
            const data = await res.json();
            setJobResult(data);
            setCurrentJobId(jobId);
            if (data.status === 'done') {
                setScreen('results');
            } else if (data.status === 'processing') {
                setJobStatus({ status: data.status, progress: data.progress, progress_text: data.progress_text });
                setScreen('processing');
            }
        } catch { /* ignore */ }
    };

    // ---- Drag & Drop ----
    const handleDragOver = (e) => { e.preventDefault(); setDragging(true); };
    const handleDragLeave = () => setDragging(false);
    const handleDrop = (e) => {
        e.preventDefault();
        setDragging(false);
        const file = e.dataTransfer.files[0];
        if (file) handleUpload(file);
    };

    // ===== RENDER SCREENS =====

    // --- Upload Screen ---
    const renderUpload = () => (
        <div className="flex flex-col items-center justify-center h-full gap-8 p-8">
            {/* Header */}
            <div className="text-center space-y-3">
                <div className="inline-flex items-center gap-3 text-accent bg-accent/10 px-5 py-2 rounded-full border border-accent/20">
                    <Scissors size={20} />
                    <span className="font-semibold text-sm">SHORTS GENERATOR</span>
                </div>
                <h2 className="text-3xl font-bold text-white">Создай шортсы из видео</h2>
                <p className="text-muted max-w-md">
                    Загрузи готовое видео — AI найдёт лучшие моменты, нарежет клипы
                    и добавит стилизованные субтитры. Без водяных знаков.
                </p>
            </div>

            {/* Drop Zone */}
            <div
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                className={`
          relative w-full max-w-lg aspect-video rounded-2xl border-2 border-dashed
          flex flex-col items-center justify-center gap-4 cursor-pointer
          transition-all duration-300 group
          ${dragging
                        ? 'border-accent bg-accent/10 scale-[1.02] shadow-[0_0_40px_rgba(59,130,246,0.2)]'
                        : 'border-border hover:border-accent/50 hover:bg-white/[0.02]'}
          ${uploading ? 'opacity-60 pointer-events-none' : ''}
        `}
                onClick={() => {
                    if (!uploading) {
                        const input = document.createElement('input');
                        input.type = 'file';
                        input.accept = 'video/*';
                        input.onchange = (e) => {
                            if (e.target.files[0]) handleUpload(e.target.files[0]);
                        };
                        input.click();
                    }
                }}
            >
                {uploading ? (
                    <Loader2 size={40} className="text-accent animate-spin" />
                ) : (
                    <>
                        <div className="w-16 h-16 rounded-xl bg-accent/10 border border-accent/20 flex items-center justify-center group-hover:scale-110 transition-transform">
                            <Upload size={28} className="text-accent" />
                        </div>
                        <div className="text-center">
                            <p className="text-white font-medium">Перетащи видео сюда</p>
                            <p className="text-muted text-sm mt-1">или нажми для выбора файла</p>
                            <p className="text-muted/60 text-xs mt-2">MP4, MOV, MKV, AVI, WebM</p>
                        </div>
                    </>
                )}
            </div>

            {error && (
                <div className="flex items-center gap-2 text-red-400 bg-red-400/10 px-4 py-2 rounded-lg border border-red-400/20 text-sm">
                    <AlertCircle size={16} />
                    {error}
                </div>
            )}

            {/* Job History */}
            {jobs.length > 0 && (
                <div className="w-full max-w-lg">
                    <button
                        onClick={() => setScreen('history')}
                        className="w-full flex items-center justify-between px-4 py-3 rounded-xl bg-surface/50 border border-border hover:border-accent/30 transition-colors text-sm"
                    >
                        <span className="text-muted flex items-center gap-2">
                            <Clock size={14} />
                            Предыдущие генерации
                        </span>
                        <span className="text-accent font-medium">{jobs.length}</span>
                    </button>
                </div>
            )}
        </div>
    );

    // --- Settings Screen ---
    const renderSettings = () => (
        <div className="flex flex-col h-full">
            {/* Header */}
            <div className="flex items-center gap-4 p-6 border-b border-border">
                <button onClick={() => setScreen('upload')} className="text-muted hover:text-white transition-colors">
                    <ChevronLeft size={20} />
                </button>
                <div className="flex-1">
                    <h2 className="text-lg font-bold text-white flex items-center gap-2">
                        <Settings size={18} className="text-accent" />
                        Настройки генерации
                    </h2>
                    <p className="text-muted text-sm mt-0.5">
                        {uploadedFile?.filename} • {formatSize(uploadedFile?.size || 0)}
                    </p>
                </div>
            </div>

            {/* Settings Form */}
            <div className="flex-1 overflow-y-auto p-6 space-y-6">

                {/* Clip Count */}
                <div className="space-y-2">
                    <label className="text-sm font-medium text-gray-300">Количество клипов</label>
                    <div className="flex gap-2">
                        {[3, 5, 7, 10].map(n => (
                            <button
                                key={n}
                                onClick={() => setSettings(s => ({ ...s, clip_count: n }))}
                                className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${settings.clip_count === n
                                    ? 'bg-accent text-white shadow-lg shadow-accent/30'
                                    : 'bg-surface border border-border text-muted hover:text-white hover:border-accent/30'
                                    }`}
                            >
                                {n}
                            </button>
                        ))}
                    </div>
                </div>

                {/* Duration Range */}
                <div className="space-y-2">
                    <label className="text-sm font-medium text-gray-300">Длительность клипов (секунды)</label>
                    <div className="flex items-center gap-3">
                        <div className="flex items-center gap-2">
                            <span className="text-xs text-muted">от</span>
                            <input
                                type="number"
                                value={settings.min_duration}
                                onChange={(e) => setSettings(s => ({ ...s, min_duration: parseInt(e.target.value) || 15 }))}
                                className="w-20 bg-surface border border-border rounded-lg px-3 py-2 text-sm text-white focus:border-accent focus:outline-none"
                                min="15" max="120"
                            />
                        </div>
                        <span className="text-muted">—</span>
                        <div className="flex items-center gap-2">
                            <span className="text-xs text-muted">до</span>
                            <input
                                type="number"
                                value={settings.max_duration}
                                onChange={(e) => setSettings(s => ({ ...s, max_duration: parseInt(e.target.value) || 60 }))}
                                className="w-20 bg-surface border border-border rounded-lg px-3 py-2 text-sm text-white focus:border-accent focus:outline-none"
                                min="30" max="180"
                            />
                        </div>
                        <span className="text-xs text-muted">сек</span>
                    </div>
                </div>

                {/* Subtitles Toggle */}
                <div className="space-y-3">
                    <div className="flex items-center justify-between">
                        <label className="text-sm font-medium text-gray-300">Субтитры</label>
                        <button
                            onClick={() => setSettings(s => ({ ...s, subtitles: !s.subtitles }))}
                            className={`relative w-11 h-6 rounded-full transition-colors ${settings.subtitles ? 'bg-accent' : 'bg-border'
                                }`}
                        >
                            <div className={`absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${settings.subtitles ? 'translate-x-[22px]' : 'translate-x-0.5'
                                }`} />
                        </button>
                    </div>

                    {/* Subtitle Style */}
                    {settings.subtitles && (
                        <div className="space-y-2 pl-1">
                            <label className="text-xs text-muted">Стиль субтитров</label>
                            <div className="flex gap-2">
                                {SUBTITLE_STYLES.map(style => (
                                    <button
                                        key={style.id}
                                        onClick={() => setSettings(s => ({ ...s, subtitle_style: style.id }))}
                                        className={`flex-1 py-3 rounded-xl border text-center transition-all ${settings.subtitle_style === style.id
                                            ? 'border-accent bg-accent/10 shadow-lg shadow-accent/10'
                                            : 'border-border bg-surface hover:border-accent/30'
                                            }`}
                                    >
                                        <div className="bg-black/40 mx-3 py-2 rounded-lg mb-2">
                                            <span className={`text-xs font-black uppercase tracking-wider ${style.id === 'bold_white' ? 'text-white' :
                                                style.id === 'yellow_pop' ? 'text-yellow-400' :
                                                    'text-green-400'
                                                }`} style={{ textShadow: '2px 2px 4px rgba(0,0,0,0.8)' }}>
                                                SAMPLE TEXT
                                            </span>
                                        </div>
                                        <span className="text-xs text-muted">{style.label}</span>
                                    </button>
                                ))}
                            </div>

                            {/* Words per line */}
                            <div className="flex items-center gap-3 mt-2">
                                <label className="text-xs text-muted">Слов на строку:</label>
                                <div className="flex gap-1">
                                    {[2, 3, 4, 5].map(n => (
                                        <button
                                            key={n}
                                            onClick={() => setSettings(s => ({ ...s, words_per_line: n }))}
                                            className={`w-8 h-8 rounded-lg text-xs font-medium transition-all ${settings.words_per_line === n
                                                ? 'bg-accent text-white'
                                                : 'bg-surface border border-border text-muted hover:text-white'
                                                }`}
                                        >
                                            {n}
                                        </button>
                                    ))}
                                </div>
                            </div>
                            {/* Custom Subtitle Styles */}
                            <div className="mt-4 pt-4 border-t border-border/50">
                                <div className="flex items-center justify-between mb-3">
                                    <label className="text-xs font-semibold text-gray-300">Кастомный стиль</label>
                                    <button
                                        onClick={() => setSettings(s => ({ ...s, use_custom_style: !s.use_custom_style }))}
                                        className={`relative w-9 h-5 rounded-full transition-colors ${settings.use_custom_style ? 'bg-accent' : 'bg-border'}`}
                                    >
                                        <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${settings.use_custom_style ? 'translate-x-[18px]' : 'translate-x-0.5'}`} />
                                    </button>
                                </div>

                                {settings.use_custom_style && (
                                    <div className="space-y-4 bg-black/20 p-4 rounded-xl border border-border/50">

                                        {/* Preview block */}
                                        <div className="flex justify-center mb-4">
                                            <div className="relative w-full max-w-[180px] aspect-[9/16] bg-black rounded-lg overflow-hidden flex flex-col items-center border border-border/50 shadow-inner">
                                                {/* Background Video */}
                                                {uploadedFile && (
                                                    <video
                                                        src={`${API}/shorts/download_raw?path=${encodeURIComponent(uploadedFile.path)}`}
                                                        className="absolute inset-0 w-full h-full object-cover opacity-50 pointer-events-none"
                                                        muted
                                                        loop
                                                        autoPlay
                                                        playsInline
                                                    />
                                                )}

                                                {/* Subtitle Overlay Container */}
                                                <div
                                                    className="absolute inset-x-0 flex justify-center text-center px-4"
                                                    style={{
                                                        // ASS margin_v is from bottom. Scale 1920 to container height, or use percentage.
                                                        bottom: `${Math.max(5, (settings.custom_margin_v / 1920) * 100)}%`
                                                    }}
                                                >
                                                    <span
                                                        className="font-black uppercase tracking-wider z-10 leading-tight"
                                                        style={{
                                                            color: settings.custom_color,
                                                            // Scale fontsize strictly. If 1080p is ~3x this container size
                                                            fontSize: `${Math.max(10, settings.custom_fontsize / 3)}px`,
                                                            WebkitTextStroke: `${Math.max(1, settings.custom_outline / 3)}px ${settings.custom_outline_color}`,
                                                            textShadow: settings.custom_shadow > 0 ? `0px ${settings.custom_shadow / 2}px ${settings.custom_shadow}px ${settings.custom_outline_color}` : 'none'
                                                        }}
                                                    >
                                                        ПРИМЕР
                                                    </span>
                                                </div>
                                            </div>
                                        </div>

                                        <div className="grid grid-cols-2 gap-4">
                                            {/* Colors */}
                                            <div className="space-y-1">
                                                <label className="text-xs text-muted">Цвет текста</label>
                                                <div className="flex items-center gap-2">
                                                    <input
                                                        type="color"
                                                        value={settings.custom_color}
                                                        onChange={(e) => setSettings(s => ({ ...s, custom_color: e.target.value }))}
                                                        className="w-8 h-8 rounded cursor-pointer bg-transparent border-0 p-0"
                                                    />
                                                    <span className="text-xs font-mono text-gray-400">{settings.custom_color}</span>
                                                </div>
                                            </div>
                                            <div className="space-y-1">
                                                <label className="text-xs text-muted">Цвет обводки/тени</label>
                                                <div className="flex items-center gap-2">
                                                    <input
                                                        type="color"
                                                        value={settings.custom_outline_color}
                                                        onChange={(e) => setSettings(s => ({ ...s, custom_outline_color: e.target.value }))}
                                                        className="w-8 h-8 rounded cursor-pointer bg-transparent border-0 p-0"
                                                    />
                                                    <span className="text-xs font-mono text-gray-400">{settings.custom_outline_color}</span>
                                                </div>
                                            </div>
                                        </div>

                                        {/* Sliders */}
                                        <div className="space-y-3">
                                            <div className="flex items-center justify-between gap-3">
                                                <label className="text-xs text-muted w-24">Размер ({settings.custom_fontsize})</label>
                                                <input
                                                    type="range" min="10" max="40" step="1"
                                                    value={settings.custom_fontsize}
                                                    onChange={(e) => setSettings(s => ({ ...s, custom_fontsize: parseInt(e.target.value) }))}
                                                    className="flex-1 accent-accent"
                                                />
                                            </div>

                                            <div className="flex items-center justify-between gap-3">
                                                <label className="text-xs text-muted w-24">Толщина ({settings.custom_outline})</label>
                                                <input
                                                    type="range" min="0" max="10" step="1"
                                                    value={settings.custom_outline}
                                                    onChange={(e) => setSettings(s => ({ ...s, custom_outline: parseInt(e.target.value) }))}
                                                    className="flex-1 accent-accent"
                                                />
                                            </div>

                                            <div className="flex items-center justify-between gap-3">
                                                <label className="text-xs text-muted w-24">Тень ({settings.custom_shadow})</label>
                                                <input
                                                    type="range" min="0" max="10" step="1"
                                                    value={settings.custom_shadow}
                                                    onChange={(e) => setSettings(s => ({ ...s, custom_shadow: parseInt(e.target.value) }))}
                                                    className="flex-1 accent-accent"
                                                />
                                            </div>

                                            <div className="flex items-center justify-between gap-3">
                                                <label className="text-xs text-muted w-24">Отступ ({settings.custom_margin_v})</label>
                                                <input
                                                    type="range" min="10" max="300" step="5"
                                                    value={settings.custom_margin_v}
                                                    onChange={(e) => setSettings(s => ({ ...s, custom_margin_v: parseInt(e.target.value) }))}
                                                    className="flex-1 accent-accent"
                                                />
                                            </div>
                                        </div>

                                    </div>
                                )}
                            </div>
                        </div>
                    )}
                </div>

                {/* Language */}
                <div className="space-y-2">
                    <label className="text-sm font-medium text-gray-300">Язык (опционально)</label>
                    <select
                        value={settings.language || ''}
                        onChange={(e) => setSettings(s => ({ ...s, language: e.target.value || null }))}
                        className="w-full bg-surface border border-border rounded-lg px-3 py-2 text-sm text-white focus:border-accent focus:outline-none"
                    >
                        <option value="">Авто-определение</option>
                        <option value="ru">Русский</option>
                        <option value="en">English</option>
                        <option value="es">Español</option>
                        <option value="fr">Français</option>
                        <option value="de">Deutsch</option>
                        <option value="ja">日本語</option>
                        <option value="ko">한국어</option>
                        <option value="zh">中文</option>
                    </select>
                </div>
            </div>

            {/* Generate Button */}
            <div className="p-6 border-t border-border">
                {error && (
                    <div className="mb-3 flex items-center gap-2 text-red-400 text-sm">
                        <AlertCircle size={14} />
                        {error}
                    </div>
                )}
                <button
                    onClick={handleGenerate}
                    className="w-full py-3.5 rounded-xl bg-gradient-to-r from-accent to-purple-500 text-white font-semibold
            hover:shadow-[0_0_30px_rgba(59,130,246,0.3)] transition-all duration-300 flex items-center justify-center gap-2"
                >
                    <Sparkles size={18} />
                    Генерировать шортсы
                </button>
            </div>
        </div>
    );

    // --- Processing Screen ---
    const renderProcessing = () => {
        const progress = jobStatus?.progress || 0;
        const text = jobStatus?.progress_text || 'Запуск…';
        const isError = jobStatus?.status === 'error';

        return (
            <div className="flex flex-col items-center justify-center h-full gap-8 p-8">
                <div className="relative w-40 h-40">
                    {/* Background circle */}
                    <svg className="w-full h-full -rotate-90" viewBox="0 0 100 100">
                        <circle cx="50" cy="50" r="45" fill="none" stroke="currentColor" className="text-border" strokeWidth="6" />
                        <circle
                            cx="50" cy="50" r="45" fill="none" strokeWidth="6" strokeLinecap="round"
                            className={isError ? 'text-red-500' : 'text-accent'}
                            style={{
                                strokeDasharray: `${2 * Math.PI * 45}`,
                                strokeDashoffset: `${2 * Math.PI * 45 * (1 - progress / 100)}`,
                                transition: 'stroke-dashoffset 0.5s ease',
                            }}
                        />
                    </svg>
                    <div className="absolute inset-0 flex items-center justify-center">
                        {isError ? (
                            <AlertCircle size={32} className="text-red-500" />
                        ) : (
                            <span className="text-2xl font-bold text-white">{progress}%</span>
                        )}
                    </div>
                </div>

                <div className="text-center space-y-2 max-w-md">
                    <h3 className={`text-lg font-semibold ${isError ? 'text-red-400' : 'text-white'}`}>
                        {isError ? 'Ошибка' : progress >= 100 ? 'Готово!' : 'Генерация…'}
                    </h3>
                    <p className="text-muted text-sm">{text}</p>
                </div>

                {isError && (
                    <button
                        onClick={() => { setScreen('settings'); setError(null); }}
                        className="px-6 py-2 rounded-lg bg-surface border border-border text-muted hover:text-white transition-colors text-sm"
                    >
                        ← Назад к настройкам
                    </button>
                )}
            </div>
        );
    };

    // --- Results Screen ---
    const renderResults = () => {
        const clips = jobResult?.clips?.filter(c => !c.error) || [];
        const errors = jobResult?.clips?.filter(c => c.error) || [];

        return (
            <div className="flex flex-col h-full">
                {/* Header */}
                <div className="flex items-center gap-4 p-6 border-b border-border">
                    <button
                        onClick={() => { setScreen('upload'); setCurrentJobId(null); setJobResult(null); setUploadedFile(null); }}
                        className="text-muted hover:text-white transition-colors"
                    >
                        <ChevronLeft size={20} />
                    </button>
                    <div className="flex-1">
                        <h2 className="text-lg font-bold text-white flex items-center gap-2">
                            <CheckCircle size={18} className="text-green-400" />
                            Готово — {clips.length} клипов
                        </h2>
                        <p className="text-muted text-sm mt-0.5">
                            {jobResult?.original_filename}
                            {errors.length > 0 && <span className="text-red-400 ml-2">({errors.length} с ошибками)</span>}
                        </p>
                    </div>
                    <button
                        onClick={() => handleDeleteJob(currentJobId)}
                        className="p-2 rounded-lg text-muted hover:text-red-400 hover:bg-red-400/10 transition-colors"
                        title="Удалить"
                    >
                        <Trash2 size={16} />
                    </button>
                </div>

                {/* Clips Grid */}
                <div className="flex-1 overflow-y-auto p-6">
                    <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                        {clips.map((clip, i) => (
                            <ClipCard
                                key={i}
                                clip={clip}
                                jobId={currentJobId}
                            />
                        ))}
                    </div>
                </div>
            </div>
        );
    };

    // --- History Screen ---
    const renderHistory = () => (
        <div className="flex flex-col h-full">
            <div className="flex items-center gap-4 p-6 border-b border-border">
                <button onClick={() => setScreen('upload')} className="text-muted hover:text-white transition-colors">
                    <ChevronLeft size={20} />
                </button>
                <h2 className="text-lg font-bold text-white">История генераций</h2>
            </div>

            <div className="flex-1 overflow-y-auto p-6 space-y-3">
                {jobs.length === 0 && (
                    <p className="text-muted text-sm text-center py-12">Нет предыдущих генераций</p>
                )}
                {jobs.map(job => (
                    <div
                        key={job.job_id}
                        className="flex items-center gap-4 p-4 rounded-xl bg-surface/50 border border-border hover:border-accent/30 transition-colors group"
                    >
                        <div className="w-10 h-10 rounded-lg bg-accent/10 flex items-center justify-center flex-shrink-0">
                            {job.status === 'done' ? (
                                <CheckCircle size={18} className="text-green-400" />
                            ) : job.status === 'processing' ? (
                                <Loader2 size={18} className="text-accent animate-spin" />
                            ) : job.status === 'error' ? (
                                <AlertCircle size={18} className="text-red-400" />
                            ) : (
                                <Film size={18} className="text-muted" />
                            )}
                        </div>

                        <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-white truncate">{job.original_filename || job.job_id}</p>
                            <p className="text-xs text-muted">
                                {job.status === 'done' && `${job.clip_count} клипов`}
                                {job.status === 'processing' && `${job.progress}% — ${job.progress_text}`}
                                {job.status === 'error' && 'Ошибка'}
                                {job.status === 'pending' && 'Ожидание'}
                            </p>
                        </div>

                        <div className="flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                            {(job.status === 'done' || job.status === 'processing') && (
                                <button
                                    onClick={() => handleViewJob(job.job_id)}
                                    className="p-2 rounded-lg text-muted hover:text-accent hover:bg-accent/10 transition-colors"
                                >
                                    <Play size={14} />
                                </button>
                            )}
                            <button
                                onClick={() => handleDeleteJob(job.job_id)}
                                className="p-2 rounded-lg text-muted hover:text-red-400 hover:bg-red-400/10 transition-colors"
                            >
                                <Trash2 size={14} />
                            </button>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );

    // ===== Main render =====
    return (
        <div className="h-full flex flex-col bg-background">
            {screen === 'upload' && renderUpload()}
            {screen === 'settings' && renderSettings()}
            {screen === 'processing' && renderProcessing()}
            {screen === 'results' && renderResults()}
            {screen === 'history' && renderHistory()}
        </div>
    );
}

// ===== Clip Card Component =====
function ClipCard({ clip, jobId }) {
    const [playing, setPlaying] = useState(false);
    const videoRef = useRef(null);

    const thumbUrl = `${API}/shorts/thumbnail/${jobId}/${clip.index}`;
    const videoUrl = `${API}/shorts/download/${jobId}/${clip.index}`;

    const handlePlayToggle = () => {
        if (playing) {
            videoRef.current?.pause();
        } else {
            videoRef.current?.play();
        }
        setPlaying(!playing);
    };

    return (
        <div className="group rounded-xl border border-border bg-surface/50 overflow-hidden hover:border-accent/30 transition-all hover:shadow-lg hover:shadow-accent/5">
            {/* Preview */}
            <div className="relative aspect-[9/16] bg-black cursor-pointer" onClick={handlePlayToggle}>
                {!playing ? (
                    <>
                        <img
                            src={thumbUrl}
                            alt={clip.title}
                            className="w-full h-full object-cover"
                            onError={(e) => { e.target.style.display = 'none'; }}
                        />
                        <div className="absolute inset-0 flex items-center justify-center bg-black/30 opacity-0 group-hover:opacity-100 transition-opacity">
                            <div className="w-12 h-12 rounded-full bg-white/20 backdrop-blur-sm flex items-center justify-center">
                                <Play size={20} className="text-white ml-0.5" />
                            </div>
                        </div>
                    </>
                ) : (
                    <video
                        ref={videoRef}
                        src={videoUrl}
                        className="w-full h-full object-cover"
                        autoPlay
                        onEnded={() => setPlaying(false)}
                        controls
                    />
                )}

                {/* Duration badge */}
                <div className="absolute bottom-2 right-2 bg-black/70 backdrop-blur-sm text-white text-xs px-2 py-1 rounded-md">
                    {formatDuration(clip.duration)}
                </div>

                {/* Score badge */}
                <div className="absolute top-2 right-2 bg-accent/80 backdrop-blur-sm text-white text-xs px-2 py-1 rounded-md font-medium">
                    ★ {clip.score}/10
                </div>
            </div>

            {/* Info */}
            <div className="p-3 space-y-2">
                <h4 className="text-sm font-semibold text-white truncate">{clip.title}</h4>
                {clip.hook && (
                    <p className="text-xs text-muted line-clamp-2">{clip.hook}</p>
                )}

                <div className="flex items-center justify-between pt-1">
                    <span className="text-xs text-muted">{formatSize(clip.file_size)}</span>
                    <a
                        href={videoUrl}
                        download={`short_${clip.index}.mp4`}
                        className="flex items-center gap-1 text-xs text-accent hover:text-accent/80 transition-colors font-medium"
                        onClick={(e) => e.stopPropagation()}
                    >
                        <Download size={12} />
                        Скачать
                    </a>
                </div>
            </div>
        </div>
    );
}

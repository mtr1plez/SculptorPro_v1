import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import {
    ArrowLeft, Play, Pause, RefreshCw, Scissors, FileVideo, Save,
    Film, Loader2, MousePointerSquareDashed, Upload, Mic, X, GripVertical, Clock,
    ChevronDown, ChevronRight, User, Shuffle, ArrowRightLeft, Music, Volume2, VolumeX,
    FolderPlus, Users, List, Magnet, Wand2
} from 'lucide-react';
import WaveSurfer from 'wavesurfer.js';
import { AudioRecorder } from './AudioRecorder';
import { electronAPI } from '../lib/electron';

// ─── Helpers ───────────────────────────────────────────────────────────────────

const PIXELS_PER_SECOND = 12; // zoom level for timeline
const MIN_CLIP_DURATION = 2;  // minimum episode clip duration in seconds

function formatTime(seconds) {
    if (!seconds || seconds < 0) seconds = 0;
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function episodeColorHash(str) {
    if (!str) return 'rgba(168, 85, 247, 0.85)';
    let hash = 0;
    for (let i = 0; i < str.length; i++) hash = str.charCodeAt(i) + ((hash << 5) - hash);
    const h = Math.abs(hash) % 360;
    return `hsl(${h}, 55%, 40%)`;
}


// ─── Main Component ────────────────────────────────────────────────────────────

export function SegmentedProjectDetail({ project, onBack, buildProgress }) {
    const [details, setDetails] = useState(null);
    const [transcript, setTranscript] = useState(null);
    const [library, setLibrary] = useState([]);

    const [isPlaying, setIsPlaying] = useState(false);
    const [isTranscribing, setIsTranscribing] = useState(false);
    const [isBuilding, setIsBuilding] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const [isUploading, setIsUploading] = useState(false);
    const [isRecorderOpen, setIsRecorderOpen] = useState(false);
    const [isWaveformLoaded, setIsWaveformLoaded] = useState(false);
    const [isAutoPlanOpen, setIsAutoPlanOpen] = useState(false);
    const [isAutoPlanning, setIsAutoPlanning] = useState(false);
    const [autoPlanText, setAutoPlanText] = useState('');
    const [autoPlanSources, setAutoPlanSources] = useState(new Set());
    const [autoPlanGroups, setAutoPlanGroups] = useState(new Set());

    // Model selector
    const [availableModels, setAvailableModels] = useState([]);
    const [selectedModel, setSelectedModel] = useState('flash-3.1');

    // Timeline clips = episodes placed on the video track
    const [clips, setClips] = useState([]);

    // Music track clips (M1)
    // Music Generation State
    const [isMusicModalOpen, setIsMusicModalOpen] = useState(false);
    const [musicTags, setMusicTags] = useState("");
    const [musicPrompt, setMusicPrompt] = useState("");
    const [isAnalyzingMood, setIsAnalyzingMood] = useState(false);
    const [musicGenStatus, setMusicGenStatus] = useState(null); // { percent, status }
    const [sunoCookies, setSunoCookies] = useState(null);

    // Music playback
    const [musicVolume, setMusicVolume] = useState(0.3);
    const [isMusicMuted, setIsMusicMuted] = useState(false);
    const [isUploadingMusic, setIsUploadingMusic] = useState(false);
    const musicAudioRef = useRef(null);
    const musicFileInputRef = useRef(null);

    // Drag from library
    const [draggedEpisode, setDraggedEpisode] = useState(null);

    // Resize state
    const [resizing, setResizing] = useState(null); // { clipId, edge: 'left'|'right', startX, origStart, origDuration }
    const [isMagnetEnabled, setIsMagnetEnabled] = useState(false);

    // Playhead
    const [playheadTime, setPlayheadTime] = useState(0);

    // Playback speed
    const SPEED_OPTIONS = [1, 1.5, 2];
    const [playbackRate, setPlaybackRate] = useState(1);

    // Library sidebar: track expanded sources and cached episodes
    const [expandedSources, setExpandedSources] = useState({});
    const [sourceEpisodes, setSourceEpisodes] = useState({});
    const [sourceCharacters, setSourceCharacters] = useState({});
    const [sourceTab, setSourceTab] = useState({}); // alias -> 'episodes' | 'characters'

    // Groups
    const [groups, setGroups] = useState([]);
    const [expandedGroups, setExpandedGroups] = useState({});
    const [pendingGroupDrop, setPendingGroupDrop] = useState(null);

    const waveformRef = useRef(null);
    const wavesurfer = useRef(null);
    const audioRef = useRef(null);
    const timelineScrollRef = useRef(null);
    const fileInputRef = useRef(null);
    const rulerRef = useRef(null);

    // Scrubber drag state
    const [isScrubbing, setIsScrubbing] = useState(false);
    const scrubStartRef = useRef(null);

    const audioDuration = transcript?.duration || 0;
    const timelineWidth = Math.max(800, audioDuration * PIXELS_PER_SECOND);

    const transcriptText = useMemo(() => (
        transcript?.batches?.map(b => b.segments?.map(s => s.text).join(" ")).join("\n\n") || ""
    ), [transcript]);

    const transcriptBoundaries = useMemo(() => {
        if (!transcript?.batches) return [];

        const points = new Set([0]);
        if (audioDuration > 0) points.add(audioDuration);

        transcript.batches.forEach((batch) => {
            batch.segments?.forEach((seg) => {
                if (Number.isFinite(seg.start)) points.add(Math.max(0, seg.start));
                if (Number.isFinite(seg.end)) points.add(Math.max(0, seg.end));
            });
        });

        return [...points]
            .filter((point) => point >= 0 && (!audioDuration || point <= audioDuration))
            .sort((a, b) => a - b);
    }, [transcript, audioDuration]);

    const snapToTranscriptBoundary = useCallback((time, minTime = 0, maxTime = audioDuration) => {
        const clamped = Math.max(minTime, Math.min(time, maxTime));
        if (!isMagnetEnabled || transcriptBoundaries.length === 0) return clamped;

        let best = clamped;
        let bestDistance = Infinity;
        transcriptBoundaries.forEach((point) => {
            if (point < minTime || point > maxTime) return;
            const distance = Math.abs(point - clamped);
            if (distance < bestDistance) {
                best = point;
                bestDistance = distance;
            }
        });
        return best;
    }, [audioDuration, isMagnetEnabled, transcriptBoundaries]);

    // ─── Data Loading ────────────────────────────────────────────────────────

    useEffect(() => {
        fetchLibrary();
        fetchDetails();
        fetchTranscript();
        fetchGroups();
        fetchModels();
    }, [project.name]);

    const fetchLibrary = async () => {
        try {
            const res = await fetch('http://localhost:8000/library');
            if (res.ok) {
                const data = await res.json();
                // Only show ready sources
                setLibrary(data.filter(s => s.ready));
            }
        } catch (e) { console.error("Library load error", e); }
    };

    const fetchGroups = async () => {
        try {
            const res = await fetch('http://localhost:8000/groups');
            if (res.ok) setGroups(await res.json());
        } catch (e) { console.error('Groups load error', e); }
    };

    const fetchModels = async () => {
        try {
            const res = await fetch('http://localhost:8000/models');
            if (res.ok) {
                const data = await res.json();
                setAvailableModels(data);
                const def = data.find(m => m.default);
                if (def) setSelectedModel(def.key);
            }
        } catch (e) { console.error('Models load error', e); }
    };

    const toggleSource = async (alias) => {
        const isExpanded = expandedSources[alias];
        if (isExpanded) {
            setExpandedSources(prev => ({ ...prev, [alias]: false }));
            return;
        }
        // Expand and fetch episodes if not cached
        setExpandedSources(prev => ({ ...prev, [alias]: true }));
        // Fetch both episodes and characters in parallel
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

    const fetchDetails = async () => {
        try {
            const res = await fetch(`http://localhost:8000/projects/${project.name}`);
            if (res.ok) {
                const data = await res.json();
                setDetails(data);
            }
        } catch (e) { console.error("Failed to load details"); }
    };

    const fetchTranscript = async () => {
        try {
            const res = await fetch(`http://localhost:8000/projects/${project.name}/transcript`);
            if (res.ok) {
                const data = await res.json();
                if (data && data.batches && data.batches.length > 0) {
                    setTranscript(data);
                }
            }
        } catch (e) { console.error("Failed to load transcript"); }
    };

    // ─── Restore saved clips from project meta ───────────────────────────────

    useEffect(() => {
        if (!details?.segmented_timeline || !transcript) return;
        if (clips.length > 0) return; // already loaded

        const saved = details.segmented_timeline;
        if (saved.length > 0) {
            setClips(saved.map((c, i) => ({
                id: c.id || `clip-${Date.now()}-${i}`,
                source_alias: c.source_alias,
                episode_id: c.episode_id,
                episode_name: c.episode_name,
                timeline_start: c.timeline_start || 0,
                timeline_duration: c.timeline_duration || 10,
                clip_type: c.clip_type || 'episode',
                character_name: c.character_name || null,
                matcher_mode: c.matcher_mode || 'sequential',
                group_items: c.clip_type === 'group' ? c.group_items : undefined,
                group_selection_mode: c.clip_type === 'group' ? (c.group_selection_mode || 'score') : undefined,
            })));
        }
    }, [details, transcript]);


    // ─── Native Audio & WaveSurfer ───────────────────────────────────────────

    useEffect(() => {
        console.log("Audio useEffect running", { detailsReady: details?.audio_ready, filename: details?.audio_filename, ref: !!waveformRef.current });
        if (!details?.audio_ready || !details?.audio_filename) return;

        let cancelled = false;

        const ts = Date.now();
        const fn = encodeURIComponent(details.audio_filename);
        const pn = encodeURIComponent(project.name);
        const audioUrl = `http://localhost:8000/projects/${pn}/audio/${fn}/play?t=${ts}`;
        const peaksUrl = `http://localhost:8000/projects/${pn}/audio/${fn}/peaks`;
        console.log("Audio URL is", audioUrl);

        // 1. Instantly initialize Native Audio for immediate playback
        const audioEl = new Audio();
        audioEl.src = audioUrl;
        audioEl.preload = 'metadata';
        audioRef.current = audioEl;

        setIsWaveformLoaded(false);

        const handleTimeUpdate = () => {
            const t = audioEl.currentTime;
            setPlayheadTime(t);
            // Auto-scroll to keep playhead visible
            if (timelineScrollRef.current && !isScrubbing) {
                const scrollEl = timelineScrollRef.current;
                const playheadX = t * PIXELS_PER_SECOND + 64;
                const visibleLeft = scrollEl.scrollLeft;
                const visibleRight = visibleLeft + scrollEl.clientWidth;
                if (playheadX > visibleRight - 60 || playheadX < visibleLeft + 60) {
                    scrollEl.scrollLeft = playheadX - scrollEl.clientWidth / 3;
                }
            }
        };

        audioEl.playbackRate = playbackRate;
        audioEl.addEventListener('play', () => setIsPlaying(true));
        audioEl.addEventListener('pause', () => setIsPlaying(false));
        audioEl.addEventListener('ended', () => setIsPlaying(false));
        audioEl.addEventListener('timeupdate', handleTimeUpdate);

        audioEl.addEventListener('error', (e) => {
            console.error('Audio native error:', e);
        });

        // 2. Fetch peaks and initialize WaveSurfer purely for visuals, without blocking
        const initWaveSurfer = async () => {
            if (!waveformRef.current) return;
            if (wavesurfer.current) wavesurfer.current.destroy();

            let peakData = null;
            try {
                const peakRes = await fetch(peaksUrl);
                if (peakRes.ok) peakData = await peakRes.json();
            } catch (e) {
                console.warn('[Peaks] Failed to fetch:', e);
            }

            if (cancelled) return;

            const wsOptions = {
                container: waveformRef.current,
                waveColor: '#4ade80',
                progressColor: '#22c55e',
                cursorColor: 'transparent',
                cursorWidth: 0,
                barWidth: 2,
                barGap: 2,
                barRadius: 2,
                height: 72,
                normalize: true,
                interact: false,
                media: audioEl, // Sync visuals directly with our native audio element
            };

            if (peakData?.peaks?.length) {
                wsOptions.peaks = [peakData.peaks];
                // We do NOT set duration here. Duration comes from loadedmetadata natively.
            } else {
                audioEl.preload = 'auto'; // Needed for fallback
            }

            wavesurfer.current = WaveSurfer.create(wsOptions);

            wavesurfer.current.on('ready', () => setIsWaveformLoaded(true));
            wavesurfer.current.on('error', (err) => {
                console.error('[WaveSurfer] Visuals error:', err);
                setIsWaveformLoaded(true); // Remove loading indicator on error
            });
        };

        initWaveSurfer();

        return () => {
            cancelled = true;
            audioEl.pause();
            audioEl.src = '';
            audioEl.removeEventListener('timeupdate', handleTimeUpdate);
            if (wavesurfer.current) wavesurfer.current.destroy();
        };
    }, [details?.audio_ready, details?.audio_filename]);

    // ─── Music Audio Playback (syncs with main audio) ──────────────────────────

    useEffect(() => {
        if (!details?.music_track) {
            // Cleanup if music was removed
            if (musicAudioRef.current) {
                musicAudioRef.current.pause();
                musicAudioRef.current.src = '';
                musicAudioRef.current = null;
            }
            return;
        }

        const musicUrl = `http://localhost:8000/music/${encodeURIComponent(project.name)}/play?t=${Date.now()}`;
        const musicEl = new Audio();
        musicEl.src = musicUrl;
        musicEl.loop = true;
        musicEl.volume = isMusicMuted ? 0 : musicVolume;
        musicEl.preload = 'auto';
        musicAudioRef.current = musicEl;

        // Sync music play/pause/seek with main audio
        const mainAudio = audioRef.current;
        if (mainAudio) {
            const onPlay = () => { musicEl.currentTime = mainAudio.currentTime; musicEl.play().catch(() => { }); };
            const onPause = () => musicEl.pause();
            const onSeeked = () => { musicEl.currentTime = mainAudio.currentTime; };

            mainAudio.addEventListener('play', onPlay);
            mainAudio.addEventListener('pause', onPause);
            mainAudio.addEventListener('seeked', onSeeked);

            // If main is already playing, start music too
            if (!mainAudio.paused) {
                musicEl.currentTime = mainAudio.currentTime;
                musicEl.play().catch(() => { });
            }

            return () => {
                mainAudio.removeEventListener('play', onPlay);
                mainAudio.removeEventListener('pause', onPause);
                mainAudio.removeEventListener('seeked', onSeeked);
                musicEl.pause();
                musicEl.src = '';
            };
        }

        return () => {
            musicEl.pause();
            musicEl.src = '';
        };
    }, [details?.music_track]);

    // Update music volume reactively
    useEffect(() => {
        if (musicAudioRef.current) {
            musicAudioRef.current.volume = isMusicMuted ? 0 : musicVolume;
        }
    }, [musicVolume, isMusicMuted]);

    // ─── Music Generation Polling ──────────────────────────────────────────────

    const pollMusicStatus = useCallback(async () => {
        try {
            const res = await fetch(`http://localhost:8000/music/${project.name}/status`);
            if (res.ok) {
                const data = await res.json();
                if (data.percent !== -1) {
                    setMusicGenStatus(data);
                    // Check if done
                    if (data.percent >= 100) {
                        setMusicGenStatus(null);
                        setIsMusicModalOpen(false);
                        // Refresh details to load the new track
                        fetchDetails();
                    }
                } else {
                    setMusicGenStatus(null);
                }
            }
        } catch (e) {
            console.error(e);
        }
    }, [project.name]);

    useEffect(() => {
        let interval;
        if (musicGenStatus && musicGenStatus.percent > 0 && musicGenStatus.percent < 100) {
            interval = setInterval(pollMusicStatus, 3000);
        } else if (!musicGenStatus) {
            // Check once on mount or occasionally
            pollMusicStatus();
        }
        return () => clearInterval(interval);
    }, [musicGenStatus, pollMusicStatus]);


    // ─── Actions ─────────────────────────────────────────────────────────────

    const openAutoPlan = () => {
        setAutoPlanText(autoPlanText || transcriptText);
        setAutoPlanSources(new Set());
        setAutoPlanGroups(new Set());
        setIsAutoPlanOpen(true);
    };

    const toggleAutoPlanSource = (alias) => {
        setAutoPlanSources(prev => {
            const next = new Set(prev);
            if (next.has(alias)) next.delete(alias);
            else next.add(alias);
            return next;
        });
    };

    const toggleAutoPlanGroup = (groupId) => {
        setAutoPlanGroups(prev => {
            const next = new Set(prev);
            if (next.has(groupId)) next.delete(groupId);
            else next.add(groupId);
            return next;
        });
    };

    const handleAutoPlanTimeline = async () => {
        if (!autoPlanText.trim()) {
            alert("Paste the exact script text first.");
            return;
        }
        if (autoPlanSources.size === 0 && autoPlanGroups.size === 0) {
            alert("Select at least one movie, series, or group.");
            return;
        }

        setIsAutoPlanning(true);
        try {
            const res = await fetch(`http://localhost:8000/projects/${project.name}/segmented_timeline/auto_plan`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    script_text: autoPlanText,
                    source_aliases: Array.from(autoPlanSources),
                    group_ids: Array.from(autoPlanGroups),
                    model: selectedModel,
                    save: true
                })
            });

            if (!res.ok) {
                const err = await res.json().catch(() => null);
                alert(err?.detail || "Auto timeline planning failed.");
                return;
            }

            const data = await res.json();
            setClips((data.items || []).map((c, i) => ({
                id: c.id || `auto-${Date.now()}-${i}`,
                source_alias: c.source_alias,
                episode_id: c.episode_id || null,
                episode_name: c.episode_name || c.character_name || 'Auto source',
                timeline_start: c.timeline_start || 0,
                timeline_duration: c.timeline_duration || 10,
                clip_type: c.clip_type || 'episode',
                character_name: c.character_name || null,
                matcher_mode: c.matcher_mode || (c.clip_type === 'character' ? 'chaotic' : 'sequential'),
                group_items: c.clip_type === 'group' ? c.group_items : undefined,
                group_selection_mode: c.clip_type === 'group' ? (c.group_selection_mode || 'score') : undefined,
            })));
            await fetchDetails();
            setIsAutoPlanOpen(false);
        } catch (e) {
            console.error(e);
            alert("Error connecting to server");
        } finally {
            setIsAutoPlanning(false);
        }
    };

    const handleTranscribe = async () => {
        setIsTranscribing(true);
        try {
            const res = await fetch(`http://localhost:8000/projects/${project.name}/audio/transcribe`, { method: 'POST' });
            if (res.ok) await fetchTranscript();
            else alert("Transcription failed.");
        } catch (e) { alert("Error connecting to server"); }
        setIsTranscribing(false);
    };

    const handleSaveTimeline = async () => {
        setIsSaving(true);
        try {
            const items = clips.map(c => ({
                id: c.id,
                source_alias: c.source_alias,
                episode_id: c.episode_id || null,
                episode_name: c.episode_name || null,
                timeline_start: c.timeline_start,
                timeline_duration: c.timeline_duration,
                clip_type: c.clip_type || 'episode',
                character_name: c.character_name || null,
                matcher_mode: c.matcher_mode || (c.clip_type === 'character' ? 'chaotic' : 'sequential'),
                group_items: c.clip_type === 'group' ? c.group_items : undefined,
                group_selection_mode: c.clip_type === 'group' ? (c.group_selection_mode || 'score') : undefined,
            }));

            const res = await fetch(`http://localhost:8000/projects/${project.name}/segmented_timeline`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items })
            });
            if (!res.ok) alert("Save failed");
        } catch (e) { console.error(e); }
        setIsSaving(false);
    };

    const handleBuildSegmented = async () => {
        setIsBuilding(true);
        try {
            await fetch(`http://localhost:8000/projects/${project.name}/build_segmented`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model: selectedModel })
            });
        } catch {
            // Build kickoff errors are surfaced by the backend/UI polling flow.
        }
        setIsBuilding(false);
    };

    const handleFileUpload = async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        setIsUploading(true);
        const formData = new FormData();
        formData.append('file', file, file.name);
        try {
            const res = await fetch(`http://localhost:8000/projects/${project.name}/input`, {
                method: 'POST',
                body: formData
            });
            if (res.ok) fetchDetails();
            else alert("Upload failed");
        } catch (error) { alert("Error uploading file"); }
        setIsUploading(false);
        if (fileInputRef.current) fileInputRef.current.value = '';
    };

    const handleAnalyzeMood = async () => {
        setIsAnalyzingMood(true);
        try {
            const res = await fetch(`http://localhost:8000/music/analyze`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    transcript_text: transcriptText,
                    duration_seconds: audioDuration,
                    project_name: project.name
                })
            });
            if (res.ok) {
                const data = await res.json();
                setMusicTags(data.tags);
            } else {
                alert("Failed to analyze mood");
            }
        } catch (e) { console.error(e); }
        setIsAnalyzingMood(false);
    };

    const handleGenerateMusic = async () => {
        if (!musicTags) return;
        let cookies = sunoCookies;

        // 1. Get Suno cookies via Electron IPC if not cached
        if (!cookies) {
            cookies = await electronAPI.sunoAuth();
            if (cookies) setSunoCookies(cookies);
        }

        if (!cookies) {
            alert("Suno Authentication failed or was cancelled.");
            return;
        }

        // 2. Start generation
        try {
            const res = await fetch(`http://localhost:8000/music/generate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    tags: musicTags,
                    prompt: musicPrompt,
                    duration_seconds: audioDuration,
                    project_name: project.name,
                    cookies: cookies
                })
            });

            if (res.ok) {
                // start polling
                setMusicGenStatus({ percent: 1, status: "Starting..." });
            } else {
                alert("Generation failed to start.");
            }
        } catch (e) { console.error(e); }
    };

    const handleMusicUpload = async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        setIsUploadingMusic(true);
        const formData = new FormData();
        formData.append('file', file, file.name);
        try {
            const res = await fetch(`http://localhost:8000/music/upload?project_name=${encodeURIComponent(project.name)}`, {
                method: 'POST',
                body: formData
            });
            if (res.ok) {
                await fetchDetails();
                setIsMusicModalOpen(false);
            } else {
                const err = await res.json().catch(() => null);
                alert(err?.detail || "Music upload failed");
            }
        } catch (error) { alert("Error uploading music file"); }
        setIsUploadingMusic(false);
        if (musicFileInputRef.current) musicFileInputRef.current.value = '';
    };


    const addClip = useCallback((ep, sourceAlias, clipType = 'episode', groupSelectionMode = 'score') => {
        if (!audioDuration) return;

        setClips(prev => {
            const existing = [...prev];
            const lastEnd = existing.length > 0
                ? Math.max(...existing.map(c => c.timeline_start + c.timeline_duration))
                : 0;

            const remaining = audioDuration - lastEnd;
            const newDuration = Math.max(MIN_CLIP_DURATION, Math.min(remaining, 10));

            if (remaining < MIN_CLIP_DURATION) return prev;

            const newClip = {
                id: `clip-${Date.now()}`,
                source_alias: clipType === 'group' ? 'group' : sourceAlias,
                episode_id: clipType === 'episode' ? ep.id : (clipType === 'group' ? ep.id : null),
                episode_name: clipType === 'episode' ? ep.name : (clipType === 'group' ? ep.name : null),
                timeline_start: lastEnd,
                timeline_duration: newDuration,
                clip_type: clipType,
                character_name: clipType === 'character' ? ep.name : null,
                matcher_mode: clipType === 'group' ? 'chaotic' : (details?.matching_mode || (clipType === 'character' ? 'chaotic' : 'sequential')),
                group_items: clipType === 'group' ? ep.group_items : undefined,
                group_selection_mode: clipType === 'group' ? groupSelectionMode : undefined
            };

            return [...existing, newClip];
        });
    }, [audioDuration, details?.matching_mode]);

    const toggleMatcherMode = useCallback((clipId) => {
        setClips(prev => prev.map(c => {
            if (c.id !== clipId) return c;
            // Groups are always chaotic, cannot toggle
            if (c.clip_type === 'group') return c; 
            return { ...c, matcher_mode: c.matcher_mode === 'chaotic' ? 'sequential' : 'chaotic' };
        }));
    }, []);

    const toggleGroupSelectionMode = useCallback((clipId) => {
        setClips(prev => prev.map(c => {
            if (c.id !== clipId || c.clip_type !== 'group') return c;
            return { ...c, group_selection_mode: c.group_selection_mode === 'alternate' ? 'score' : 'alternate' };
        }));
    }, []);

    const removeClip = useCallback((clipId) => {
        setClips(prev => {
            const without = prev.filter(c => c.id !== clipId);
            // Re-compact: shift subsequent clips to fill the gap
            return recompactClips(without);
        });
    }, []);

    const recompactClips = (clipList) => {
        // Sort by timeline_start, then remove gaps between clips
        const sorted = [...clipList].sort((a, b) => a.timeline_start - b.timeline_start);
        let cursor = 0;
        return sorted.map(c => {
            const updated = { ...c, timeline_start: cursor };
            cursor += c.timeline_duration;
            return updated;
        });
    };


    // ─── Resize Logic ────────────────────────────────────────────────────────

    const handleResizeMouseDown = useCallback((e, clipId, edge) => {
        e.preventDefault();
        e.stopPropagation();
        const clip = clips.find(c => c.id === clipId);
        if (!clip) return;
        setResizing({
            clipId,
            edge,
            startX: e.clientX,
            origStart: clip.timeline_start,
            origDuration: clip.timeline_duration
        });
    }, [clips]);

    useEffect(() => {
        if (!resizing) return;

        const handleMouseMove = (e) => {
            const dx = e.clientX - resizing.startX;
            const dt = dx / PIXELS_PER_SECOND;

            setClips(prev => {
                const idx = prev.findIndex(c => c.id === resizing.clipId);
                if (idx === -1) return prev;

                const updated = [...prev];
                const clip = { ...updated[idx] };

                if (resizing.edge === 'right') {
                    // Resize from right edge
                    const minEnd = clip.timeline_start + MIN_CLIP_DURATION;
                    const maxEnd = audioDuration;
                    const rawEnd = resizing.origStart + resizing.origDuration + dt;
                    const snappedEnd = snapToTranscriptBoundary(rawEnd, minEnd, maxEnd);
                    clip.timeline_duration = snappedEnd - clip.timeline_start;

                    // Push subsequent clips
                    updated[idx] = clip;
                    for (let j = idx + 1; j < updated.length; j++) {
                        const prev_end = updated[j - 1].timeline_start + updated[j - 1].timeline_duration;
                        if (updated[j].timeline_start < prev_end) {
                            updated[j] = { ...updated[j], timeline_start: prev_end };
                        }
                    }
                } else if (resizing.edge === 'left') {
                    // Resize from left edge — adjust start and duration
                    const rawStart = resizing.origStart + dt;
                    const maxStart = resizing.origStart + resizing.origDuration - MIN_CLIP_DURATION;

                    // Don't overlap with previous clip
                    const prevClip = idx > 0 ? updated[idx - 1] : null;
                    const minStart = prevClip ? prevClip.timeline_start + prevClip.timeline_duration : 0;
                    const finalStart = snapToTranscriptBoundary(rawStart, minStart, maxStart);

                    clip.timeline_start = finalStart;
                    clip.timeline_duration = resizing.origDuration + (resizing.origStart - finalStart);
                    clip.timeline_duration = Math.max(MIN_CLIP_DURATION, clip.timeline_duration);
                    updated[idx] = clip;
                }

                return updated;
            });
        };

        const handleMouseUp = () => {
            setResizing(null);
        };

        window.addEventListener('mousemove', handleMouseMove);
        window.addEventListener('mouseup', handleMouseUp);
        return () => {
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseup', handleMouseUp);
        };
    }, [resizing, audioDuration, snapToTranscriptBoundary]);


    // ─── Drop on video track ─────────────────────────────────────────────────

    const handleTrackDragOver = (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'copy';
    };

    const handleTrackDrop = (e) => {
        e.preventDefault();
        if (!draggedEpisode) return;

        // Group drop: add as a single group clip
        if (draggedEpisode._isGroup && draggedEpisode.group_items) {
            setPendingGroupDrop(draggedEpisode);
            setDraggedEpisode(null);
            return;
        }

        addClip(draggedEpisode, draggedEpisode.sourceAlias, draggedEpisode.clipType);
        setDraggedEpisode(null);
    };

    const handleLibDragStart = (e, ep, sourceAlias, clipType = 'episode') => {
        setDraggedEpisode({ ...ep, sourceAlias, clipType });
        e.dataTransfer.effectAllowed = 'copy';
        const img = new Image();
        img.src = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
        e.dataTransfer.setDragImage(img, 0, 0);
    };


    // ─── Scrubber/Playhead Logic (Premiere Pro-style) ─────────────────────────

    const getTimeFromMouseEvent = useCallback((e) => {
        if (!rulerRef.current || !audioDuration) return 0;
        const rect = rulerRef.current.getBoundingClientRect();
        const offsetX = e.clientX - rect.left;
        return Math.max(0, Math.min(offsetX / PIXELS_PER_SECOND, audioDuration));
    }, [audioDuration]);

    const seekToTime = useCallback((time) => {
        if (!audioRef.current || !audioDuration) return;
        const clamped = Math.max(0, Math.min(time, audioDuration));
        audioRef.current.currentTime = clamped;
        setPlayheadTime(clamped);
    }, [audioDuration]);

    const handleScrubStart = useCallback((e) => {
        e.preventDefault();
        e.stopPropagation();
        const time = getTimeFromMouseEvent(e);
        setIsScrubbing(true);
        scrubStartRef.current = true;
        seekToTime(time);
        // Pause during scrubbing for responsive feel
        if (audioRef.current && !audioRef.current.paused) {
            audioRef.current.pause();
        }
    }, [getTimeFromMouseEvent, seekToTime]);

    useEffect(() => {
        if (!isScrubbing) return;

        const handleMouseMove = (e) => {
            const time = getTimeFromMouseEvent(e);
            seekToTime(time);
        };

        const handleMouseUp = () => {
            setIsScrubbing(false);
            scrubStartRef.current = null;
        };

        window.addEventListener('mousemove', handleMouseMove);
        window.addEventListener('mouseup', handleMouseUp);
        return () => {
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseup', handleMouseUp);
        };
    }, [isScrubbing, getTimeFromMouseEvent, seekToTime]);

    const renderRuler = () => {
        if (!audioDuration) return null;
        const ticks = [];
        const majorInterval = audioDuration > 120 ? 30 : audioDuration > 60 ? 10 : 5;
        for (let t = 0; t <= audioDuration; t += majorInterval) {
            ticks.push(
                <div
                    key={t}
                    className="absolute top-0 h-full flex flex-col justify-end pointer-events-none"
                    style={{ left: t * PIXELS_PER_SECOND }}
                >
                    <div className="border-l border-zinc-600 h-2"></div>
                    <span className="text-[9px] text-zinc-500 font-mono ml-0.5 select-none">
                        {formatTime(t)}
                    </span>
                </div>
            );
        }
        return ticks;
    };


    // ─── Render: Transcript Segments Under Audio ─────────────────────────────

    const renderTranscriptSegments = () => {
        if (!transcript || !transcript.batches) return null;
        const segs = [];
        transcript.batches.forEach((b) => {
            b.segments?.forEach((seg, si) => {
                const left = seg.start * PIXELS_PER_SECOND;
                const width = (seg.end - seg.start) * PIXELS_PER_SECOND;
                if (width < 3) return;
                segs.push(
                    <div
                        key={`seg-${seg.start}-${si}`}
                        className={`absolute top-0 h-full border-r px-0.5 overflow-hidden ${isMagnetEnabled ? 'border-yellow-400/25' : 'border-white/5'}`}
                        style={{ left, width }}
                    >
                        <span className="text-[8px] text-zinc-600 leading-tight block truncate mt-0.5">
                            {seg.text}
                        </span>
                    </div>
                );
            });
        });
        return segs;
    };


    // ─── Render ──────────────────────────────────────────────────────────────

    return (
        <div className="h-full flex flex-col bg-background text-primary">
            {pendingGroupDrop && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
                    <div className="w-full max-w-md rounded-xl border border-border bg-surface shadow-2xl">
                        <div className="p-5 border-b border-border">
                            <div className="flex items-center gap-2 text-emerald-400 mb-2">
                                <FolderPlus size={18} />
                                <span className="text-xs font-bold uppercase tracking-wider">Group source mode</span>
                            </div>
                            <h2 className="text-lg font-bold text-white truncate">{pendingGroupDrop.name}</h2>
                        </div>
                        <div className="p-4 grid grid-cols-2 gap-3">
                            <button
                                onClick={() => {
                                    addClip(pendingGroupDrop, 'group', 'group', 'alternate');
                                    setPendingGroupDrop(null);
                                }}
                                className="min-h-[112px] rounded-lg border border-emerald-500/30 bg-emerald-500/10 hover:bg-emerald-500/20 text-left p-4 transition-colors"
                            >
                                <ArrowRightLeft size={18} className="text-emerald-300 mb-3" />
                                <div className="text-sm font-bold text-white mb-1">Strict alternation</div>
                                <div className="text-xs leading-snug text-zinc-400">Rotate through films in group order.</div>
                            </button>
                            <button
                                onClick={() => {
                                    addClip(pendingGroupDrop, 'group', 'group', 'score');
                                    setPendingGroupDrop(null);
                                }}
                                className="min-h-[112px] rounded-lg border border-white/10 bg-white/5 hover:bg-white/10 text-left p-4 transition-colors"
                            >
                                <Shuffle size={18} className="text-zinc-300 mb-3" />
                                <div className="text-sm font-bold text-white mb-1">Highest score</div>
                                <div className="text-xs leading-snug text-zinc-400">Use the previous score-based matcher.</div>
                            </button>
                        </div>
                        <div className="px-4 pb-4 flex justify-end">
                            <button
                                onClick={() => setPendingGroupDrop(null)}
                                className="px-3 py-2 text-sm text-muted hover:text-white transition-colors"
                            >
                                Cancel
                            </button>
                        </div>
                    </div>
                </div>
            )}
            {/* Header */}
            <header className="flex-shrink-0 border-b border-border bg-surface px-6 py-4 flex items-center justify-between">
                <div className="flex items-center gap-4">
                    <button onClick={onBack} className="p-2 hover:bg-white/5 rounded-lg transition-colors text-muted hover:text-white">
                        <ArrowLeft size={20} />
                    </button>
                    <div>
                        <h1 className="text-xl font-bold flex items-center gap-2">
                            <span className="text-accent">◆</span> {project.name}
                            <span className="px-2 py-0.5 ml-2 text-[10px] uppercase font-bold bg-purple-500/20 text-purple-400 rounded border border-purple-500/30">
                                Segmented
                            </span>
                        </h1>
                        <p className="text-sm text-muted">Drop episodes onto the video track. Resize to control duration.</p>
                    </div>
                </div>

                <div className="flex items-center gap-3">
                    {clips.length > 0 && (
                        <>
                            <button
                                onClick={handleSaveTimeline}
                                disabled={isSaving}
                                className="px-4 py-2 bg-white/10 hover:bg-white/20 text-white rounded-lg text-sm font-medium transition-all disabled:opacity-50 flex items-center gap-2"
                            >
                                {isSaving ? <Loader2 className="animate-spin" size={16} /> : <Save size={16} />}
                                Save
                            </button>
                            <button
                                onClick={() => setIsMusicModalOpen(true)}
                                className="px-4 py-2 bg-pink-600/20 hover:bg-pink-600/40 text-pink-400 border border-pink-500/30 rounded-lg text-sm font-bold transition-all flex items-center gap-2"
                            >
                                <Music size={16} />
                                Generate Music
                            </button>
                            <button
                                onClick={handleBuildSegmented}
                                disabled={isBuilding}
                                className="px-4 py-2 bg-purple-600 hover:bg-purple-500 text-white rounded-r-lg text-sm font-bold transition-all disabled:opacity-50 flex items-center gap-2 shadow-lg shadow-purple-900/20"
                            >
                                {isBuilding ? <Loader2 className="animate-spin" size={16} /> : <FileVideo size={16} />}
                                Build
                            </button>
                            <select
                                value={selectedModel}
                                onChange={(e) => setSelectedModel(e.target.value)}
                                disabled={isBuilding}
                                className="px-2 py-2 bg-purple-900/60 border border-purple-500/30 text-purple-200 rounded-l-lg text-xs font-mono cursor-pointer hover:bg-purple-900/80 transition-all disabled:opacity-50 outline-none"
                                title="Gemini Model"
                            >
                                {availableModels.map(m => (
                                    <option key={m.key} value={m.key}>{m.label}</option>
                                ))}
                            </select>
                        </>
                    )}
                </div>
            </header>

            {/* Build Progress Bar */}
            {buildProgress && buildProgress.percent >= 0 && buildProgress.percent < 100 && (
                <div className="flex-shrink-0 bg-black/60 border-b border-border px-6 py-2">
                    <div className="flex items-center gap-3">
                        <Loader2 className="animate-spin text-purple-400" size={14} />
                        <span className="text-xs text-zinc-400">{buildProgress.status || 'Building...'}</span>
                        <div className="flex-1 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                            <div className="h-full bg-purple-500 rounded-full transition-all" style={{ width: `${buildProgress.percent}%` }}></div>
                        </div>
                        <span className="text-xs text-zinc-500 font-mono">{buildProgress.percent}%</span>
                    </div>
                </div>
            )}

            {/* Main Content */}
            <div className="flex-1 overflow-hidden flex">

                {/* Left Sidebar: Library → Films → Episodes */}
                <div className="w-72 border-r border-border bg-black/20 flex flex-col">
                    <div className="p-4 border-b border-border font-medium text-sm text-muted uppercase tracking-wider flex items-center gap-2">
                        <Film size={14} /> Library
                    </div>
                    <div className="flex-1 overflow-y-auto p-2 space-y-1">
                        {library.map(source => {
                            const alias = source.alias;
                            const isExpanded = expandedSources[alias];
                            const episodes = sourceEpisodes[alias] || [];

                            return (
                                <div key={alias} className="rounded-lg border border-border overflow-hidden">
                                    {/* Film header — click to expand */}
                                    <button
                                        onClick={() => toggleSource(alias)}
                                        className="w-full flex items-center gap-2 px-3 py-2.5 bg-surface hover:bg-white/5 transition-colors text-left"
                                    >
                                        {isExpanded
                                            ? <ChevronDown size={14} className="text-purple-400 flex-shrink-0" />
                                            : <ChevronRight size={14} className="text-muted flex-shrink-0" />
                                        }
                                        {source.thumbnail && (
                                            <img src={source.thumbnail} alt="" className="w-6 h-8 object-cover rounded-sm flex-shrink-0 opacity-80" />
                                        )}
                                        <span className="text-xs font-bold truncate">{alias}</span>
                                    </button>

                                    {/* Episodes list */}
                                    {isExpanded && (
                                        <div className="bg-black/30 border-t border-border">
                                            {episodes.length === 0 ? (
                                                <div className="px-3 py-3 flex items-center justify-center">
                                                    <Loader2 className="animate-spin text-muted" size={14} />
                                                    <span className="text-[10px] text-muted ml-2">Loading episodes...</span>
                                                </div>
                                            ) : (
                                                <div className="flex flex-col max-h-[300px]">
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

                                                    <div className="p-1.5 space-y-0.5 overflow-y-auto">
                                                        {sourceTab[alias] === 'characters' ? (
                                                            (sourceCharacters[alias] || []).length === 0 ? (
                                                                <div className="text-[10px] text-muted p-2 text-center">No characters found</div>
                                                            ) : (
                                                                (sourceCharacters[alias] || []).map(charObj => {
                                                                    const charName = charObj.name;
                                                                    const count = charObj.scene_count;
                                                                    return (
                                                                        <div
                                                                            key={`char-${charName}`}
                                                                            draggable
                                                                            onDragStart={(e) => handleLibDragStart(e, { id: charName, name: charName }, alias, 'character')}
                                                                            onDragEnd={() => setDraggedEpisode(null)}
                                                                            className="w-full text-left px-3 py-1.5 rounded-md text-xs transition-colors flex items-center justify-between hover:bg-white/5 border border-transparent hover:border-white/10 cursor-grab active:cursor-grabbing group"
                                                                        >
                                                                            <div className="flex items-center gap-2 truncate">
                                                                                <User size={11} className="text-muted flex-shrink-0 group-hover:text-orange-400 transition-colors" />
                                                                                <span className="truncate flex-1">{charName}</span>
                                                                            </div>
                                                                            {count !== undefined && (
                                                                                <span className="text-[10px] text-muted whitespace-nowrap ml-2">
                                                                                    {count} scenes
                                                                                </span>
                                                                            )}
                                                                        </div>
                                                                    );
                                                                })
                                                            )
                                                        ) : (
                                                            episodes.map(ep => {
                                                                const dur = Math.round((ep.end_time || 0) - (ep.start_time || 0));
                                                                return (
                                                                    <div
                                                                        key={ep.id}
                                                                        draggable
                                                                        onDragStart={(e) => handleLibDragStart(e, ep, alias, 'episode')}
                                                                        onDragEnd={() => setDraggedEpisode(null)}
                                                                        className="w-full text-left px-3 py-1.5 rounded-md text-xs transition-colors flex items-center justify-between hover:bg-white/5 border border-transparent hover:border-white/10 cursor-grab active:cursor-grabbing group"
                                                                    >
                                                                        <div className="flex items-center gap-2 truncate">
                                                                            <MousePointerSquareDashed size={11} className="text-muted flex-shrink-0 group-hover:text-purple-400 transition-colors" />
                                                                            <span className="truncate">{ep.name}</span>
                                                                        </div>
                                                                        <span className="text-[10px] text-muted whitespace-nowrap ml-2">
                                                                            {dur}s
                                                                        </span>
                                                                    </div>
                                                                );
                                                            })
                                                        )}
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>
                            );
                        })}

                        {/* Groups Section */}
                        {groups.length > 0 && (
                            <div className="mt-2 pt-2 border-t border-border">
                                <div className="px-2 py-1.5 text-[10px] uppercase tracking-wider text-emerald-400 font-bold flex items-center gap-1">
                                    <FolderPlus size={11} /> Groups
                                </div>
                                {groups.map(group => {
                                    const isExpanded = expandedGroups[group.id];
                                    return (
                                        <div key={group.id} className="rounded-lg border border-border overflow-hidden mb-1">
                                            <button
                                                onClick={() => setExpandedGroups(prev => ({ ...prev, [group.id]: !prev[group.id] }))}
                                                className="w-full flex items-center gap-2 px-3 py-2 bg-surface hover:bg-white/5 transition-colors text-left"
                                            >
                                                {isExpanded
                                                    ? <ChevronDown size={12} className="text-emerald-400 flex-shrink-0" />
                                                    : <ChevronRight size={12} className="text-muted flex-shrink-0" />
                                                }
                                                <FolderPlus size={12} className="text-emerald-400 flex-shrink-0" />
                                                <span className="text-xs font-bold truncate flex-1">{group.name}</span>
                                                <span className="text-[9px] text-zinc-600">{(group.items || []).length}</span>
                                            </button>

                                            {/* Drag the whole group */}
                                            {!isExpanded && (
                                                <div
                                                    draggable
                                                    onDragStart={(e) => {
                                                        setDraggedEpisode({
                                                            id: group.id,
                                                            name: group.name,
                                                            sourceAlias: 'group',
                                                            clipType: 'episode',
                                                            _isGroup: true,
                                                            group_items: group.items || []
                                                        });
                                                        e.dataTransfer.effectAllowed = 'copy';
                                                        const img = new Image();
                                                        img.src = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
                                                        e.dataTransfer.setDragImage(img, 0, 0);
                                                    }}
                                                    onDragEnd={() => setDraggedEpisode(null)}
                                                    className="mx-2 mb-1.5 px-3 py-1.5 bg-emerald-500/10 border border-emerald-500/20 rounded-md text-[10px] text-emerald-300 cursor-grab active:cursor-grabbing hover:bg-emerald-500/20 transition-colors text-center font-medium"
                                                >
                                                    ⊞ Drag entire group to timeline
                                                </div>
                                            )}

                                            {isExpanded && (
                                                <div className="bg-black/30 border-t border-border p-1.5 space-y-0.5">
                                                    {/* Drag all button */}
                                                    <div
                                                        draggable
                                                        onDragStart={(e) => {
                                                            setDraggedEpisode({
                                                                id: group.id,
                                                                name: group.name,
                                                                sourceAlias: 'group',
                                                                clipType: 'episode',
                                                                _isGroup: true,
                                                                group_items: group.items || []
                                                            });
                                                            e.dataTransfer.effectAllowed = 'copy';
                                                            const img = new Image();
                                                            img.src = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
                                                            e.dataTransfer.setDragImage(img, 0, 0);
                                                        }}
                                                        onDragEnd={() => setDraggedEpisode(null)}
                                                        className="px-3 py-1.5 bg-emerald-500/10 border border-emerald-500/20 rounded-md text-[10px] text-emerald-300 cursor-grab active:cursor-grabbing hover:bg-emerald-500/20 transition-colors text-center font-medium mb-1"
                                                    >
                                                        ⊞ Drop all {(group.items || []).length} items
                                                    </div>
                                                    {(group.items || []).map((item, i) => (
                                                        <div
                                                            key={`grp-${group.id}-${i}`}
                                                            draggable
                                                            onDragStart={(e) => handleLibDragStart(e, { id: item.episode_id || item.name, name: item.name }, item.source_alias, item.type)}
                                                            onDragEnd={() => setDraggedEpisode(null)}
                                                            className="w-full text-left px-3 py-1.5 rounded-md text-xs transition-colors flex items-center justify-between hover:bg-white/5 border border-transparent hover:border-white/10 cursor-grab active:cursor-grabbing group"
                                                        >
                                                            <div className="flex items-center gap-2 truncate">
                                                                {item.type === 'character'
                                                                    ? <Users size={11} className="text-orange-400 flex-shrink-0" />
                                                                    : <List size={11} className="text-purple-400 flex-shrink-0" />
                                                                }
                                                                <span className="truncate">{item.name}</span>
                                                            </div>
                                                            <span className="text-[10px] text-zinc-600 ml-2 flex-shrink-0">{item.source_alias}</span>
                                                        </div>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </div>
                </div>

                {/* Right: Timeline Area */}
                <div className="flex-1 flex flex-col bg-[#0a0a0a] relative overflow-hidden">

                    {!details?.audio_ready ? (
                        /* ── No Audio Yet ── */
                        <div className="h-full flex flex-col items-center justify-center p-8 bg-black/40">
                            <div className="bg-surface border border-white/5 rounded-2xl p-8 max-w-md w-full text-center shadow-2xl">
                                <Mic className="text-zinc-700 w-16 h-16 mx-auto mb-6" />
                                <h3 className="text-xl font-bold mb-2">Add Audio Track</h3>
                                <p className="text-muted text-sm mb-8">
                                    Upload or record audio. It will be transcribed, then you can map episodes to the timeline.
                                </p>
                                <div className="space-y-3">
                                    <input type="file" accept="audio/*" className="hidden" ref={fileInputRef} onChange={handleFileUpload} />
                                    <button
                                        onClick={() => fileInputRef.current?.click()}
                                        disabled={isUploading}
                                        className="w-full px-4 py-3 bg-accent hover:bg-accent/80 text-white rounded-xl text-sm font-bold transition-all shadow-[0_0_15px_rgba(59,130,246,0.3)] disabled:opacity-50 flex items-center justify-center gap-2"
                                    >
                                        {isUploading ? <Loader2 className="animate-spin" size={18} /> : <Upload size={18} />}
                                        {isUploading ? "Uploading..." : "Upload Audio File"}
                                    </button>
                                    <div className="text-xs text-zinc-600 font-bold uppercase my-2">— or —</div>
                                    <button
                                        onClick={() => setIsRecorderOpen(true)}
                                        className="w-full px-4 py-3 bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/30 rounded-xl text-sm font-bold transition-all flex items-center justify-center gap-2"
                                    >
                                        <Mic size={18} /> Record New Audio
                                    </button>
                                </div>
                            </div>
                        </div>

                    ) : !transcript ? (
                        /* ── Audio Ready, No Transcript ── */
                        <div className="h-full flex flex-col items-center justify-center p-8">
                            <Scissors className="text-muted opacity-20 mb-4" size={64} />
                            <h3 className="text-xl font-bold mb-4">Audio Ready</h3>
                            <p className="text-sm text-muted mb-6 max-w-sm text-center">Transcribe to generate the timeline segments for your video track.</p>
                            <button
                                onClick={handleTranscribe}
                                disabled={isTranscribing}
                                className="px-6 py-3 bg-accent hover:bg-accent/80 text-white font-bold rounded-xl transition-all shadow-[0_0_20px_rgba(168,85,247,0.4)] flex items-center gap-2 disabled:opacity-50"
                            >
                                {isTranscribing ? <RefreshCw className="animate-spin" size={20} /> : <RefreshCw size={20} />}
                                {isTranscribing ? 'Transcribing...' : 'Transcribe Audio'}
                            </button>
                        </div>

                    ) : (
                        /* ── Timeline Editor ── */
                        <div className="flex-1 flex flex-col">

                            {/* Toolbar */}
                            <div className="flex-shrink-0 h-10 bg-[#1a1a1a] border-b border-[#333] flex items-center px-4 gap-4">
                                <span className="text-[11px] font-mono text-zinc-500 uppercase tracking-wider">Timeline</span>
                                <button
                                    onClick={openAutoPlan}
                                    disabled={isAutoPlanning}
                                    className="h-7 px-2.5 rounded-md border border-purple-500/35 bg-purple-500/15 text-purple-200 hover:bg-purple-500/25 text-[11px] font-bold transition-colors flex items-center gap-1.5 disabled:opacity-50"
                                    title="Generate segmented timeline from exact script text and selected sources"
                                >
                                    {isAutoPlanning ? <Loader2 className="animate-spin" size={13} /> : <Wand2 size={13} />}
                                    Auto Timeline
                                </button>
                                <button
                                    onClick={() => setIsMagnetEnabled(prev => !prev)}
                                    className={`h-7 px-2 rounded-md border text-[11px] font-bold transition-colors flex items-center gap-1.5 ${isMagnetEnabled
                                        ? 'bg-yellow-500/15 border-yellow-500/40 text-yellow-300 hover:bg-yellow-500/25'
                                        : 'bg-white/5 border-white/10 text-zinc-500 hover:text-white hover:bg-white/10'
                                        }`}
                                    title={isMagnetEnabled ? 'Magnet on: resize snaps to phrase boundaries' : 'Magnet off: free resize'}
                                >
                                    <Magnet size={13} />
                                    {isMagnetEnabled ? 'Magnet' : 'Free'}
                                </button>
                                <div className="flex-1" />
                                <span className="text-[11px] font-mono text-zinc-600">
                                    {clips.length} clip{clips.length !== 1 ? 's' : ''} • {formatTime(audioDuration)}
                                </span>
                            </div>

                            {/* Scrollable Timeline */}
                            <div className="flex-1 overflow-x-auto overflow-y-hidden" ref={timelineScrollRef}>
                                <div style={{ width: timelineWidth + 80, minHeight: '100%' }} className="relative pl-16">

                                    {/* Timecode Ruler — click/drag to scrub */}
                                    <div
                                        ref={rulerRef}
                                        className="h-7 relative bg-[#1a1a1a] border-b border-[#333] cursor-pointer select-none"
                                        onMouseDown={handleScrubStart}
                                    >
                                        {renderRuler()}
                                        {/* Playhead handle (draggable triangle) */}
                                        {audioDuration > 0 && (
                                            <div
                                                className="absolute top-0 z-40 pointer-events-none"
                                                style={{ left: playheadTime * PIXELS_PER_SECOND - 6 }}
                                            >
                                                <div
                                                    style={{
                                                        width: 0, height: 0,
                                                        borderLeft: '6px solid transparent',
                                                        borderRight: '6px solid transparent',
                                                        borderTop: '8px solid #facc15',
                                                        filter: 'drop-shadow(0 0 4px rgba(250, 204, 21, 0.6))',
                                                    }}
                                                />
                                            </div>
                                        )}
                                    </div>

                                    {/* Video Track (V1) */}
                                    <div
                                        className={`h-20 relative bg-[#1a1a1a] border-b border-[#333] transition-all ${draggedEpisode ? 'ring-1 ring-purple-500/30 bg-purple-500/5' : ''}`}
                                        onDragOver={handleTrackDragOver}
                                        onDrop={handleTrackDrop}
                                    >
                                        {/* Track label */}
                                        <div className="absolute -left-16 top-0 h-full w-16 flex items-center justify-end pr-3 text-[10px] font-mono text-zinc-600 select-none">V1</div>

                                        {/* Drop hint when dragging */}
                                        {draggedEpisode && clips.length === 0 && (
                                            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                                                <span className="text-xs text-purple-400/60 font-medium animate-pulse">Drop episode here</span>
                                            </div>
                                        )}

                                        {/* Clips */}
                                        {clips.map((clip) => {
                                            const left = clip.timeline_start * PIXELS_PER_SECOND;
                                            const width = clip.timeline_duration * PIXELS_PER_SECOND;

                                            const isChar = clip.clip_type === 'character';
                                            const isGroup = clip.clip_type === 'group';
                                            
                                            let color = episodeColorHash(clip.episode_name);
                                            if (isChar) color = 'rgba(234, 88, 12, 0.85)'; // orange
                                            if (isGroup) color = 'rgba(16, 185, 129, 0.85)'; // emerald
                                            
                                            const displayName = isChar || isGroup ? (clip.character_name || clip.episode_name) : clip.episode_name;
                                            const label = isGroup ? 'GROUP' : (isChar ? 'CHAR' : 'EP');
                                            const groupMode = clip.group_selection_mode || 'score';

                                            return (
                                                <div
                                                    key={clip.id}
                                                    className={`absolute top-[3px] h-[74px] rounded-[3px] overflow-hidden group/clip border border-white/10 transition-all ${isGroup ? 'hover:border-emerald-500/50' : (isChar ? 'hover:border-orange-500/50' : 'hover:border-white/25')}`}
                                                    style={{
                                                        left,
                                                        width: Math.max(width, 20),
                                                        backgroundColor: color,
                                                    }}
                                                >
                                                    {/* Left resize handle */}
                                                    <div
                                                        className="absolute left-0 top-0 w-2 h-full cursor-col-resize hover:bg-white/20 z-10"
                                                        onMouseDown={(e) => handleResizeMouseDown(e, clip.id, 'left')}
                                                    />

                                                    {/* Content */}
                                                    <div className="px-2 py-1 h-full flex flex-col justify-between pointer-events-none select-none relative z-0">
                                                        <div className="flex items-center gap-1">
                                                            <div className={`px-1.5 h-4 ${isGroup ? 'bg-emerald-500/30' : (isChar ? 'bg-orange-500/30' : 'bg-black/40')} rounded-sm flex items-center justify-center flex-shrink-0`}>
                                                                <span className="text-[7.5px] italic text-white/90 font-bold">{label}</span>
                                                            </div>
                                                            <span className="text-[10px] font-bold text-white truncate drop-shadow-md">{displayName}</span>
                                                        </div>
                                                        <div className="flex items-center justify-between mt-auto">
                                                            <span className="text-[8px] text-white/70 truncate drop-shadow-md pr-1">
                                                                {isGroup ? `${clip.group_items?.length || 0} items · ${groupMode === 'alternate' ? 'alternate' : 'score'}` : clip.source_alias}
                                                            </span>
                                                            <span className="text-[8px] text-white/80 font-mono drop-shadow-md bg-black/30 px-1 rounded flex-shrink-0">{clip.timeline_duration.toFixed(1)}s</span>
                                                        </div>
                                                    </div>

                                                    {/* Right resize handle */}
                                                    <div
                                                        className="absolute right-0 top-0 w-2 h-full cursor-col-resize hover:bg-white/20 z-10"
                                                        onMouseDown={(e) => handleResizeMouseDown(e, clip.id, 'right')}
                                                    />

                                                    {/* Actions overlay */}
                                                    <div className="absolute inset-0 bg-black/40 opacity-0 group-hover/clip:opacity-100 transition-opacity flex items-center justify-center gap-2 pointer-events-none">
                                                        {/* Matcher Mode Toggle */}
                                                        {!isGroup && (
                                                            <button
                                                                onClick={(e) => { e.stopPropagation(); toggleMatcherMode(clip.id); }}
                                                                className={`p-1.5 rounded-md pointer-events-auto transition-all ${clip.matcher_mode === 'chaotic' ? 'bg-orange-500 hover:bg-orange-400 text-white shadow-[0_0_10px_rgba(249,115,22,0.5)]' : 'bg-blue-500 hover:bg-blue-400 text-white shadow-[0_0_10px_rgba(59,130,246,0.5)]'}`}
                                                                title={`Matcher: ${clip.matcher_mode === 'chaotic' ? 'Chaotic (Random frames)' : 'Sequential (Chronological gap fill)'}`}
                                                            >
                                                                {clip.matcher_mode === 'chaotic' ? <Shuffle size={12} /> : <ArrowRightLeft size={12} />}
                                                            </button>
                                                        )}
                                                        {isGroup && (
                                                            <button
                                                                onClick={(e) => { e.stopPropagation(); toggleGroupSelectionMode(clip.id); }}
                                                                className={`p-1.5 rounded-md pointer-events-auto transition-all ${groupMode === 'alternate' ? 'bg-emerald-500 hover:bg-emerald-400 text-white shadow-[0_0_10px_rgba(16,185,129,0.5)]' : 'bg-zinc-700 hover:bg-zinc-600 text-white shadow-lg'}`}
                                                                title={`Group source mode: ${groupMode === 'alternate' ? 'Strict alternation' : 'Highest score'}`}
                                                            >
                                                                {groupMode === 'alternate' ? <ArrowRightLeft size={12} /> : <Shuffle size={12} />}
                                                            </button>
                                                        )}

                                                        {/* Remove button */}
                                                        <button
                                                            onClick={(e) => { e.stopPropagation(); removeClip(clip.id); }}
                                                            className="p-1.5 bg-red-500 hover:bg-red-400 text-white rounded-md z-20 shadow-lg pointer-events-auto"
                                                            title="Remove Clip"
                                                        >
                                                            <X size={12} />
                                                        </button>
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>

                                    {/* Audio Track (A1) */}
                                    <div className="h-24 relative bg-[#1c2a1a] border-b border-[#333] overflow-hidden">
                                        <div className="absolute -left-16 top-0 h-full w-16 flex items-center justify-end pr-3 text-[10px] font-mono text-zinc-600 select-none bg-black/50 z-10">A1</div>
                                        <div className="w-full h-full" ref={waveformRef} style={{ width: timelineWidth }}></div>

                                        {/* Non-blocking waveform loading indicator */}
                                        {!isWaveformLoaded && (
                                            <div className="absolute right-4 bottom-2 z-20 pointer-events-none transition-opacity duration-300">
                                                <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-black/60 text-[9px] font-bold text-green-400 border border-green-500/20 shadow-lg">
                                                    <Loader2 className="animate-spin" size={10} />
                                                    Generating Waveform...
                                                </div>
                                            </div>
                                        )}
                                    </div>

                                    {/* Music Track (M1) */}
                                    <div className="h-10 relative bg-[#1a202a] border-b border-[#333] overflow-hidden group">
                                        <div className="absolute -left-16 top-0 h-full w-16 flex items-center justify-end pr-2 text-[10px] font-mono text-zinc-600 select-none z-10 bg-[#1a202a] gap-1">
                                            {details?.music_track && (
                                                <button
                                                    onClick={() => setIsMusicMuted(m => !m)}
                                                    className="p-0.5 hover:text-pink-400 transition-colors"
                                                    title={isMusicMuted ? 'Unmute music' : 'Mute music'}
                                                >
                                                    {isMusicMuted ? <VolumeX size={10} /> : <Volume2 size={10} />}
                                                </button>
                                            )}
                                            M1
                                        </div>
                                        {details?.music_track && (
                                            <div
                                                className="absolute top-1 bottom-1 rounded-md bg-gradient-to-r from-pink-600/70 to-purple-600/50 border border-pink-400/50 flex items-center px-3 gap-2"
                                                style={{ left: 0, width: audioDuration * PIXELS_PER_SECOND }}
                                            >
                                                <Music size={12} className="text-pink-200 flex-shrink-0" />
                                                <span className="text-[10px] text-white font-mono truncate">{details.music_track}</span>
                                                <div className="flex items-center gap-1 ml-auto flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                                                    <Volume2 size={10} className="text-white/60" />
                                                    <input
                                                        type="range"
                                                        min="0"
                                                        max="1"
                                                        step="0.05"
                                                        value={isMusicMuted ? 0 : musicVolume}
                                                        onChange={(e) => {
                                                            const v = parseFloat(e.target.value);
                                                            setMusicVolume(v);
                                                            setIsMusicMuted(v === 0);
                                                            if (musicAudioRef.current) musicAudioRef.current.volume = v;
                                                        }}
                                                        className="w-16 h-1 accent-pink-500 cursor-pointer"
                                                        title={`Volume: ${Math.round((isMusicMuted ? 0 : musicVolume) * 100)}%`}
                                                    />
                                                    <span className="text-[8px] text-white/50 w-6 text-right font-mono">{Math.round((isMusicMuted ? 0 : musicVolume) * 100)}%</span>
                                                </div>
                                                <button
                                                    onClick={() => {
                                                        if (confirm('Remove music track?')) {
                                                            // Stop playback
                                                            if (musicAudioRef.current) { musicAudioRef.current.pause(); musicAudioRef.current.src = ''; }
                                                            // We just refresh, the user can upload a new one
                                                            setIsMusicModalOpen(true);
                                                        }
                                                    }}
                                                    className="p-0.5 text-white/30 hover:text-red-400 transition-colors flex-shrink-0 opacity-0 group-hover:opacity-100"
                                                    title="Change music"
                                                >
                                                    <X size={10} />
                                                </button>
                                            </div>
                                        )}
                                        {musicGenStatus && (
                                            <div className="absolute top-0 bottom-0 left-0 right-0 bg-blue-500/10 flex items-center px-4">
                                                <Loader2 size={14} className="animate-spin text-blue-400 mr-2" />
                                                <span className="text-[10px] text-blue-400 font-mono">Generating: {musicGenStatus.status} ({musicGenStatus.percent}%)</span>
                                            </div>
                                        )}
                                    </div>

                                    {/* Transcript Segments Under Audio */}
                                    <div className="h-8 relative bg-[#111] border-b border-[#222]">
                                        <div className="absolute -left-16 top-0 h-full w-16 flex items-center justify-end pr-3 text-[8px] font-mono text-zinc-700 select-none">TXT</div>
                                        {renderTranscriptSegments()}
                                    </div>

                                    {/* Playhead line (vertical) */}
                                    {audioDuration > 0 && (
                                        <div
                                            className="absolute top-0 w-[2px] bg-yellow-400 pointer-events-none z-30"
                                            style={{
                                                left: playheadTime * PIXELS_PER_SECOND + 64, // +64 for pl-16
                                                height: '100%',
                                                boxShadow: '0 0 6px rgba(250, 204, 21, 0.4)',
                                            }}
                                        />
                                    )}
                                </div>
                            </div>

                            {/* Transport Controls */}
                            <div className="flex-shrink-0 h-14 border-t border-[#333] bg-[#141414] flex items-center justify-center gap-6">
                                <span className="text-sm font-mono text-zinc-400 w-14 text-right tabular-nums">{formatTime(playheadTime)}</span>

                                {/* Rewind to start */}
                                <button
                                    onClick={() => seekToTime(0)}
                                    className="w-8 h-8 flex items-center justify-center rounded-full bg-zinc-800/70 hover:bg-zinc-700 text-zinc-400 hover:text-white transition-all"
                                    title="Go to start"
                                >
                                    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M6 6h2v12H6zm3.5 6 8.5 6V6z" /></svg>
                                </button>

                                {/* Play/Pause */}
                                <button
                                    onClick={() => {
                                        if (audioRef.current) {
                                            if (audioRef.current.paused) audioRef.current.play().catch(e => console.error("PLAY_ERR", e));
                                            else audioRef.current.pause();
                                        }
                                    }}
                                    className={`w-11 h-11 flex items-center justify-center rounded-full transition-all border shadow-lg ${isPlaying
                                        ? 'bg-yellow-500/20 text-yellow-400 hover:bg-yellow-500/30 border-yellow-500/30 cursor-pointer shadow-[0_0_15px_rgba(250,204,21,0.2)]'
                                        : 'bg-zinc-800 text-white hover:bg-zinc-700 border-white/10 cursor-pointer'
                                        }`}
                                >
                                    {isPlaying ? <Pause size={18} fill="currentColor" /> : <Play size={18} fill="currentColor" className="ml-0.5" />}
                                </button>

                                <span className="text-sm font-mono text-zinc-600 w-14 tabular-nums">{formatTime(audioDuration)}</span>

                                {/* Speed toggle */}
                                <button
                                    onClick={() => {
                                        const idx = SPEED_OPTIONS.indexOf(playbackRate);
                                        const next = SPEED_OPTIONS[(idx + 1) % SPEED_OPTIONS.length];
                                        setPlaybackRate(next);
                                        if (audioRef.current) audioRef.current.playbackRate = next;
                                    }}
                                    className={`ml-2 px-2.5 py-1 rounded-md text-xs font-bold transition-all border ${playbackRate === 1
                                        ? 'bg-zinc-800/70 text-zinc-400 border-zinc-700 hover:bg-zinc-700'
                                        : 'bg-purple-500/20 text-purple-400 border-purple-500/30 hover:bg-purple-500/30 shadow-[0_0_8px_rgba(168,85,247,0.15)]'
                                        }`}
                                    title={`Playback speed: ${playbackRate}x`}
                                >
                                    {playbackRate}x
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* Recorder Modal */}
            {isRecorderOpen && (
                <AudioRecorder
                    project={project}
                    customSaveUrl={`http://localhost:8000/projects/${project.name}/input`}
                    onClose={() => setIsRecorderOpen(false)}
                    onSave={() => { setIsRecorderOpen(false); fetchDetails(); }}
                />
            )}

            {/* Auto Timeline Modal */}
            {isAutoPlanOpen && (
                <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4">
                    <div className="bg-surface border border-white/10 rounded-2xl w-full max-w-5xl h-[86vh] shadow-2xl overflow-hidden flex flex-col">
                        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
                            <div>
                                <h2 className="text-lg font-bold flex items-center gap-2">
                                    <Wand2 className="text-purple-300" size={20} /> Auto Timeline
                                </h2>
                                <p className="text-xs text-muted mt-1">Exact script controls meaning; transcript timing controls clip boundaries.</p>
                            </div>
                            <button
                                onClick={() => setIsAutoPlanOpen(false)}
                                disabled={isAutoPlanning}
                                className="text-muted hover:text-white transition-colors disabled:opacity-50"
                            >
                                <X size={20} />
                            </button>
                        </div>

                        <div className="flex-1 min-h-0 overflow-hidden grid grid-cols-[minmax(0,1fr)_320px]">
                            <div className="p-5 border-r border-border min-h-0 flex flex-col">
                                <label className="block text-xs font-bold text-zinc-400 uppercase mb-2">Exact script text</label>
                                <textarea
                                    value={autoPlanText}
                                    onChange={(e) => setAutoPlanText(e.target.value)}
                                    placeholder="Paste the final script used in this audio. The planner will use it instead of Whisper's imperfect wording."
                                    className="flex-1 min-h-0 w-full bg-black/40 border border-white/10 rounded-xl p-4 text-sm leading-relaxed focus:outline-none focus:border-purple-500/50 resize-none"
                                />
                                <div className="mt-3 flex items-center justify-between gap-3">
                                    <button
                                        onClick={() => setAutoPlanText(transcriptText)}
                                        className="px-3 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-xs font-medium text-zinc-300 transition-colors"
                                    >
                                        Use Whisper Text
                                    </button>
                                    <span className="text-[11px] text-zinc-600 font-mono">{autoPlanText.trim().split(/\s+/).filter(Boolean).length} words</span>
                                </div>
                            </div>

                            <div className="p-5 min-h-0 flex flex-col gap-5 overflow-y-auto custom-scrollbar">
                                <div className="min-h-0 flex flex-col">
                                    <div className="flex items-center justify-between mb-2">
                                        <label className="block text-xs font-bold text-zinc-400 uppercase">Movies and series</label>
                                        <button
                                            onClick={() => setAutoPlanSources(new Set(library.map(source => source.alias)))}
                                            className="text-[10px] text-purple-300 hover:text-purple-200"
                                        >
                                            Select all
                                        </button>
                                    </div>
                                    <div className="min-h-0 overflow-y-auto rounded-xl border border-white/10 bg-black/25 p-2 space-y-1">
                                        {library.length === 0 ? (
                                            <div className="text-xs text-muted p-3 text-center">No ready sources found.</div>
                                        ) : library.map(source => {
                                            const isSelected = autoPlanSources.has(source.alias);
                                            return (
                                                <button
                                                    key={`auto-source-${source.alias}`}
                                                    type="button"
                                                    onClick={() => toggleAutoPlanSource(source.alias)}
                                                    aria-pressed={isSelected}
                                                    className={`w-full flex items-center gap-2 px-2 py-2 rounded-lg border text-left cursor-pointer transition-colors ${
                                                        isSelected
                                                            ? 'bg-purple-500/15 border-purple-400/40 text-white'
                                                            : 'border-transparent hover:border-white/10 hover:bg-white/5 text-zinc-300'
                                                    }`}
                                                >
                                                    {source.thumbnail ? (
                                                        <img src={source.thumbnail} alt="" className="w-6 h-8 object-cover rounded-sm opacity-80" />
                                                    ) : (
                                                        <Film size={16} className="text-zinc-600" />
                                                    )}
                                                    <span className="text-xs font-medium truncate">{source.alias}</span>
                                                </button>
                                            );
                                        })}
                                    </div>
                                </div>

                                <div className="min-h-0 flex flex-col">
                                    <label className="block text-xs font-bold text-zinc-400 uppercase mb-2">Groups</label>
                                    <div className="min-h-[120px] max-h-[220px] overflow-y-auto rounded-xl border border-white/10 bg-black/25 p-2 space-y-1">
                                        {groups.length === 0 ? (
                                            <div className="text-xs text-muted p-3 text-center">No groups created yet.</div>
                                        ) : groups.map(group => {
                                            const isSelected = autoPlanGroups.has(group.id);
                                            return (
                                                <button
                                                    key={`auto-group-${group.id}`}
                                                    type="button"
                                                    onClick={() => toggleAutoPlanGroup(group.id)}
                                                    aria-pressed={isSelected}
                                                    className={`w-full flex items-center gap-2 px-2 py-2 rounded-lg border text-left cursor-pointer transition-colors ${
                                                        isSelected
                                                            ? 'bg-emerald-500/15 border-emerald-400/40 text-white'
                                                            : 'border-transparent hover:border-white/10 hover:bg-white/5 text-zinc-300'
                                                    }`}
                                                >
                                                    <FolderPlus size={15} className="text-emerald-400 flex-shrink-0" />
                                                    <span className="text-xs font-medium truncate flex-1">{group.name}</span>
                                                    <span className="text-[10px] text-zinc-600">{(group.items || []).length}</span>
                                                </button>
                                            );
                                        })}
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div className="px-6 py-4 border-t border-border bg-black/20 flex items-center justify-between gap-3">
                            <p className="text-xs text-zinc-500 max-w-xl">
                                This replaces the current video track with AI-planned episode, character, source, and group clips.
                            </p>
                            <div className="flex items-center gap-3">
                                <button
                                    onClick={() => setIsAutoPlanOpen(false)}
                                    disabled={isAutoPlanning}
                                    className="px-4 py-2 hover:bg-white/5 rounded-lg text-sm font-medium transition-colors text-muted disabled:opacity-50"
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={handleAutoPlanTimeline}
                                    disabled={isAutoPlanning || !autoPlanText.trim() || (autoPlanSources.size === 0 && autoPlanGroups.size === 0)}
                                    className="px-5 py-2 bg-purple-600 hover:bg-purple-500 text-white rounded-lg text-sm font-bold transition-all shadow-[0_0_15px_rgba(147,51,234,0.3)] flex items-center gap-2 disabled:opacity-50"
                                >
                                    {isAutoPlanning ? <Loader2 size={16} className="animate-spin" /> : <Wand2 size={16} />}
                                    {isAutoPlanning ? 'Planning...' : 'Create Timeline'}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Music Generation Modal */}
            {isMusicModalOpen && (
                <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4">
                    <div className="bg-surface border border-white/10 rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden flex flex-col">
                        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
                            <h2 className="text-lg font-bold flex items-center gap-2">
                                <Music className="text-pink-400" size={20} /> AI Music Supervisor
                            </h2>
                            <button onClick={() => setIsMusicModalOpen(false)} className="text-muted hover:text-white transition-colors">
                                <X size={20} />
                            </button>
                        </div>

                        <div className="p-6 space-y-6">
                            {/* Upload Section */}
                            <div className="p-4 border border-dashed border-pink-500/30 rounded-xl bg-pink-500/5 hover:bg-pink-500/10 transition-colors">
                                <input type="file" accept="audio/*" className="hidden" ref={musicFileInputRef} onChange={handleMusicUpload} />
                                <button
                                    onClick={() => musicFileInputRef.current?.click()}
                                    disabled={isUploadingMusic}
                                    className="w-full flex flex-col items-center gap-2 py-3"
                                >
                                    {isUploadingMusic
                                        ? <Loader2 className="animate-spin text-pink-400" size={24} />
                                        : <Upload className="text-pink-400" size={24} />
                                    }
                                    <span className="text-sm font-bold text-pink-300">
                                        {isUploadingMusic ? 'Uploading...' : 'Upload Music File'}
                                    </span>
                                    <span className="text-[10px] text-zinc-500">MP3, WAV, M4A, FLAC, OGG</span>
                                </button>
                            </div>

                            <div className="flex items-center gap-3">
                                <div className="flex-1 h-px bg-white/10"></div>
                                <span className="text-[10px] text-zinc-600 uppercase font-bold">or generate with Suno AI</span>
                                <div className="flex-1 h-px bg-white/10"></div>
                            </div>

                            {/* Suno Generation Section */}
                            <div>
                                <p className="text-sm text-muted mb-4">
                                    Analyze the episode's transcript to automatically determine the perfect musical mood and generate a background track using Suno AI.
                                </p>

                                <div className="space-y-4">
                                    <button
                                        onClick={handleAnalyzeMood}
                                        disabled={isAnalyzingMood || !transcript}
                                        className="w-full py-2.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
                                    >
                                        {isAnalyzingMood ? <Loader2 size={16} className="animate-spin text-purple-400" /> : <RefreshCw size={16} className="text-purple-400" />}
                                        Analyze Transcript Mood
                                    </button>

                                    <div>
                                        <label className="block text-xs font-bold text-zinc-400 uppercase mb-2">Suno Tags (Max 120 chars)</label>
                                        <textarea
                                            value={musicTags}
                                            onChange={(e) => setMusicTags(e.target.value)}
                                            placeholder="e.g. dark cinematic ambient, tension strings, slow tempo, instrumental"
                                            className="w-full h-20 bg-black/40 border border-white/10 rounded-lg p-3 text-sm focus:outline-none focus:border-purple-500/50 resize-none"
                                        />
                                    </div>

                                    <div>
                                        <label className="block text-xs font-bold text-zinc-400 uppercase mb-2">Optional Prompt / Lyrics</label>
                                        <input
                                            value={musicPrompt}
                                            onChange={(e) => setMusicPrompt(e.target.value)}
                                            placeholder="Leave empty for purely instrumental based on tags..."
                                            className="w-full bg-black/40 border border-white/10 rounded-lg p-3 text-sm focus:outline-none focus:border-purple-500/50"
                                        />
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div className="px-6 py-4 border-t border-border bg-black/20 flex justify-end gap-3">
                            <button
                                onClick={() => setIsMusicModalOpen(false)}
                                className="px-4 py-2 hover:bg-white/5 rounded-lg text-sm font-medium transition-colors text-muted"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={handleGenerateMusic}
                                disabled={!musicTags || (musicGenStatus && musicGenStatus.percent > 0)}
                                className="px-5 py-2 bg-pink-600 hover:bg-pink-500 text-white rounded-lg text-sm font-bold transition-all shadow-[0_0_15px_rgba(219,39,119,0.3)] flex items-center gap-2 disabled:opacity-50"
                            >
                                {musicGenStatus ? <Loader2 size={16} className="animate-spin" /> : <Music size={16} />}
                                {musicGenStatus ? 'Generating...' : 'Generate via Suno'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}

export default SegmentedProjectDetail;

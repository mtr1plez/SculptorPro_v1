import { useState, useRef, useEffect } from 'react';
import { Mic, Square, Scissors, Save, X, Play, Pause, Trash2, Loader2 } from 'lucide-react';
import WaveSurfer from 'wavesurfer.js';
import RegionsPlugin from 'wavesurfer.js/dist/plugins/regions.esm.js';

export function AudioRecorder({ project, onClose, onSave, variant = 'modal', customSave = false, customSaveUrl, lang: propLang, onLangChange, ...props }) {
    const [isRecording, setIsRecording] = useState(false);
    const [audioBlob, setAudioBlob] = useState(null);
    const [isPlaying, setIsPlaying] = useState(false);
    const [isProcessing, setIsProcessing] = useState(false);

    const containerRef = useRef(null);
    const wavesurferRef = useRef(null);
    const mediaRecorderRef = useRef(null);
    const regionsPluginRef = useRef(null);

    // ... (rest of recording logic is same) ...

    // === RECORDING ===
    const startRecording = async () => {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            const mediaRecorder = new MediaRecorder(stream);
            const chunks = [];

            mediaRecorder.ondataavailable = (e) => chunks.push(e.data);
            mediaRecorder.onstop = () => {
                const blob = new Blob(chunks, { type: 'audio/webm' });
                setAudioBlob(blob);
                stream.getTracks().forEach(track => track.stop());
            };

            mediaRecorder.start();
            setIsRecording(true);
            mediaRecorderRef.current = mediaRecorder;
        } catch (err) {
            console.error("Microphone access denied:", err);
            alert("Could not access microphone.");
        }
    };

    const stopRecording = () => {
        if (mediaRecorderRef.current && isRecording) {
            mediaRecorderRef.current.stop();
            setIsRecording(false);
        }
    };

    // === WAVEFORM & REGIONS ===
    useEffect(() => {
        if (audioBlob && containerRef.current) {
            // Init Wavesurfer
            const ws = WaveSurfer.create({
                container: containerRef.current,
                waveColor: '#4b5563',
                progressColor: '#3b82f6',
                cursorColor: '#ffffff',
                barWidth: 2,
                barGap: 3,
                height: variant === 'inline' ? 64 : 128, // Smaller height for inline
            });

            // Init Regions
            const wsRegions = ws.registerPlugin(RegionsPlugin.create());
            regionsPluginRef.current = wsRegions;

            // Load Blob
            ws.loadBlob(audioBlob);

            ws.on('ready', () => {
                // Enable click-to-create region
                wsRegions.enableDragSelection({
                    color: 'rgba(59, 130, 246, 0.3)',
                });
            });

            ws.on('finish', () => setIsPlaying(false));
            ws.on('play', () => setIsPlaying(true));
            ws.on('pause', () => setIsPlaying(false));

            wavesurferRef.current = ws;

            return () => {
                ws.destroy();
            };
        }
    }, [audioBlob, variant]);

    const togglePlay = () => {
        if (wavesurferRef.current) {
            wavesurferRef.current.playPause();
        }
    };

    // === EDITING (CUT) ===
    const handleCut = async () => {
        const regions = regionsPluginRef.current.getRegions();
        if (regions.length === 0) {
            alert("Please select a region to cut (remove).");
            return;
        }

        // For MVP: Take the first region and cut it out.
        const region = regions[0];
        const start = region.start;
        const end = region.end;

        setIsProcessing(true);
        try {
            const arrayBuffer = await audioBlob.arrayBuffer();
            const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);

            const sampleRate = audioBuffer.sampleRate;
            const startFrame = Math.floor(start * sampleRate);
            const endFrame = Math.floor(end * sampleRate);

            // Total frames - region duration
            const cutLength = endFrame - startFrame;
            const newLength = audioBuffer.length - cutLength;

            if (newLength <= 0) {
                alert("Cannot cut entire audio.");
                setIsProcessing(false);
                return;
            }

            const newBuffer = audioCtx.createBuffer(
                audioBuffer.numberOfChannels,
                newLength,
                sampleRate
            );

            for (let i = 0; i < audioBuffer.numberOfChannels; i++) {
                const channelData = audioBuffer.getChannelData(i);
                const newChannelData = newBuffer.getChannelData(i);

                // Copy part before cut
                for (let j = 0; j < startFrame; j++) {
                    newChannelData[j] = channelData[j];
                }

                // Copy part after cut
                for (let j = endFrame; j < audioBuffer.length; j++) {
                    newChannelData[j - cutLength] = channelData[j];
                }
            }

            // Convert back to Blob (WAV)
            const wavBlob = await bufferToWav(newBuffer);
            setAudioBlob(wavBlob); // Update state with new blob
            regionsPluginRef.current.clearRegions(); // Clear regions

        } catch (e) {
            console.error("Cut failed", e);
            alert("Cut failed: " + e.message);
        } finally {
            setIsProcessing(false);
        }
    };

    // Helper: AudioBuffer to WAV Blob
    const bufferToWav = (abuffer) => {
        const numOfChan = abuffer.numberOfChannels;
        const length = abuffer.length * numOfChan * 2 + 44;
        const buffer = new ArrayBuffer(length);
        const view = new DataView(buffer);
        const channels = [];
        let i;
        let sample;
        let offset = 0;
        let pos = 0;

        // write WAVE header
        setUint32(0x46464952); // "RIFF"
        setUint32(length - 8); // file length - 8
        setUint32(0x45564157); // "WAVE"

        setUint32(0x20746d66); // "fmt " chunk
        setUint32(16); // length = 16
        setUint16(1); // PCM (uncompressed)
        setUint16(numOfChan);
        setUint32(abuffer.sampleRate);
        setUint32(abuffer.sampleRate * 2 * numOfChan); // avg. bytes/sec
        setUint16(numOfChan * 2); // block-align
        setUint16(16); // 16-bit (hardcoded in this example)

        setUint32(0x61746164); // "data" - chunk
        setUint32(length - pos - 4); // chunk length

        // write interleaved data
        for (i = 0; i < abuffer.numberOfChannels; i++)
            channels.push(abuffer.getChannelData(i));

        while (pos < abuffer.length) {
            for (i = 0; i < numOfChan; i++) {
                sample = Math.max(-1, Math.min(1, channels[i][pos]));
                sample = (0.5 + sample < 0 ? sample * 32768 : sample * 32767) | 0;
                view.setInt16(44 + offset, sample, true);
                offset += 2;
            }
            pos++;
        }

        return new Blob([buffer], { type: "audio/wav" });

        function setUint16(data) {
            view.setUint16(pos, data, true);
            pos += 2;
        }

        function setUint32(data) {
            view.setUint32(pos, data, true);
            pos += 4;
        }
    };

    // === LANGUAGE TOGGLE ===
    // Use prop if available (controlled), otherwise local state (uncontrolled)
    const [localLang, setLocalLang] = useState('RU');
    const isControlled = propLang !== undefined;
    const lang = isControlled ? propLang : localLang;

    const setLang = (newLang) => {
        if (isControlled && onLangChange) {
            onLangChange(newLang);
        } else {
            setLocalLang(newLang);
        }
    };

    // === SAVE ===
    const handleSave = async () => {
        if (!audioBlob) return;
        setIsProcessing(true);

        // CUSTOM SAVE (e.g. Translate Tab)
        // If customSave is true, we usually want to save it as a specific filename
        // or trigger a download if no project is attached.
        if (customSave) {

            // 1. Determine Filename
            // If autoSaveName is provided, use it.
            // If NOT provided, and we have a project, let backend handle naming (Sequential).
            // If NO project, generate timestamp for download.

            const targetName = props.autoSaveName; // Can be undefined

            // If we are linked to a project (project prop exist) OR customUploadUrl is provided, we save to backend
            if (project || props.customUploadUrl) {
                const formData = new FormData();
                // If targetName is null, we can pass a dummy name in blob, but backend cares about query param or generation.
                // If we don't pass custom_filename, backend generates it.
                // WE MUST PASS 'file' argument to append. logic: formData.append('file', blob, filename)
                // If we don't have a filename, we can use "blob.wav" or anything, backend ignores it if generating name? 
                // Actually server.py: 
                //    if custom_filename: ... 
                //    else: ... new_filename = f"{name}-{new_index}.wav"
                // It writes: with open(file_path, "wb")...
                // So the filename in Append doesn't matter much for the *save path*, but good to be clean.

                formData.append('file', audioBlob, targetName || 'new_recording.wav');

                // Append custom_filename param ONLY if targetName is set
                // PASS VARIANT param
                let url = props.customUploadUrl || `http://localhost:8000/projects/${project.name}/audio?variant=${lang}`;
                if (targetName) {
                    const separator = url.includes('?') ? '&' : '?';
                    url += `${separator}custom_filename=${encodeURIComponent(targetName)}`;
                }

                try {
                    const res = await fetch(url, {
                        method: 'POST',
                        body: formData
                    });

                    if (res.ok) {
                        const data = await res.json();
                        onSave(data.path);
                        if (onClose) onClose();
                    } else {
                        throw new Error("Upload failed");
                    }
                } catch (e) {
                    alert("Failed to save recording: " + e.message);
                }
            } else {
                // No project context -> Browser Download (Fallback)
                downloadBlob(audioBlob, targetName || `recording_${lang}.wav`);
                onSave(targetName);
            }

            setIsProcessing(false);
            return;
        }

        // PROJECT SAVE (Standard)
        // Generate filename
        const filename = `recording_${Date.now()}.wav`; // Fallback for standard
        // ... (Usually we'd want variant here too but standard modal save might differ. 
        // For now user asked for Studio 'Audio Recorder' specifically which uses customSave=true)

        const formData = new FormData();
        formData.append('file', audioBlob, filename);

        const url = customSaveUrl || `http://localhost:8000/projects/${project?.name}/audio?variant=${lang}`;

        try {
            const res = await fetch(url, {
                method: 'POST',
                body: formData
            });

            if (res.ok) {
                const data = await res.json();
                onSave(data.path); // Return the saved path
                onClose();
            } else {
                throw new Error("Upload failed");
            }
        } catch (e) {
            alert("Failed to save recording");
            console.error(e);
        } finally {
            setIsProcessing(false);
        }
    };

    const downloadBlob = (blob, filename) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
    };

    const [script, setScript] = useState('');

    // ... existing logic ...

    // === RENDER CONTENT ===

    // Help render language toggle
    const renderLangToggle = (className = "absolute top-3 right-3") => (
        <div className={`${className} flex bg-black/50 rounded-lg p-1 border border-white/10 z-10 font-bold text-xs`}>
            <button
                onClick={() => setLang('RU')}
                className={`px-2 py-1 rounded transition-all ${lang === 'RU' ? 'bg-zinc-700 text-white shadow-sm' : 'text-zinc-500 hover:text-zinc-300'}`}
            >
                RU
            </button>
            <button
                onClick={() => setLang('ENG')}
                className={`px-2 py-1 rounded transition-all ${lang === 'ENG' ? 'bg-blue-600 text-white shadow-sm' : 'text-zinc-500 hover:text-zinc-300'}`}
            >
                ENG
            </button>
        </div>
    );

    const renderControls = () => (
        <div className="w-full h-full flex flex-col justify-center items-center">
            {/* RECORDING STATE */}
            {!audioBlob && !isRecording && (
                <div className={`text-center ${variant === 'inline' ? 'flex items-center gap-4 justify-center' : ''}`}>
                    <button
                        onClick={startRecording}
                        className={`${variant === 'modal'
                            ? 'w-24 h-24 rounded-full shadow-[0_0_30px_rgba(239,68,68,0.3)]'
                            : 'w-12 h-12 rounded-full shadow-md'} 
                            bg-red-500 hover:bg-red-400 text-white flex items-center justify-center transition-all hover:scale-105`}
                    >
                        <Mic size={variant === 'modal' ? 40 : 20} />
                    </button>
                    <p className={`${variant === 'modal' ? 'mt-6' : 'text-sm'} text-zinc-400`}>
                        {variant === 'modal' ? "Click to start recording" : "Record Audio"}
                    </p>
                </div>
            )}

            {isRecording && (
                <div className={`text-center ${variant === 'inline' ? 'flex items-center gap-4 justify-center' : ''}`}>
                    <div className={`${variant === 'modal' ? 'w-24 h-24 border-2' : 'w-12 h-12 border'} rounded-full bg-zinc-800 border-red-500 flex items-center justify-center animate-pulse`}>
                        <div className={`${variant === 'modal' ? 'w-4 h-4' : 'w-2 h-2'} bg-red-500 rounded-sm`}></div>
                    </div>

                    <div className={`${variant === 'modal' ? 'mt-6 flex flex-col items-center gap-2' : 'flex flex-col text-left'}`}>
                        {variant === 'modal' && <span className="text-red-500 font-mono animate-pulse">RECORDING...</span>}
                        <button
                            onClick={stopRecording}
                            className={`${variant === 'modal' ? 'px-6 py-2' : 'px-3 py-1 text-sm'} bg-zinc-800 hover:bg-zinc-700 text-white rounded-lg border border-red-500/30 transition-colors`}
                        >
                            Stop
                        </button>
                    </div>
                </div>
            )}

            {/* WAVEFORM & CONTROLS */}
            {audioBlob && (
                <div className="w-full">
                    <div ref={containerRef} className="w-full bg-black/40 rounded-xl border border-white/5 mb-4"></div>

                    <div className="flex items-center justify-between">
                        <div className="flex gap-2">
                            <button onClick={togglePlay} className="p-2 bg-white/10 hover:bg-white/20 rounded-full text-white transition-colors">
                                {isPlaying ? <Pause size={18} /> : <Play size={18} />}
                            </button>
                            <button onClick={() => { setAudioBlob(null); regionsPluginRef.current?.clearRegions(); }} className="p-2 hover:bg-red-500/20 rounded-full text-zinc-500 hover:text-red-400 transition-colors" title="Discard">
                                <Trash2 size={18} />
                            </button>
                        </div>

                        <div className="flex gap-2">
                            <button
                                onClick={handleCut}
                                className="flex items-center gap-2 px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-lg border border-white/10 transition-colors text-sm"
                                title="Remove selected region"
                            >
                                <Scissors size={14} /> {variant === 'modal' ? "Cut Selection" : "Cut"}
                            </button>

                            <button
                                onClick={handleSave}
                                disabled={isProcessing}
                                className="flex items-center gap-2 px-4 py-1.5 bg-green-600 hover:bg-green-500 text-white font-bold rounded-lg shadow-lg shadow-green-900/20 transition-all hover:scale-105 disabled:opacity-50 text-sm"
                            >
                                {isProcessing ? <Loader2 className="animate-spin" size={14} /> : <Save size={14} />}
                                {customSave ? "Save As..." : (variant === 'modal' ? "Save to Project" : "Save")}
                            </button>
                        </div>
                    </div>

                    {variant === 'modal' && (
                        <p className="text-center text-xs text-zinc-600 mt-6 md:mt-4">
                            Tip: Drag on the waveform to select a region to trim.
                        </p>
                    )}
                </div>
            )}
        </div>
    );

    const content = (
        <div className={`flex flex-col ${variant === 'modal' ? 'h-[500px]' : 'p-4 gap-4'}`}>
            {variant === 'modal' ? (
                <div className="flex flex-1 min-h-0">
                    {/* LEFT: SCRIPT */}
                    <div className="w-1/2 border-r border-white/10 p-6 flex flex-col bg-black/10">
                        <label className="text-xs uppercase font-bold text-zinc-500 tracking-wider mb-3 flex items-center gap-2">
                            Script / Notes
                        </label>
                        <textarea
                            value={script}
                            onChange={(e) => setScript(e.target.value)}
                            placeholder="Type or paste your script here to read while recording..."
                            className="flex-1 w-full bg-black/20 border border-white/5 rounded-xl p-4 text-base text-zinc-200 focus:outline-none focus:border-white/20 resize-none leading-relaxed custom-scrollbar placeholder-zinc-600"
                        />
                    </div>

                    {/* RIGHT: CONTROLS */}
                    <div className="w-1/2 p-6 flex flex-col bg-surface relative">
                        <div className="flex justify-between items-center mb-4">
                            <label className="text-xs uppercase font-bold text-zinc-500 tracking-wider flex items-center gap-2">
                                Audio Recorder
                            </label>
                            {renderLangToggle("")}
                        </div>
                        <div className="flex-1 flex items-center justify-center relative">
                            {renderControls()}
                        </div>
                    </div>
                </div>
            ) : (
                renderControls()
            )}
        </div>
    );



    // If modal, wrap in overlay. If inline, just return content.
    if (variant === 'inline') {
        return (
            <div className="bg-surface border border-border rounded-xl shadow-lg relative overflow-hidden animate-in slide-in-from-top-2">
                {/* {renderLangToggle()} - Controlled by Parent in inline mode */}
                {onClose && <button onClick={onClose} className="absolute top-2 right-24 text-zinc-500 hover:text-white"><X size={16} /></button>}
                {content}
            </div>
        );
    }

    return (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/90 backdrop-blur-md animate-in fade-in">
            <div className="bg-surface border border-border w-full max-w-4xl rounded-2xl shadow-2xl overflow-hidden flex flex-col relative">
                <div className="px-6 py-4 border-b border-border flex items-center justify-between bg-black/20">
                    <h3 className="text-lg font-bold text-white flex items-center gap-2">
                        <Mic className="text-red-500" /> Audio Recorder
                    </h3>
                    <button onClick={onClose} className="text-zinc-500 hover:text-white"><X size={20} /></button>
                </div>
                {content}
            </div>
        </div>
    );
}

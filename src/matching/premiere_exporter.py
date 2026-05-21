import json
import logging
import uuid
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

logger = logging.getLogger(__name__)

class PremiereExporter:
    """
    FCP XML (XMEML v4) compliant exporter for Adobe Premiere Pro.
    
    Key compliance features:
    - Proper file reference deduplication (first full, rest refs)
    - Rate elements on all clipitems
    - Duration on file elements
    - Proper masterclipid references
    """
    
    def __init__(self, width=1920, height=1080, fps=24):
        self.width = width
        self.height = height
        self.fps = int(fps)
        self.timebase = int(fps)
        # Track which files have already been fully defined
        self._defined_files = {}
        # Map file paths to their generated IDs to prevent duplication
        self._path_to_id_map = {}
        # Map file paths to their masterclip IDs to prevent duplication in Project bin
        self._path_to_masterclipid_map = {}

    def _frames(self, seconds):
        return int(round(seconds * self.fps))

    def _indent(self, elem, level=0):
        """Pretty-print XML with indentation."""
        i = "\n" + level * "\t"
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = i + "\t"
            if not elem.tail or not elem.tail.strip():
                elem.tail = i
            for child in elem:
                self._indent(child, level + 1)
            if not child.tail or not child.tail.strip():
                child.tail = i
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = i

    def _make_rate(self, parent):
        """Add a rate element."""
        rate = ET.SubElement(parent, "rate")
        ET.SubElement(rate, "timebase").text = str(self.timebase)
        ET.SubElement(rate, "ntsc").text = "FALSE"
        return rate

    def _make_file_url(self, path):
        """Create a properly encoded file:// URL."""
        path_str = str(path).replace('\\', '/')
        # Encoded, localhost style
        return f"file://localhost{urllib.parse.quote(path_str)}"

    def _create_video_file_element(self, parent, video_path, source_duration_frames):
        """
        Create or reference a video file element.
        Deduplicates files based on absolute path.
        """
        abs_path = Path(video_path).absolute() if video_path else None
        
        # Check if we already have an ID for this file
        if abs_path and str(abs_path) in self._path_to_id_map:
            file_id = self._path_to_id_map[str(abs_path)]
            # Just reference existing file
            ET.SubElement(parent, "file", id=file_id)
            return

        # Use a placeholder ID if no path (shouldn't happen often)
        if not abs_path:
            file_id = f"file-placeholder-{uuid.uuid4()}"
            ET.SubElement(parent, "file", id=file_id)
            return

        # Generate new ID
        file_id = f"file-{len(self._path_to_id_map) + 1}"
        self._path_to_id_map[str(abs_path)] = file_id
        
        # Create full definition
        file_node = ET.SubElement(parent, "file", id=file_id)
        
        if abs_path.exists():
            clean_name = abs_path.name
            file_url = self._make_file_url(abs_path)
        else:
            clean_name = f"{file_id}.mp4"
            file_url = f"file://localhost/PLACEHOLDER/{urllib.parse.quote(clean_name)}"
        
        ET.SubElement(file_node, "name").text = clean_name
        ET.SubElement(file_node, "pathurl").text = file_url
        
        # Duration of source file (important for Premiere!)
        ET.SubElement(file_node, "duration").text = str(source_duration_frames)
        
        # Rate
        self._make_rate(file_node)
        
        # Timecode
        tc = ET.SubElement(file_node, "timecode")
        self._make_rate(tc)
        ET.SubElement(tc, "string").text = "00:00:00:00"
        ET.SubElement(tc, "frame").text = "0"
        ET.SubElement(tc, "displayformat").text = "NDF"
        
        # Media characteristics
        mf = ET.SubElement(file_node, "media")
        vf = ET.SubElement(mf, "video")
        vsc = ET.SubElement(vf, "samplecharacteristics")
        self._make_rate(vsc)
        ET.SubElement(vsc, "width").text = str(self.width)
        ET.SubElement(vsc, "height").text = str(self.height)
        ET.SubElement(vsc, "anamorphic").text = "FALSE"
        ET.SubElement(vsc, "pixelaspectratio").text = "square"

    def _create_audio_file_element(self, parent, audio_path, duration_frames):
        """
        Create or reference an audio file element.
        """
        abs_path = audio_path.absolute()
        
        if str(abs_path) in self._path_to_id_map:
            file_id = self._path_to_id_map[str(abs_path)]
            ET.SubElement(parent, "file", id=file_id)
            return

        file_id = f"file-audio-{len(self._path_to_id_map) + 1}"
        self._path_to_id_map[str(abs_path)] = file_id
        
        file_node = ET.SubElement(parent, "file", id=file_id)
        
        clean_name = audio_path.name
        file_url = self._make_file_url(abs_path)
        
        ET.SubElement(file_node, "name").text = clean_name
        ET.SubElement(file_node, "pathurl").text = file_url
        ET.SubElement(file_node, "duration").text = str(duration_frames)
        
        self._make_rate(file_node)
        
        # Media characteristics
        mf = ET.SubElement(file_node, "media")
        af = ET.SubElement(mf, "audio")
        asc = ET.SubElement(af, "samplecharacteristics")
        ET.SubElement(asc, "depth").text = "16"
        ET.SubElement(asc, "samplerate").text = "48000"
        ET.SubElement(af, "channelcount").text = "2"

    def export(self, edl_path, output_xml_path, audio_file_path):
        """
        Export timeline to FCP XML (XMEML v4) format.
        """
        edl_path = Path(edl_path)
        output_xml_path = Path(output_xml_path)
        
        # Reset file tracking for new export
        self._defined_files = {}
        self._path_to_id_map = {}
        self._path_to_masterclipid_map = {}
        
        # Parse audio inputs
        audio_tracks = []
        if isinstance(audio_file_path, list):
            for item in audio_file_path:
                if isinstance(item, tuple):
                    audio_tracks.append({
                        "path": Path(item[0]).absolute(), 
                        "duration": float(item[1])
                    })
                else:
                    audio_tracks.append({
                        "path": Path(item).absolute(), 
                        "duration": 600.0
                    })
        else:
            audio_tracks.append({
                "path": Path(audio_file_path).absolute(), 
                "duration": 600.0
            })
        
        with open(edl_path, 'r') as f:
            edl = json.load(f)

        logger.info(f"🎞 Generating FCP XML (XMEML v4)...")

        # === ROOT ===
        xmeml = ET.Element("xmeml", version="4")
        
        # === SEQUENCE ===
        sequence = ET.SubElement(xmeml, "sequence")
        sequence.set("id", "sequence-1")
        
        ET.SubElement(sequence, "uuid").text = str(uuid.uuid4())
        ET.SubElement(sequence, "name").text = "Sculptor Pro Cut"
        
        # Calculate durations
        video_dur_frames = self._frames(sum(c['target_duration'] for c in edl))
        total_audio_sec = sum(t["duration"] for t in audio_tracks)
        audio_dur_frames = self._frames(total_audio_sec)
        total_frames = max(video_dur_frames, audio_dur_frames) + 240  # +10 sec buffer
        
        ET.SubElement(sequence, "duration").text = str(total_frames)
        self._make_rate(sequence)
        
        # Timecode for sequence
        tc = ET.SubElement(sequence, "timecode")
        self._make_rate(tc)
        ET.SubElement(tc, "string").text = "00:00:00:00"
        ET.SubElement(tc, "frame").text = "0"
        ET.SubElement(tc, "displayformat").text = "NDF"
        
        # === MEDIA ===
        media = ET.SubElement(sequence, "media")
        
        # === VIDEO ===
        video_media = ET.SubElement(media, "video")
        
        # Video format
        fmt = ET.SubElement(video_media, "format")
        sc = ET.SubElement(fmt, "samplecharacteristics")
        self._make_rate(sc)
        ET.SubElement(sc, "width").text = str(self.width)
        ET.SubElement(sc, "height").text = str(self.height)
        ET.SubElement(sc, "anamorphic").text = "FALSE"
        ET.SubElement(sc, "pixelaspectratio").text = "square"
        ET.SubElement(sc, "fielddominance").text = "none"
        ET.SubElement(sc, "colordepth").text = "24"
        
        # Video track
        track_video = ET.SubElement(video_media, "track")
        
        timeline_cursor = 0
        # Assume source files are long (e.g., 4 hours = ~345600 frames at 24fps)
        source_duration_estimate = 345600
        
        for i, cut in enumerate(edl):
            dur_frames = self._frames(cut['target_duration'])
            if dur_frames < 1:
                dur_frames = 1
            
            clipitem = ET.SubElement(track_video, "clipitem", id=f"clipitem-{i+1}")
            
            # Masterclip reference (Deduplicated)
            video_path = cut.get('source_video_path')
            abs_video_path = str(Path(video_path).absolute()) if video_path else None
            
            if abs_video_path and abs_video_path in self._path_to_masterclipid_map:
                masterclip_id = self._path_to_masterclipid_map[abs_video_path]
            else:
                masterclip_id = f"masterclip-sourcemain-{len(self._path_to_masterclipid_map) + 1}"
                if abs_video_path:
                    self._path_to_masterclipid_map[abs_video_path] = masterclip_id
            
            ET.SubElement(clipitem, "masterclipid").text = masterclip_id
            
            clip_name = cut['text'][:50] if cut.get('text') else f"Clip {i+1}"
            ET.SubElement(clipitem, "name").text = clip_name
            ET.SubElement(clipitem, "enabled").text = "TRUE"
            ET.SubElement(clipitem, "duration").text = str(dur_frames)
            
            self._make_rate(clipitem)
            
            clip_start_frames = self._frames(cut.get('timeline_start')) if 'timeline_start' in cut else timeline_cursor
            
            ET.SubElement(clipitem, "start").text = str(clip_start_frames)
            ET.SubElement(clipitem, "end").text = str(clip_start_frames + dur_frames)
            
            source_in = self._frames(cut.get('in_point', 0))
            source_out = self._frames(cut.get('out_point', cut.get('in_point', 0) + cut['target_duration']))
            ET.SubElement(clipitem, "in").text = str(source_in)
            ET.SubElement(clipitem, "out").text = str(source_out)
            
            # File reference
            video_path = cut.get('source_video_path')
            self._create_video_file_element(
                clipitem, 
                video_path, 
                source_duration_estimate
            )
            
            timeline_cursor = clip_start_frames + dur_frames
        
        # === AUDIO ===
        audio_media = ET.SubElement(media, "audio")
        
        # Audio format (needed for proper import)
        audio_fmt = ET.SubElement(audio_media, "format")
        audio_sc = ET.SubElement(audio_fmt, "samplecharacteristics")
        ET.SubElement(audio_sc, "depth").text = "16"
        ET.SubElement(audio_sc, "samplerate").text = "48000"
        
        # Audio track
        track_audio = ET.SubElement(audio_media, "track")
        
        audio_cursor = 0
        
        for j, track_info in enumerate(audio_tracks):
            path_obj = track_info["path"]
            duration_sec = track_info["duration"]
            duro_frames = self._frames(duration_sec)
            if duro_frames < 1:
                duro_frames = 1
            
            clip_audio = ET.SubElement(track_audio, "clipitem", id=f"clipitem-audio-{j+1}")
            
            ET.SubElement(clip_audio, "masterclipid").text = f"masterclip-audio-{j+1}"
            ET.SubElement(clip_audio, "name").text = path_obj.name
            ET.SubElement(clip_audio, "enabled").text = "TRUE"
            ET.SubElement(clip_audio, "duration").text = str(duro_frames)
            
            self._make_rate(clip_audio)
            
            ET.SubElement(clip_audio, "start").text = str(audio_cursor)
            ET.SubElement(clip_audio, "end").text = str(audio_cursor + duro_frames)
            ET.SubElement(clip_audio, "in").text = "0"
            ET.SubElement(clip_audio, "out").text = str(duro_frames)
            
            # File reference
            self._create_audio_file_element(
                clip_audio,
                path_obj,
                duro_frames
            )
            
            audio_cursor += duro_frames
        
        # === SAVE ===
        self._indent(xmeml)
        tree = ET.ElementTree(xmeml)
        
        # Atomic write
        temp_path = output_xml_path.with_suffix('.tmp')
        try:
            tree.write(temp_path, encoding="UTF-8", xml_declaration=True)
            
            if temp_path.exists():
                temp_path.replace(output_xml_path)
                logger.info(f"✅ FCP XML Exported: {output_xml_path}")
            else:
                logger.error(f"❌ Temp file creation failed")
        except Exception as e:
            logger.error(f"❌ XML Write Failed: {e}")
            if temp_path.exists():
                temp_path.unlink()
            raise
#!/usr/bin/env python3
"""charts.py shim — load charts from JSON files in `charts/`.

Exports:
  - `SongDef` class (compatibility)
  - `SONGS` list of `SongDef` instances built from JSON files

This replaces the old monolithic file-based SongDef registry.
"""

from pathlib import Path
import json, os
from typing import List, Tuple

_DIR = Path(__file__).parent

def _audio(filename: str):
    if not filename:
        return None
    p = _DIR / filename
    return str(p) if p.exists() else None


class SongDef:
    def __init__(self, title: str, artist: str, bpm: int, pattern: List[Tuple[float,int,bool,float]], audio_file: str = None):
        self.title = title
        self.artist = artist
        self.bpm = bpm
        self.pattern = pattern
        self.audio_file = audio_file


def _note_from_raw(n):
    t = n.get("time_ms", 0) / 1000.0
    lane = int(n.get("lane", 0))
    if n.get("type") == "hold" or n.get("duration_ms"):
        dur = n.get("duration_ms", 0) / 1000.0
        return (round(t, 3), lane, True, round(dur, 3))
    return (round(t, 3), lane, False, 0.0)


def _load_from_json(path: Path) -> SongDef:
    raw = json.loads(path.read_text(encoding="utf-8"))
    notes = raw.get("notes", [])
    pattern = [_note_from_raw(n) for n in notes]
    audio_name = raw.get("audio_file") or raw.get("meta", {}).get("audio") or raw.get("meta", {}).get("cover")
    audio_file = _audio(audio_name) if audio_name else None
    return SongDef(raw.get("title", "Untitled"), raw.get("artist", "Unknown"), int(raw.get("bpm", 120)), pattern, audio_file)


def discover_songs(charts_dir: Path = None):
    charts_dir = Path(charts_dir) if charts_dir else (_DIR / "charts")
    songs = []
    if not charts_dir.exists():
        return songs
    for p in sorted(charts_dir.glob("*.json")):
        try:
            songs.append(_load_from_json(p))
        except Exception:
            continue
    return songs


# Build SONGS on import for compatibility with previous code
SONGS = discover_songs()

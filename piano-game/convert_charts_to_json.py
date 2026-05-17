import os, json
from pathlib import Path

import charts as old_charts

OUT_DIR = Path(__file__).parent / "charts"
OUT_DIR.mkdir(exist_ok=True)

def note_from_tuple(tpl):
    # tpl: (time_seconds, lane, is_hold_bool, hold_duration_sec)
    time_s, lane, is_hold, hold_dur = tpl
    note = {"time_ms": int(round(time_s * 1000)), "lane": int(lane)}
    if is_hold and hold_dur:
        note["type"] = "hold"
        note["duration_ms"] = int(round(hold_dur * 1000))
    else:
        note["type"] = "tap"
    return note

def filename_for(song, idx):
    title = song.title.replace(" ", "_").lower()
    artist = song.artist.replace(" ", "_").lower()
    diff = getattr(song, 'difficulty', 'unknown')
    name = f"{artist}__{title}__{diff}"
    # ensure unique
    p = OUT_DIR / f"{name}.json"
    i = 1
    while p.exists():
        p = OUT_DIR / f"{name}_{i}.json"
        i += 1
    return p

def main():
    songs = getattr(old_charts, 'SONGS', None)
    if not songs:
        print("No SONGS list found in charts.py")
        return
    for i, s in enumerate(songs):
        notes = [note_from_tuple(t) for t in s.pattern]
        length_ms = max((n['time_ms'] + n.get('duration_ms',0)) for n in notes) if notes else 0
        audio_basename = None
        if getattr(s, 'audio_file', None):
            audio_basename = os.path.basename(s.audio_file)
        obj = {
            "id": f"{s.artist}-{s.title}-{i}".replace(' ', '-').lower(),
            "title": s.title,
            "artist": s.artist,
            "bpm": getattr(s, 'bpm', 120),
            "offset_ms": getattr(s, 'offset_ms', 0),
            "difficulty": getattr(s, 'difficulty', 'default'),
            "lanes": getattr(s, 'lanes', 4),
            "length_ms": int(length_ms),
            "meta": {"audio": audio_basename},
            "notes": notes,
        }
        outp = filename_for(s, i)
        outp.write_text(json.dumps(obj, indent=2), encoding='utf-8')
        print(f"Wrote {outp}")

if __name__ == '__main__':
    main()

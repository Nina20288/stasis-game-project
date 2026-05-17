#!/usr/bin/env python3
"""
make_chart.py  —  Auto-generate a chart from an MP3 and append it to charts.py

Usage:
    python3 make_chart.py MySong.mp3
    python3 make_chart.py MySong.mp3 --artist "Artist Name"

Requirements:  ffmpeg (system), numpy
    pip install numpy --break-system-packages

What it does:
  1. Decodes the MP3 to raw PCM via ffmpeg
  2. Detects onsets using spectral flux + adaptive threshold
  3. Assigns lanes semi-randomly, adds hold notes at ~15% rate
  4. Prints a SongDef block and appends it to charts.py
  5. Adds the new song to the SONGS list in charts.py
"""

import sys, os, subprocess, argparse, textwrap
import numpy as np

SR  = 22050
HOP = 512
WIN = 1024


def decode_mp3(mp3_path):
    tmp = "/tmp/_make_chart_audio.f32"
    result = subprocess.run([
        "ffmpeg", "-i", mp3_path,
        "-ar", str(SR), "-ac", "1", "-f", "f32le", tmp, "-y"
    ], capture_output=True)
    if result.returncode != 0:
        print("[ERROR] ffmpeg failed:")
        print(result.stderr.decode())
        sys.exit(1)
    audio = np.frombuffer(open(tmp,'rb').read(), dtype=np.float32)
    os.remove(tmp)
    return audio


def detect_onsets(audio):
    frames = len(audio) // HOP
    energy = np.array([
        np.sqrt(np.mean(audio[i*HOP : i*HOP+WIN]**2))
        for i in range(frames - 1)
    ])
    flux = np.maximum(0, np.diff(energy))
    flux = flux / (flux.max() + 1e-9)

    W = 20
    threshold = np.array([
        flux[max(0,i-W):i+W].mean() + 1.2*flux[max(0,i-W):i+W].std()
        for i in range(len(flux))
    ])

    MIN_SPACING = int(0.12 * SR / HOP)
    onsets, last = [], -MIN_SPACING
    for i in range(len(flux)):
        if flux[i] > threshold[i] and flux[i] > 0.05 and i-last >= MIN_SPACING:
            onsets.append(i * HOP / SR)
            last = i

    return onsets, energy


def estimate_bpm(onsets):
    if len(onsets) < 2:
        return 120
    iois = np.diff(onsets)
    beat_iois = iois[(iois > 0.28) & (iois < 1.1)]
    if not len(beat_iois):
        return 120
    return round(60 / np.median(beat_iois))


def build_pattern(onsets, energy, seed=42):
    rng  = np.random.RandomState(seed)
    pattern, prev = [], []
    for t in onsets:
        if t < 1.5:
            continue
        frame_idx = int(t * SR / HOP)
        e = energy[min(frame_idx, len(energy)-1)]
        n_notes = 2 if e > 0.08 else 1
        avail = [l for l in range(4) if l not in prev[-1:]]
        if len(avail) < n_notes:
            avail = list(range(4))
        lanes = list(rng.choice(avail, size=min(n_notes, len(avail)), replace=False))
        for lane in lanes:
            is_hold  = (n_notes == 1 and rng.random() < 0.15)
            hold_dur = round(rng.uniform(0.4, 0.9), 2) if is_hold else 0.0
            pattern.append((round(t, 3), int(lane), is_hold, hold_dur))
        prev = lanes
    return pattern


def make_var_name(title):
    """Turn a song title into a Python variable name."""
    import re
    name = re.sub(r"[^a-zA-Z0-9 ]", "", title).strip()
    return "_".join(name.upper().split())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mp3", help="Path to MP3 file")
    parser.add_argument("--artist", default="Unknown", help="Artist name")
    parser.add_argument("--title",  default=None,      help="Song title (default: filename)")
    parser.add_argument("--charts-dir", default="charts", help="Path to charts directory (default: ./charts)")
    args = parser.parse_args()

    mp3_path = os.path.abspath(args.mp3)
    if not os.path.exists(mp3_path):
        print(f"[ERROR] File not found: {mp3_path}")
        sys.exit(1)

    mp3_filename = os.path.basename(mp3_path)
    title  = args.title or os.path.splitext(mp3_filename)[0].replace("_", " ")
    varname = make_var_name(title)

    print(f"[1/4] Decoding {mp3_filename}...")
    audio = decode_mp3(mp3_path)
    duration = len(audio) / SR
    print(f"      Duration: {duration:.1f}s")

    print(f"[2/4] Detecting onsets...")
    onsets, energy = detect_onsets(audio)
    print(f"      Found {len(onsets)} onsets")

    bpm = estimate_bpm(onsets)
    print(f"[3/4] Estimated BPM: {bpm}")

    pattern = build_pattern(onsets, energy)
    print(f"      Built {len(pattern)} chart notes")

    # Format pattern lines
    pat_lines = "\n".join(
        f"        ({t}, {l}, {h}, {d}),"
        for t, l, h, d in pattern
    )

    block = textwrap.dedent(f"""

# ══════════════════════════════════════════════════════════════════════════════
#  {title.upper()}  —  {args.artist}  |  {bpm} BPM  |  {duration:.0f}s
# ══════════════════════════════════════════════════════════════════════════════
{varname} = SongDef(
    title      = "{title}",
    artist     = "{args.artist}",
    bpm        = {bpm},
    audio_file = _audio("{mp3_filename}"),
    pattern    = [
{pat_lines}
    ],
)
""")

    charts_dir = os.path.abspath(args.charts_dir)
    print(f"[4/4] Writing chart JSON to {charts_dir}...")

    if not os.path.exists(charts_dir):
        os.makedirs(charts_dir, exist_ok=True)

    # Build JSON object
    notes = []
    for t, l, h, d in pattern:
        obj = {"time_ms": int(round(t * 1000)), "lane": int(l)}
        if h and d:
            obj["type"] = "hold"
            obj["duration_ms"] = int(round(d * 1000))
        else:
            obj["type"] = "tap"
        notes.append(obj)

    length_ms = max((n['time_ms'] + n.get('duration_ms', 0)) for n in notes) if notes else 0

    out = {
        "id": f"{title}-{args.artist}".replace(' ', '-').lower(),
        "title": title,
        "artist": args.artist,
        "bpm": int(bpm),
        "offset_ms": 0,
        "difficulty": "default",
        "lanes": 4,
        "length_ms": int(length_ms),
        "meta": {"audio": mp3_filename},
        "notes": notes,
    }

    import json
    song_name = title.replace(' ', '_').replace('/', '_').lower()
    artist_name = args.artist.replace(' ', '_').replace('/', '_').lower()
    safe_name = f"{song_name}_{artist_name}.json"
    out_path = os.path.join(charts_dir, safe_name)
    i = 1
    base, ext = os.path.splitext(out_path)
    while os.path.exists(out_path):
        out_path = f"{base}_{i}{ext}"
        i += 1

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2)

    print(f"\n✓ Done! Wrote {out_path}")
    print(f"  Make sure {mp3_filename} is in the same folder as the game (or update meta.audio).")


if __name__ == "__main__":
    main()
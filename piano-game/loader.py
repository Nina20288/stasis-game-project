from pathlib import Path
import json
from typing import Dict, Any, Optional

DEFAULT_CHARTS_DIR = Path(__file__).parent / "charts"

def validate_chart(data: Dict[str, Any]) -> None:
    required = ["id", "title", "artist", "bpm", "offset_ms", "difficulty", "lanes", "notes"]
    for k in required:
        if k not in data:
            raise ValueError(f"Missing required field: {k}")
    if not isinstance(data["notes"], list):
        raise ValueError("notes must be a list")

def preprocess_chart(data: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(data)
    data["notes"] = [(int(n["time_ms"]), int(n["lane"]), n.get("type", "tap")) for n in data["notes"]]
    return data

def discover_charts(charts_dir: Optional[Path] = None) -> Dict[str, Path]:
    charts_dir = Path(charts_dir) if charts_dir else DEFAULT_CHARTS_DIR
    charts: Dict[str, Path] = {}
    if not charts_dir.exists():
        return charts
    for p in charts_dir.glob("*.json"):
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            cid = raw.get("id") or p.stem
            charts[cid] = p
        except Exception:
            continue
    return charts

def load_chart_by_path(path: Path) -> Dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_chart(data)
    return preprocess_chart(data)

def load_chart(chart_id: str, charts_dir: Optional[Path] = None) -> Dict[str, Any]:
    charts = discover_charts(charts_dir)
    if chart_id not in charts:
        raise KeyError(f"Chart '{chart_id}' not found")
    return load_chart_by_path(charts[chart_id])

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--list", action="store_true")
    p.add_argument("--dir", default=None)
    p.add_argument("--id", default=None)
    args = p.parse_args()
    if args.list:
        charts = discover_charts(args.dir)
        for cid, path in charts.items():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                print(f"{cid}: {raw.get('title')} — {raw.get('artist')} ({raw.get('difficulty')})")
            except Exception as e:
                print(f"{cid}: error reading ({e})")
    elif args.id:
        ch = load_chart(args.id, args.dir)
        print(f"Loaded: {ch['id']} - {ch['title']} - {len(ch['notes'])} notes")
    else:
        p.print_help()

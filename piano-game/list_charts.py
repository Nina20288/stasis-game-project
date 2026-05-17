from pathlib import Path
import json
from loader import discover_charts

def main():
    charts = discover_charts()
    if not charts:
        print("No charts found in charts/ directory.")
        return
    for cid, path in charts.items():
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            print(f"{cid}: {raw.get('title')} — {raw.get('artist')} ({raw.get('difficulty')})")
        except Exception as e:
            print(f"{cid}: error reading ({e})")

if __name__ == "__main__":
    main()

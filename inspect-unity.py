"""Read-only Unity bundle inventory helper for the SVWB mod lab."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import UnityPy
import UnityPy.config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()

    # Runtime bundles in the game's cache omit the Unity version string.
    UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.62f2"
    env = UnityPy.load(str(args.bundle))
    counts = Counter(obj.type.name for obj in env.objects)
    print(f"Bundle: {args.bundle}")
    print(f"Objects: {len(env.objects)}")
    for name, count in counts.most_common():
        print(f"{name}\t{count}")

    for obj in env.objects:
        if obj.type.name not in {"Texture2D", "Sprite", "SpriteAtlas"}:
            continue
        try:
            item = obj.read()
            name = getattr(item, "m_Name", "")
            if obj.type.name == "Texture2D":
                detail = f"{getattr(item, 'm_Width', '?')}x{getattr(item, 'm_Height', '?')}"
            else:
                detail = ""
            print(f"VISUAL\t{obj.type.name}\t{obj.path_id}\t{name}\t{detail}")
        except Exception as exc:
            print(f"WARN\t{obj.type.name}\t{obj.path_id}\t{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()

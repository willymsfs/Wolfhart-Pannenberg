#!/usr/bin/env python3
"""Sort photos/videos exported from an iPhone into a tidy folder structure.

Layout produced inside DEST:
    Photos/2025/2025-03/           camera photos by year/month
    Screenshots/2025/              screenshots
    WhatsApp/2025/                 images/videos saved from WhatsApp
    Videos/2025/                   camera videos
    _Duplicates/                   byte-identical copies (nothing is deleted)
    _Unsorted/                     files with unknown type (e.g. .AAE sidecars)

Safe by default: DRY RUN, and files are COPIED (use --move to move).
Live Photos (IMG_1234.HEIC + IMG_1234.MOV) are kept together.

Usage:
    python3 organize_photos.py SOURCE DEST            # preview only
    python3 organize_photos.py SOURCE DEST --apply    # actually copy
    python3 organize_photos.py SOURCE DEST --apply --move
Optional: pip install pillow pillow-heif   (better date detection from EXIF)
"""
import argparse, hashlib, re, shutil, sys
from collections import Counter
from datetime import datetime
from pathlib import Path

PHOTO = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".gif", ".webp", ".tiff", ".dng"}
VIDEO = {".mov", ".mp4", ".m4v", ".3gp"}

try:
    from PIL import Image
    try:
        import pillow_heif; pillow_heif.register_heif_opener()
    except ImportError:
        pass
except ImportError:
    Image = None

NAME_DATE = re.compile(r"(20\d{2}|19\d{2})[-_]?([01]\d)[-_]?([0-3]\d)")


def exif_info(path):
    """Return (datetime|None, has_camera_make)."""
    if Image is None:
        return None, False
    try:
        with Image.open(path) as im:
            ex = im.getexif()
            sub = ex.get_ifd(0x8769) if hasattr(ex, "get_ifd") else {}
            raw = sub.get(36867) or ex.get(306)
            dt = datetime.strptime(str(raw)[:19], "%Y:%m:%d %H:%M:%S") if raw else None
            return dt, bool(ex.get(271))
    except Exception:
        return None, False


def date_of(path, exif_dt):
    if exif_dt:
        return exif_dt
    m = NAME_DATE.search(path.name)
    if m:
        try:
            return datetime(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime)


def classify(path, has_make):
    ext, name = path.suffix.lower(), path.name.lower()
    if ext not in PHOTO | VIDEO:
        return "Unsorted"
    if "-wa" in name or name.startswith("whatsapp"):
        return "WhatsApp"
    if "screenshot" in name or "screen shot" in name or (ext == ".png" and not has_make):
        return "Screenshots"
    return "Videos" if ext in VIDEO else "Photos"


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def unique(dest):
    if not dest.exists():
        return dest
    for i in range(1, 10000):
        c = dest.with_name(f"{dest.stem}_{i}{dest.suffix}")
        if not c.exists():
            return c
    raise RuntimeError("too many name clashes")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path)
    ap.add_argument("dest", type=Path)
    ap.add_argument("--apply", action="store_true", help="really copy/move (default: preview)")
    ap.add_argument("--move", action="store_true", help="move instead of copy")
    a = ap.parse_args()
    src, dst = a.source.resolve(), a.dest.resolve()
    if not src.is_dir():
        sys.exit(f"Source not found: {src}")
    if dst == src or src in dst.parents:
        sys.exit("DEST must be outside SOURCE.")

    files = sorted(p for p in src.rglob("*") if p.is_file() and not p.name.startswith("."))
    seen, plan, stats = {}, [], Counter()
    live = {}  # stem+folder -> target folder of the still photo (Live Photos)

    # photos first so a same-named .MOV can follow its still image
    files.sort(key=lambda p: (p.suffix.lower() in VIDEO, str(p)))
    for p in files:
        ext = p.suffix.lower()
        digest = sha(p)
        if digest in seen:
            plan.append((p, dst / "_Duplicates" / p.name)); stats["Duplicates"] += 1
            continue
        seen[digest] = p
        exif_dt, has_make = exif_info(p) if ext in PHOTO else (None, False)
        kind = classify(p, has_make)
        key = (p.parent, p.stem.lower())
        if ext in PHOTO and kind == "Photos":
            live[key] = None
        if kind == "Unsorted":
            target = dst / "_Unsorted"
        elif ext in VIDEO and key in live and live[key]:
            target = live[key]; kind = "Photos(live)"
        else:
            d = date_of(p, exif_dt)
            target = dst / kind / str(d.year)
            if kind == "Photos":
                target = target / f"{d.year}-{d.month:02d}"
            if key in live:
                live[key] = target
        plan.append((p, target / p.name)); stats[kind] += 1

    print(f"{len(files)} files scanned in {src}")
    for k, v in stats.most_common():
        print(f"  {k:14} {v}")
    if Image is None:
        print("  (tip: pip install pillow pillow-heif for exact EXIF dates)")
    if not a.apply:
        print("\nDRY RUN - first 15 planned moves (re-run with --apply):")
        for s, t in plan[:15]:
            print(f"  {s.name} -> {t.relative_to(dst)}")
        return
    for s, t in plan:
        t.parent.mkdir(parents=True, exist_ok=True)
        t = unique(t)
        (shutil.move if a.move else shutil.copy2)(s, t)
    print(f"\nDone: {'moved' if a.move else 'copied'} {len(plan)} files to {dst}")


if __name__ == "__main__":
    main()

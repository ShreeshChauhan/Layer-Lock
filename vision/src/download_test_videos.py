"""Download annotated research clips (five by default; --all for the catalog)."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "datasets" / "videos"
MANIFEST = ROOT / "datasets" / "test_videos_manifest.csv"
DATASET = "https://github.com/EmptyDeck/3DPrint-Failure-Video-Dataset"
# video_links.md label, sequences.csv label, YouTube ID, onset frame, frame count.
# Metadata declares 1 fps and zero-based frames. Labels differ between files;
# join by YouTube ID rather than guessing sequence names.
SELECTION = [
    ("PinkNetriti", "PinkNetriti_Early", "nx7Wy4spvGM", 49, 270),
    ("YellowEarly", "YellowEarly", "Y8H8eqtemuk", 120, 391),
    ("WhiteHorseback", "WhiteHorseback", "qI8mrMG_b6c", 262, 4721),
    ("BlackEarly", "BlackTilt_noz", "taTnJqpeyy8", 312, 1207),
    ("P2RedSkull", "RedSkullEarly", "X-NGUAAV_uc", 317, 741),
]


def clip_range(onset: float, duration: float) -> tuple[float, float]:
    """Keep 60 seconds by shifting at boundaries; use all of shorter videos."""
    if not (math.isfinite(onset) and math.isfinite(duration)):
        raise ValueError("Non-finite onset or duration")
    if duration <= 0 or not 0 <= onset < duration:
        raise ValueError(f"Onset {onset} is outside video duration {duration}")
    length = min(60.0, duration)
    start = min(max(0.0, onset - 20.0), duration - length)
    return start, start + length


def planned_rows(selection=None) -> list[dict]:
    rows = []
    for label, sequence, video_id, onset, duration in SELECTION if selection is None else selection:
        start, end = clip_range(onset, duration)
        rows.append(dict(
            dataset_label=label, metadata_sequence=sequence,
            source_url=f"https://www.youtube.com/watch?v={video_id}",
            failure_category="bed_adhesion", onset_frame=onset, annotation_fps=1,
            failure_onset_seconds=onset,
            failure_onset_timestamp=f"{onset // 3600:02}:{onset // 60 % 60:02}:{onset % 60:02}",
            source_duration_seconds=duration, clip_start_seconds=start,
            clip_end_seconds=end, onset_in_clip_seconds=onset - start,
            output_filename=f"bed_adhesion_{label}_{video_id}_onset_{onset}s.mp4",
            actual_clip_duration_seconds="", status="planned", error="",
            license="CC BY-NC 4.0 (dataset README)", dataset_url=DATASET,
        ))
    return rows


def catalog_selection():
    """Read the saved upstream metadata snapshot; preserve initial five filenames."""
    aliases = {entry[2]: entry[0] for entry in SELECTION}
    with (ROOT / "datasets" / "dataset_sequences.csv").open(newline="", encoding="utf-8-sig") as handle:
        catalog = list(csv.DictReader(handle))
    selection = []
    for row in catalog:
        video_id = parse_qs(urlparse(row["video_url"]).query)["v"][0]
        if float(row["fps"]) != 1:
            raise ValueError("Catalog FPS changed; review onset conversion before downloading")
        selection.append((aliases.get(video_id, row["sequence"]), row["sequence"],
                          video_id, int(row["onset_frame"]), int(row["n_frames"])))
    if len({entry[2] for entry in selection}) != len(selection):
        raise ValueError("Duplicate video IDs in catalog")
    return selection


def write_manifest(rows: list[dict], path: Path = MANIFEST) -> None:
    temporary = path.with_suffix(".csv.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def run(command: list[str], timeout: int = 1800) -> str:
    result = subprocess.run(command, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout)[-2500:].strip())
    return result.stdout


def verify(path: Path, expected: float) -> float:
    info = json.loads(run([
        "ffprobe", "-v", "error", "-show_streams", "-show_format",
        "-of", "json", str(path),
    ], timeout=60))
    if not any(s.get("codec_type") == "video" for s in info["streams"]):
        raise RuntimeError("Output has no video stream")
    duration = float(info["format"]["duration"])
    # The sources are 1 fps; allow one frame of container rounding.
    if not math.isfinite(duration) or abs(duration - expected) > 1.1:
        raise RuntimeError(f"Clip duration {duration}s; expected {expected}s")
    run(["ffmpeg", "-v", "error", "-xerror", "-i", str(path),
         "-map", "0:v:0", "-f", "null", "-"], timeout=180)
    return duration


def process(row: dict, overwrite: bool) -> None:
    target = OUTPUT / row["output_filename"]
    expected = row["clip_end_seconds"] - row["clip_start_seconds"]
    if target.exists() and not overwrite:
        row["actual_clip_duration_seconds"] = verify(target, expected)
        row["status"] = "verified_existing"
        return
    base = [sys.executable, "-m", "yt_dlp", "--ignore-config",
            "--no-cache-dir", "--no-playlist", "--no-progress", "--no-geo-bypass",
            "--socket-timeout", "30", "--retries", "2", "--fragment-retries", "2"]
    info = json.loads(run(base + ["--dump-single-json", "--skip-download",
                                 row["source_url"]], timeout=180))
    if info.get("is_live") or info.get("has_drm"):
        raise RuntimeError("Live or DRM-protected video is not supported")
    if info.get("availability") not in (None, "public", "unlisted"):
        raise RuntimeError("Video is access-restricted; no authentication attempted")
    duration = float(info.get("duration") or 0)
    # A differently sped-up YouTube upload cannot use these frame annotations.
    if not math.isfinite(duration) or abs(duration - row["source_duration_seconds"]) > 2:
        raise RuntimeError("Hosted duration differs from annotation timeline; "
                           "verify alignment manually before using this video")
    start, end = clip_range(row["failure_onset_seconds"], duration)
    row.update(source_duration_seconds=duration, clip_start_seconds=start,
               clip_end_seconds=end,
               onset_in_clip_seconds=row["failure_onset_seconds"] - start)
    with tempfile.TemporaryDirectory(prefix="clip_", dir=OUTPUT) as folder:
        work = Path(folder)
        # FFmpeg seeks remotely; do not first download hours of source footage.
        run(base + ["--format", "bestvideo[ext=mp4]/best[ext=mp4]/bestvideo/best",
                    "--download-sections", f"*{start}-{end}",
                    "--force-keyframes-at-cuts", "--output", str(work / "source.%(ext)s"),
                    row["source_url"]])
        sources = [p for p in work.glob("source.*")
                   if p.suffix not in (".part", ".ytdl", ".temp")]
        if len(sources) != 1:
            raise RuntimeError("Download did not produce exactly one complete video")
        encoded = work / "verified.mp4"
        run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(sources[0]),
             "-t", str(end - start), "-map", "0:v:0", "-an", "-c:v", "libx264",
             "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", str(encoded)])
        row["actual_clip_duration_seconds"] = verify(encoded, end - start)
        encoded.replace(target)
    row["status"] = "downloaded_verified"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true", help="Write planned CSV without network or dependencies")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing clips after verifying replacements")
    parser.add_argument("--all", action="store_true", help="Process all entries in dataset_sequences.csv")
    args = parser.parse_args()
    rows = planned_rows(catalog_selection()) if args.all else planned_rows()
    retained = {}
    if MANIFEST.exists():
        with MANIFEST.open(newline="", encoding="utf-8-sig") as handle:
            retained = {row["source_url"]: row for row in csv.DictReader(handle)}
    def persist():
        merged = dict(retained)
        merged.update({row["source_url"]: row for row in rows})
        write_manifest(list(merged.values()))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if args.plan:
        for row in rows:
            retained.setdefault(row["source_url"], row)
        write_manifest(list(retained.values()))
        print(f"Manifest includes {len(retained)} clips: {MANIFEST}")
        return 0
    missing = [name for name in ("ffmpeg", "ffprobe") if not shutil.which(name)]
    if importlib.util.find_spec("yt_dlp") is None:
        missing.append("yt-dlp (install: python -m pip install -U yt-dlp)")
    if missing:
        for row in rows:
            row.update(status="blocked_dependencies", error="Missing: " + ", ".join(missing))
        for row in rows:
            retained.setdefault(row["source_url"], row)
        write_manifest(list(retained.values()))
        print("Missing dependencies: " + ", ".join(missing), file=sys.stderr)
        print("Install FFmpeg and FFprobe on PATH. See vision/docs/TEST_VIDEOS.md.", file=sys.stderr)
        return 2
    print("Dataset license: CC BY-NC 4.0, research use. Retain attribution; "
          "commercial use requires separate permission.")
    for row in rows:
        print(f"Processing {row['dataset_label']}...", flush=True)
        try:
            process(row, args.overwrite)
        except (RuntimeError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
            row.update(status="failed", error=str(error))
            print(f"FAILED {row['dataset_label']}: {error}", file=sys.stderr)
        except KeyboardInterrupt:
            row.update(status="interrupted", error="Interrupted by user")
            persist()
            return 130
        persist()
    successes = sum(r["status"] in ("downloaded_verified", "verified_existing") for r in rows)
    print(f"Verified {successes}/{len(rows)} clips. Manifest: {MANIFEST}")
    return 0 if successes == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())

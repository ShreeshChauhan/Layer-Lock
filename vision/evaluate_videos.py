"""Evaluate prerecorded constant-FPS clips; timestamps are clip-relative.

Examples (from repository root):
    python vision/evaluate_videos.py --source vision/test_videos/example.mp4
    python vision/evaluate_videos.py --all

Bed-adhesion onset annotations are context, not spaghetti ground truth.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
import math
from pathlib import Path
import sys
import time

import cv2

ROOT = Path(__file__).resolve().parent
FIELDS = [
    "video", "frame_index", "clip_timestamp_seconds", "spaghetti_detected",
    "highest_spaghetti_confidence", "predicted_categories", "detections_json",
    "inference_ms", "status", "error", "screenshot", "source_url",
    "failure_category", "source_timestamp_seconds", "source_failure_onset_seconds",
    "clip_failure_onset_seconds", "manifest_clip_start_seconds",
    "roi_xywh", "preview",
]


def validate_roi(roi, shape) -> tuple[int, int, int, int]:
    if len(roi) != 4 or any(not isinstance(v, int) for v in roi):
        raise ValueError("ROI must be four integer pixel values: X Y WIDTH HEIGHT")
    x, y, width, height = roi
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError("ROI must be nonempty with nonnegative origin")
    if x + width > shape[1] or y + height > shape[0]:
        raise ValueError(f"ROI {roi} exceeds frame size {shape[1]}x{shape[0]}")
    return x, y, width, height


def draw_roi(frame, roi):
    preview = frame.copy()
    if roi is not None:
        x, y, width, height = validate_roi(roi, frame.shape)
        cv2.rectangle(preview, (x, y), (x + width - 1, y + height - 1), (0, 255, 0), 2)
    return preview


def select_video_roi(source, roi, interactive=False, seconds=0.0):
    capture = cv2.VideoCapture(str(source))
    try:
        if not capture.isOpened():
            raise ValueError("Cannot open video for ROI selection")
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError("Invalid FPS for ROI selection")
        target = math.ceil(seconds * fps)
        if target and not capture.set(cv2.CAP_PROP_POS_FRAMES, target):
            raise ValueError("Cannot seek to representative frame")
        ok, frame = capture.read()
        if not ok or frame is None:
            raise ValueError("Cannot decode representative frame; check --roi-frame-seconds")
        if interactive:
            title = f"ROI: {source.name} (Enter confirms; C cancels)"
            try:
                roi = tuple(int(v) for v in cv2.selectROI(title, frame, showCrosshair=True, fromCenter=False))
            except cv2.error as error:
                raise ValueError("OpenCV GUI unavailable; provide --roi X Y WIDTH HEIGHT") from error
            finally:
                cv2.destroyAllWindows()
        return validate_roi(roi, frame.shape), frame
    finally:
        capture.release()


def detector_with_boxes(detector):
    """Reuse the same prediction, without changing detector.py or running YOLO twice.

    detect_failure omits boxes from its response. Ultralytics retains the Results
    used by that call in model.predictor.results. This evaluator is sequential.
    """
    def detect(frame):
        response, annotated = detector.detect_failure(frame)
        result = detector.model.predictor.results[0]
        boxes = result.boxes.xyxy.cpu().tolist()
        if len(boxes) != len(response["detections"]):
            raise RuntimeError("Detector response and retained YOLO boxes disagree")
        response = dict(response)
        response["detections"] = [dict(d, bbox_xyxy=box)
                                  for d, box in zip(response["detections"], boxes)]
        return response, annotated
    return detect


def roi_inference(frame, detect_failure, roi):
    if roi is None:
        return detect_failure(frame)
    x, y, width, height = validate_roi(roi, frame.shape)
    response, cropped_annotation = detect_failure(frame[y:y + height, x:x + width].copy())
    response = dict(response)
    translated = []
    for detection in response["detections"]:
        detection = dict(detection)
        if "bbox_xyxy" in detection:
            x1, y1, x2, y2 = detection["bbox_xyxy"]
            detection["bbox_roi_xyxy"] = [x1, y1, x2, y2]
            detection["bbox_xyxy"] = [x1 + x, y1 + y, x2 + x, y2 + y]
        translated.append(detection)
    response["detections"] = translated
    # Pasting the annotated crop at its original origin translates rendered boxes
    # as well as preserving the surrounding scene for human validation.
    annotated = frame.copy()
    annotated[y:y + height, x:x + width] = cropped_annotation
    return response, draw_roi(annotated, roi)


def sample_index(sample: int, fps: float) -> int:
    # First frame at/after each 2-second target, without cumulative rounding drift.
    return math.ceil(sample * 2.0 * fps - 1e-9)


def load_manifest() -> dict:
    path = ROOT / "test_videos_manifest.csv"
    if not path.exists():
        return {}
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return {row["output_filename"]: row for row in csv.DictReader(handle)}
    except (OSError, KeyError, csv.Error) as error:
        print(f"Warning: cannot read manifest: {error}", file=sys.stderr)
        return {}


def timing_context(metadata: dict, timestamp: float) -> dict:
    context = {
        "source_url": metadata.get("source_url", ""),
        "failure_category": metadata.get("failure_category", ""),
        "source_failure_onset_seconds": metadata.get("failure_onset_seconds", ""),
        "manifest_clip_start_seconds": metadata.get("clip_start_seconds", ""),
    }
    try:
        start = float(metadata["clip_start_seconds"])
        onset = float(metadata["failure_onset_seconds"])
        if math.isfinite(start) and math.isfinite(onset):
            context.update(source_timestamp_seconds=round(start + timestamp, 6),
                           clip_failure_onset_seconds=onset - start)
    except (KeyError, ValueError, TypeError):
        pass
    return context


def evaluate(source: Path, destination: Path, detect_failure, metadata: dict,
             roi=None, preview_roi=None, save_previews=False) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    summary = dict(video=str(source), frames_analyzed=0, spaghetti_detections=0,
                   maximum_confidence=0.0, first_spaghetti_clip_seconds=None,
                   average_inference_ms=None, model_errors=0, decode_errors=0,
                   screenshot_errors=0, status="ok", manifest=metadata, roi_xywh=roi,
                   bbox_coordinate_system="full-frame pixels, xyxy")
    elapsed = 0.0
    attempts = 0
    capture = cv2.VideoCapture(str(source))
    csv_path = destination / "frames.csv"
    try:
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            if not capture.isOpened():
                raise ValueError("Cannot open video")
            fps = capture.get(cv2.CAP_PROP_FPS)
            if not math.isfinite(fps) or fps <= 0:
                raise ValueError(f"Invalid FPS ({fps}); cannot assign reliable timestamps")
            count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
            count = int(count) if math.isfinite(count) and count > 0 else None
            summary.update(fps=fps, reported_frame_count=count)
            frame_index, sample, next_index = 0, 0, 0
            while True:
                try:
                    ok, frame = capture.read()
                except cv2.error as error:
                    ok, frame = False, None
                    summary["decode_error"] = str(error)
                if not ok or frame is None or frame.size == 0:
                    # Do not keep retrying a broken decoder or invent negative detections.
                    if count is not None and frame_index < count or "decode_error" in summary:
                        summary["decode_errors"] += 1
                        summary["status"] = "partial"
                        writer.writerow(dict(video=source.name, frame_index=frame_index,
                                             clip_timestamp_seconds=frame_index / fps,
                                             status="decode_error",
                                             error="Decoding stopped before expected EOF",
                                             **timing_context(metadata, frame_index / fps)))
                    elif count is None:
                        summary["end_note"] = "Decoder stopped; unknown frame count prevents distinguishing EOF from corruption"
                    break
                if frame_index >= next_index:
                    if roi is not None:
                        validate_roi(roi, frame.shape)
                    timestamp = frame_index / fps
                    row = dict(video=source.name, frame_index=frame_index,
                               clip_timestamp_seconds=round(timestamp, 6), status="ok",
                               roi_xywh=json.dumps(roi) if roi is not None else "",
                               **timing_context(metadata, timestamp))
                    started = time.perf_counter()
                    attempts += 1
                    try:
                        response, annotated = roi_inference(frame, detect_failure, roi)
                        inference_ms = (time.perf_counter() - started) * 1000
                        detections = response["detections"]
                        categories = sorted({d["type"] for d in detections})
                        confidence = max((float(d["confidence"]) for d in detections
                                          if d["type"].lower() == "spaghetti"), default=0.0)
                        spaghetti = any(d["type"].lower() == "spaghetti" for d in detections)
                        row.update(spaghetti_detected=spaghetti,
                                   highest_spaghetti_confidence=confidence,
                                   predicted_categories=json.dumps(categories),
                                   detections_json=json.dumps(detections))
                    except Exception as error:
                        inference_ms = (time.perf_counter() - started) * 1000
                        row.update(status="model_error", error=str(error))
                        summary["model_errors"] += 1
                        summary["status"] = "partial"
                    else:
                        annotated = draw_roi(annotated, preview_roi)
                        if save_previews:
                            preview_path = destination / f"preview_frame_{frame_index:08d}_{timestamp:.3f}s.jpg"
                            try:
                                if not cv2.imwrite(str(preview_path), annotated):
                                    raise OSError("Image encoder returned false")
                                row["preview"] = preview_path.name
                            except Exception as error:
                                row.update(status="screenshot_error", error=str(error))
                                summary["screenshot_errors"] += 1
                                summary["status"] = "partial"
                        summary["frames_analyzed"] += 1
                        summary["maximum_confidence"] = max(summary["maximum_confidence"], confidence)
                        if spaghetti:
                            summary["spaghetti_detections"] += 1
                            if summary["first_spaghetti_clip_seconds"] is None:
                                summary["first_spaghetti_clip_seconds"] = timestamp
                            screenshot = destination / f"spaghetti_frame_{frame_index:08d}_{timestamp:.3f}s.jpg"
                            try:
                                if not cv2.imwrite(str(screenshot), annotated):
                                    raise OSError("Image encoder returned false")
                                row["screenshot"] = screenshot.name
                            except Exception as error:
                                row.update(status="screenshot_error", error=str(error))
                                summary["screenshot_errors"] += 1
                                summary["status"] = "partial"
                    elapsed += inference_ms
                    row["inference_ms"] = round(inference_ms, 3)
                    writer.writerow(row)
                    handle.flush()
                    sample += 1
                    next_index = max(frame_index + 1, sample_index(sample, fps))
                frame_index += 1
    except Exception as error:
        summary.update(status="error", error=str(error))
    finally:
        capture.release()
    summary["inference_attempts"] = attempts
    summary["average_inference_ms"] = elapsed / attempts if attempts else None
    summary["timing_note"] = "detect_failure plus ROI/box adaptation and annotation; includes failed attempts and first-call warmup; excludes decode and file writes"
    (destination / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    first = summary["first_spaghetti_clip_seconds"]
    average = summary["average_inference_ms"]
    print(f"{source.name}: {summary['frames_analyzed']} frames analyzed, "
          f"{summary['spaghetti_detections']} spaghetti detections, "
          f"max confidence {summary['maximum_confidence']:.4f}, "
          f"first detection {f'{first:.3f}s (clip)' if first is not None else 'none'}, "
          f"average inference {f'{average:.2f} ms' if average is not None else 'N/A'}, "
          f"status {summary['status']}")
    if summary.get("error"):
        print(summary["error"], file=sys.stderr)
    print(f"Results: {destination}")
    return summary


def compare_results(destination, baseline, cropped):
    def read_rows(mode):
        with (destination / mode / "frames.csv").open(newline="", encoding="utf-8") as handle:
            return {r["frame_index"]: r for r in csv.DictReader(handle)}
    full, roi = read_rows("full_frame"), read_rows("roi")
    counts = {"both_positive": 0, "full_only_positive": 0,
              "roi_only_positive": 0, "both_negative": 0, "unpaired_or_error": 0}
    rows = []
    for index in sorted(full.keys() | roi.keys(), key=int):
        before, after = full.get(index, {}), roi.get(index, {})
        b, a = before.get("spaghetti_detected"), after.get("spaghetti_detected")
        if b not in ("True", "False") or a not in ("True", "False"):
            outcome = "unpaired_or_error"
        elif b == "True":
            outcome = "both_positive" if a == "True" else "full_only_positive"
        else:
            outcome = "roi_only_positive" if a == "True" else "both_negative"
        counts[outcome] += 1
        rows.append(dict(frame_index=index,
                         clip_timestamp_seconds=before.get("clip_timestamp_seconds", after.get("clip_timestamp_seconds")),
                         full_spaghetti=b, roi_spaghetti=a, outcome=outcome,
                         full_confidence=before.get("highest_spaghetti_confidence", ""),
                         roi_confidence=after.get("highest_spaghetti_confidence", ""),
                         full_preview=before.get("preview", ""), roi_preview=after.get("preview", ""),
                         validation_label="unreviewed"))
    with (destination / "comparison.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["frame_index", "outcome"])
        writer.writeheader()
        writer.writerows(rows)
    report = dict(full_frame=baseline, roi=cropped, paired_counts=counts,
                  interpretation="Prediction changes only, not accuracy. Review preserved positive and negative previews; bed-adhesion onset is not spaghetti ground truth.")
    (destination / "comparison.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Comparison: {counts}. These counts do not establish false positives or accuracy.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--source", type=Path, help="Path to a prerecorded video")
    group.add_argument("--all", action="store_true", help="Evaluate all MP4s in vision/test_videos")
    roi_group = parser.add_mutually_exclusive_group()
    roi_group.add_argument("--roi", nargs=4, type=int, metavar=("X", "Y", "WIDTH", "HEIGHT"),
                           help="Fixed ROI in full-frame pixels; same coordinates for each --all video")
    roi_group.add_argument("--select-roi", action="store_true", help="Select one ROI per video using OpenCV")
    parser.add_argument("--roi-frame-seconds", type=float, default=0.0,
                        help="Clip-relative representative frame time for ROI preview/selection")
    parser.add_argument("--compare", action="store_true", help="Run full-frame and ROI modes; retain all sampled previews")
    args = parser.parse_args()
    if args.compare and not (args.roi or args.select_roi):
        parser.error("--compare requires --roi or --select-roi")
    if not math.isfinite(args.roi_frame_seconds) or args.roi_frame_seconds < 0:
        parser.error("--roi-frame-seconds must be finite and nonnegative")
    sources = (sorted(p for p in (ROOT / "test_videos").glob("*")
                      if p.is_file() and p.suffix.lower() == ".mp4")
               if args.all else [args.source.resolve()])
    if not sources or any(not p.is_file() for p in sources):
        print("No videos found, or source is not a file", file=sys.stderr)
        return 2
    try:
        import detector
        detect_failure = detector_with_boxes(detector)
    except Exception as error:
        print(f"Cannot load detector/model: {error}. Use the project's Python environment.", file=sys.stderr)
        return 2
    manifest = load_manifest()
    output = ROOT / "results" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    print("Timestamps are clip-relative. Bed-adhesion annotations are not spaghetti ground truth; no missed-bed-adhesion metric is computed.")
    summaries = []
    for source in sources:
        destination = output / source.stem
        roi = None
        try:
            if args.roi or args.select_roi:
                roi, representative = select_video_roi(source, args.roi, args.select_roi, args.roi_frame_seconds)
                destination.mkdir(parents=True, exist_ok=True)
                if not cv2.imwrite(str(destination / "roi_selection.jpg"), draw_roi(representative, roi)):
                    raise OSError("Cannot save ROI selection preview")
            metadata = manifest.get(source.name, {})
            if args.compare:
                full = evaluate(source, destination / "full_frame", detect_failure, metadata,
                                preview_roi=roi, save_previews=True)
                cropped = evaluate(source, destination / "roi", detect_failure, metadata,
                                   roi=roi, save_previews=True)
                compare_results(destination, full, cropped)
                summaries.extend([full, cropped])
            else:
                summaries.append(evaluate(source, destination, detect_failure, metadata, roi=roi))
        except (ValueError, OSError, cv2.error) as error:
            print(f"{source.name}: {error}", file=sys.stderr)
            summaries.append({"status": "error"})
    return 0 if all(s["status"] == "ok" for s in summaries) else 1


if __name__ == "__main__":
    raise SystemExit(main())

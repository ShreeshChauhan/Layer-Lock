"""Evaluate every local MP4 with per-video reviewed ROIs and consolidate results.

Reuses evaluate_videos and the unchanged detector. No accuracy labels are inferred.
Run: .venv/Scripts/python.exe vision/evaluate_dataset.py
Use --output vision/results/<run> --resume to add newly downloaded videos.
"""
import argparse
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys

import cv2
import numpy as np

import evaluate_videos as ev

ROOT = Path(__file__).resolve().parent


def prepare_reviews():
    destination = ROOT / 'results' / 'dataset_review'
    destination.mkdir(parents=True, exist_ok=True)
    for source in sorted((ROOT / 'test_videos').glob('*.mp4')):
        target = destination / (source.stem + '.jpg')
        if target.exists():
            continue
        capture = cv2.VideoCapture(str(source))
        tiles = []
        try:
            fps = capture.get(cv2.CAP_PROP_FPS)
            for seconds in [0, 20, 40, 58]:
                capture.set(cv2.CAP_PROP_POS_FRAMES, round(seconds * fps))
                ok, frame = capture.read()
                if not ok:
                    break
                height, width = frame.shape[:2]
                tile = cv2.resize(frame, (480, 360))
                cv2.putText(tile, f'{seconds}s {width}x{height}', (8,24), 0, .65, (255,255,255), 2)
                tiles.append(tile)
        finally:
            capture.release()
        if len(tiles) == 4:
            cv2.imwrite(str(target), np.vstack([np.hstack(tiles[:2]), np.hstack(tiles[2:])]))
            print(target.name)


def write_csv(path, rows, fields=None):
    if not rows and not fields:
        return
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def consolidate(output, manifest, rois):
    frames, summaries = [], []
    review_path = ROOT / 'dataset_visual_review.json'
    reviews = json.loads(review_path.read_text()) if review_path.exists() else []
    review_by_key = {(r['video'],r['mode'],float(r['clip_seconds'])):r for r in reviews}
    with (ROOT / 'dataset_sequences.csv').open(newline='', encoding='utf-8-sig') as handle:
        catalog = list(csv.DictReader(handle))
    by_url = {m['source_url']: m for m in manifest.values()}
    inventory = []
    for item in catalog:
        m = by_url.get(item['video_url'], {})
        exists = bool(m) and (ROOT / 'test_videos' / m['output_filename']).is_file()
        inventory.append(dict(sequence=item['sequence'], source_url=item['video_url'],
                              source_onset_seconds=item['onset_frame'], available=exists,
                              output_filename=m.get('output_filename', ''),
                              download_status=m.get('status', 'not_attempted'),
                              download_error=m.get('error', '')))
    write_csv(output / 'inventory.csv', inventory)
    representatives = output / 'representatives'
    representatives.mkdir(exist_ok=True)
    for video in sorted((ROOT / 'test_videos').glob('*')):
        if video.suffix.lower() != '.mp4' or not video.is_file():
            continue
        metadata = manifest.get(video.name, {})
        label = metadata.get('dataset_label', video.stem)
        onset = metadata.get('onset_in_clip_seconds')
        try:
            onset = float(onset)
        except (TypeError, ValueError):
            onset = None
        for mode in ['full_frame', 'roi']:
            folder = output / video.stem / mode
            summary_file = folder / 'summary.json'
            if not summary_file.exists():
                summaries.append(dict(video=label, mode=mode, status='not_evaluated',
                                      frames_analyzed=0, before_frames=0, after_frames=0,
                                      spaghetti_frames='', before_positive='', after_positive='',
                                      max_confidence='', first_clip_seconds='', first_source_seconds='',
                                      average_inference_ms='', source_onset_seconds=metadata.get('failure_onset_seconds',''),
                                      clip_onset_seconds=onset, roi_xywh='', roi_review=rois.get(label,{}).get('review','No reviewed ROI'),
                                      representative='', validation='not_evaluated'))
                continue
            summary = json.loads(summary_file.read_text())
            with (folder / 'frames.csv').open(newline='', encoding='utf-8') as handle:
                rows = list(csv.DictReader(handle))
            valid = [r for r in rows if r['spaghetti_detected'] in ('True', 'False')]
            positive = [r for r in valid if r['spaghetti_detected'] == 'True']
            before = [r for r in valid if onset is not None and float(r['clip_timestamp_seconds']) < onset]
            after = [r for r in valid if onset is not None and float(r['clip_timestamp_seconds']) >= onset]
            for row in rows:
                timestamp = float(row['clip_timestamp_seconds'])
                review = review_by_key.get((label,mode,timestamp),{})
                frames.append(dict(dataset_label=label, mode=mode,
                                   onset_phase=('unknown' if onset is None else 'before' if timestamp < onset else 'at_or_after'),
                                   validation_label='unreviewed', human_ground_truth='',
                                   visual_assessment=review.get('assessment','uncertain_unreviewed'),
                                   review_note=review.get('note',''), reviewer_type='assistant_visual_review' if review else '',
                                   result_directory=str(folder.relative_to(output)), **row))
            best = max(positive, key=lambda r: float(r['highest_spaghetti_confidence']), default=None)
            representative = ''
            if best and best['screenshot']:
                target = representatives / f'{label}_{mode}_{best["clip_timestamp_seconds"]}s.jpg'
                shutil.copyfile(folder / best['screenshot'], target)
                representative = str(target.relative_to(output))
            first = positive[0] if positive else {}
            summaries.append(dict(video=label, mode=mode, status=summary['status'],
                                  frames_analyzed=summary['frames_analyzed'], before_frames=len(before), after_frames=len(after),
                                  spaghetti_frames=len(positive), before_positive=sum(r['spaghetti_detected']=='True' for r in before),
                                  after_positive=sum(r['spaghetti_detected']=='True' for r in after),
                                  max_confidence=summary['maximum_confidence'], first_clip_seconds=first.get('clip_timestamp_seconds',''),
                                  first_source_seconds=first.get('source_timestamp_seconds',''),
                                  average_inference_ms=summary['average_inference_ms'],
                                  source_onset_seconds=metadata.get('failure_onset_seconds',''), clip_onset_seconds=onset,
                                  roi_xywh=json.dumps(summary.get('roi_xywh')),
                                  roi_review=rois.get(label,{}).get('review','No reviewed ROI'),
                                  representative=representative, validation='unreviewed_no_human_spaghetti_ground_truth'))
    if summaries:
        for missing in inventory:
            if missing['available']:
                continue
            for mode in ['full_frame','roi']:
                row = dict.fromkeys(summaries[0], '')
                row.update(video=missing['sequence'],mode=mode,status='unavailable',frames_analyzed=0,
                           source_onset_seconds=missing['source_onset_seconds'],validation='not_evaluated')
                summaries.append(row)
    write_csv(output / 'consolidated_frames.csv', frames)
    write_csv(output / 'consolidated_evaluation.csv', summaries)
    report = ['# LayerLock dataset evaluation', '',
              f'Catalog: {len(catalog)} sequences; local catalog clips: {sum(r["available"] for r in inventory)}. '
              f'Evaluated local MP4s: {len({r["video"] for r in summaries if r["status"] in ("ok","partial","error")})}.', '',
              'Initial inventory was five MP4s with 25 catalog clips missing; see vision/dataset_initial_inventory.csv for the exact list. '
              'Additional clips were downloaded through the public-only existing downloader, without access-restriction workarounds.', '',
              'Every sample is separated by two seconds of video time. Clips retain source onset timing. '
              'Before means strictly before the annotated bed-adhesion onset; after includes onset. '
              'Annotations do not label spaghetti. Counts are descriptive, not accuracy metrics.', '',
              '| Video | Mode | Status | Frames | Positive/observed before; at/after | Max confidence | First clip s | Mean ms |',
              '|---|---|---|---:|---|---:|---:|---:|']
    for r in summaries:
        avg = f'{r["average_inference_ms"]:.2f}' if isinstance(r['average_inference_ms'], (int,float)) else ''
        report.append(f'| {r["video"]} | {r["mode"]} | {r["status"]} | {r["frames_analyzed"]} | '
                      f'{r["before_positive"]}/{r["before_frames"]}; {r["after_positive"]}/{r["after_frames"]} | {r["max_confidence"]} | {r["first_clip_seconds"]} | {avg} |')
    report += ['', '## Missing catalog clips', '']
    if all(r['available'] for r in inventory):
        report.append('None: every catalog source has a local clip.')
    report += [f'- {r["sequence"]}: {r["download_status"]}. See inventory.csv for exact error.' for r in inventory if not r['available']]
    report += ['', '## ROI decisions', '']
    report += [f'- **{label}**: `{item["roi"]}` (x,y,width,height). {item["review"]}' for label,item in rois.items()]
    totals = []
    for mode in ['full_frame','roi']:
        records = [r for r in summaries if r['mode']==mode and r['status'] in ('ok','partial')]
        measured = [float(r['inference_ms']) for r in frames if r['mode']==mode and r['inference_ms']]
        totals.append(dict(mode=mode,videos=len(records),frames=sum(r['frames_analyzed'] for r in records),
                           positive_frames=sum(r['spaghetti_frames'] for r in records),
                           before_frames=sum(r['before_frames'] for r in records),
                           after_frames=sum(r['after_frames'] for r in records),
                           before_positive=sum(r['before_positive'] for r in records),
                           after_positive=sum(r['after_positive'] for r in records),
                           mean_inference_ms=sum(measured)/len(measured) if measured else None))
    write_csv(output/'totals.csv',totals)
    report += ['', '## Aggregate descriptive counts', '',
               '| Mode | Videos | Frames | Spaghetti-positive frames | Before positive/observed | At/after positive/observed | Mean call ms |',
               '|---|---:|---:|---:|---:|---:|---:|']
    report += [f'| {r["mode"]} | {r["videos"]} | {r["frames"]} | {r["positive_frames"]} | {r["before_positive"]}/{r["before_frames"]} | {r["after_positive"]}/{r["after_frames"]} | {round(r["mean_inference_ms"],2) if r["mean_inference_ms"] is not None else "N/A"} |' for r in totals]
    report += ['', '## Interpretation and limitations', '',
               '- Correct spaghetti detections: require verified spaghetti ground truth; none assigned automatically.',
               '- False spaghetti detections: representative logo/hardware/background boxes may be marked suspected by visual review; this is not a human-reviewed benchmark.',
               '- Bed-adhesion failures: present by dataset annotation; the current spaghetti/stringing/zits classes do not provide an explicit detachment or displacement decision. No spaghetti response is not a missed spaghetti event.',
               '- Uncertain: all predictions remain unreviewed until a qualified reviewer labels visible filament and occluded areas. Preserve positive and negative samples.',
               '- Precision and recall are not calculated: no suitable human-reviewed spaghetti labels were supplied. Post-onset detections are not automatically true positives.',
               '- ROI selection used representative frames from these same clips; this is exploratory and is not held-out validation. Cropping changes scale/context and may exclude genuine debris.',
               '- Only 60 seconds around each onset are evaluated, not the entire original recording. This cannot establish whole-print reliability or late spaghetti recall.',
               '- Calls include plotting, coordinate adaptation and initial warmup. Full-frame always runs first; some evaluations overlapped download/transcoding activity. Timings are descriptive, not controlled benchmarks.',
               '', '## Recommendations', '',
               'Use printer-specific bed/object masks and hard-negative training examples of logos, cables, fans, reflections and background clutter. '
               'Validate thresholds and temporal confirmation on separately labeled positive and negative sequences; repeated logos can also persist, so temporal filtering alone is insufficient. '
               'Retain unfiltered outputs and full-frame context during validation, and label both model-positive and model-negative frames to avoid selection bias.', '',
               'A separate bed-detachment/displacement capability is warranted for early adhesion failure. Track a segmented printed object relative to the bed, '
               'compensate for camera/bed motion, and suppress print-head occlusions. Evaluate change-point latency and false alarms against the provided onset annotations. '
               'This can be a tracking/segmentation branch alongside YOLO rather than necessarily a second YOLO model; current appearance classes alone are insufficient.', '',
               'Source: https://github.com/EmptyDeck/3DPrint-Failure-Video-Dataset (CC BY-NC 4.0 research use per README). '
               'Retain source attribution with derivative clips; commercial usage requires separate permission.', '',
               'Artifacts: consolidated_frames.csv, consolidated_evaluation.csv, inventory.csv, per-video comparisons, representatives/, '
               'and all sampled annotated previews. See visual_review.md when present for specific inspected examples.']
    (output / 'REPORT.md').write_text('\n'.join(report)+'\n', encoding='utf-8')
    review_report = ['# Representative visual review', '',
                     'These are assistant visual observations, not human-reviewed ground-truth labels. '
                     'No precision/recall is computed from them. Mixed or occluded predictions remain uncertain.', '']
    for r in reviews:
        candidates = [f for f in frames if f['dataset_label']==r['video'] and f['mode']==r['mode']
                      and float(f['clip_timestamp_seconds'])==float(r['clip_seconds'])]
        if not candidates:
            continue
        frame = candidates[0]
        relative = (Path(frame['result_directory']) / (frame['preview'] or frame['screenshot'])).as_posix()
        review_report += [f'## {r["video"]}, {r["mode"]}, clip {r["clip_seconds"]} s', '',
                          f'**{r["assessment"]}**: {r["note"]}', '', f'![Reviewed frame]({relative})', '']
    (output / 'visual_review.md').write_text('\n'.join(review_report), encoding='utf-8')
    print(f'Consolidated report: {output / "REPORT.md"}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'results' / datetime.now().strftime('dataset_%Y%m%d_%H%M%S'))
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--report-only', action='store_true')
    parser.add_argument('--prepare-reviews', action='store_true', help='Create four-frame contact sheets without running inference')
    args = parser.parse_args()
    if args.prepare_reviews:
        prepare_reviews()
        return
    output = args.output.resolve()
    if not output.is_relative_to(ROOT):
        parser.error('Keep output inside vision/')
    output.mkdir(parents=True, exist_ok=True)
    manifest = ev.load_manifest()
    rois = json.loads((ROOT / 'dataset_rois.json').read_text())
    if args.report_only:
        consolidate(output, manifest, rois)
        return
    import detector
    detect = ev.detector_with_boxes(detector)
    identity = dict(model_sha256=hashlib.sha256((ROOT/'models/layerlock.pt').read_bytes()).hexdigest(),
                    sampling_seconds=2, thresholds='unchanged detector.py conf=0.25',
                    python=sys.version,opencv=cv2.__version__,class_names=detector.model.names,
                    device=str(next(detector.model.model.parameters()).device))
    (output / 'run_metadata.json').write_text(json.dumps(identity,indent=2),encoding='utf-8')
    for source in sorted((ROOT / 'test_videos').glob('*')):
        if not source.is_file() or source.suffix.lower() != '.mp4':
            continue
        m = manifest.get(source.name,{})
        label = m.get('dataset_label',source.stem)
        folder = output / source.stem
        roi = rois.get(label,{}).get('roi')
        if roi is not None:
            roi, representative = ev.select_video_roi(source,roi)
            folder.mkdir(parents=True,exist_ok=True)
            cv2.imwrite(str(folder/'roi_selection.jpg'),ev.draw_roi(representative,roi))
        results = {}
        for mode in ['full_frame','roi']:
            if mode == 'roi' and roi is None:
                print(f'{label}: no reviewed ROI; retaining full-frame evaluation only',flush=True)
                continue
            summary_path = folder / mode / 'summary.json'
            if args.resume and summary_path.exists():
                old = json.loads(summary_path.read_text())
                if old['status']=='ok' and old.get('roi_xywh') == (list(roi) if mode=='roi' else None):
                    results[mode] = old
                    continue
            results[mode] = ev.evaluate(source,folder/mode,detect,m,
                                       roi=roi if mode=='roi' else None,
                                       preview_roi=roi if mode=='full_frame' else None,save_previews=True)
        if len(results)==2:
            ev.compare_results(folder,results['full_frame'],results['roi'])
    consolidate(output,manifest,rois)


if __name__ == '__main__':
    main()

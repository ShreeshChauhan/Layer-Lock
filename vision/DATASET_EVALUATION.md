# Full dataset workflow

The original downloader selected only five entries. `dataset_sequences.csv` is a
snapshot of the upstream 30-row metadata retrieved on October 24, 2026:
https://raw.githubusercontent.com/EmptyDeck/3DPrint-Failure-Video-Dataset/master/metadata/sequences.csv

The upstream README licenses metadata and hosted research videos under CC BY-NC
4.0. Attribution: EmptyDeck, Bed-Adhesion Failure-Onset Dataset for FDM 3D Printing.
Commercial use requires separate permission. The downloader uses public access
without cookies, authentication, geo bypass, or DRM workarounds.

```powershell
# Ensure ffmpeg and ffprobe are on this terminal's PATH first.
.venv/Scripts/python.exe vision/download_test_videos.py --all

# Review four frames per clip and document per-video rectangles.
.venv/Scripts/python.exe vision/evaluate_dataset.py --prepare-reviews

# Run all available MP4s, reusing the existing evaluator and detector.
.venv/Scripts/python.exe vision/evaluate_dataset.py --output vision/results/dataset_all --resume

# Refresh reports after adding visual review notes without re-running YOLO.
.venv/Scripts/python.exe vision/evaluate_dataset.py --output vision/results/dataset_all --report-only
```

Without `--all`, the downloader still selects the initial five. Both modes retain
other existing manifest rows. `--all --plan` adds missing catalog entries without
downloading or replacing existing metadata. Existing clips are decoded and checked
before reuse. Upstream metadata names occasionally differ from display labels; the
original five retain their filenames, and other filenames use metadata names.

`dataset_rois.json` documents reviewed rectangles in original image pixels, keyed
by dataset label. ROIs are intentionally different across clips, including changes
within one printer setup when object height or motion differs. A video without a
reviewed ROI still receives full-frame inference and an explicit `not_evaluated`
ROI result rather than a blindly inherited YellowEarly rectangle. Add a reviewed
ROI and resume to evaluate it. `--resume` skips successful modes with matching ROI;
use a new output directory after changing the model, evaluator, or source clips.

The original `evaluate_videos.py` CLI remains available, including interactive
`--select-roi`, fixed `--roi`, and `--compare`. No changes to detector.py, capture.py,
inference.py, weights, or model thresholds are required.

Outputs under `vision/results/dataset_all/`:

- `REPORT.md`: descriptive results, missing videos, ROI rationale and recommendations.
- `consolidated_evaluation.csv`: per-video/mode counts, before/after-onset counts,
  confidence, first timestamps, inference timings and ROI notes. Unavailable videos
  are explicit rows, never zero-detection successful evaluations.
- `consolidated_frames.csv`: every sampled frame, categories, confidence, boxes,
  timing, source onset, phase, and review metadata.
- `inventory.csv`: all 30 sources, availability and downloader errors.
- `visual_review.md`: specific visually inspected examples with screenshots.
- `representatives/`: strongest spaghetti prediction per video/mode where present.
- Per-video folders: comparisons, CSVs, summaries, every sampled preview and every
  positive screenshot. Initial exploratory result folders remain untouched.

`dataset_visual_review.json` stores **assistant visual observations**, not human
ground truth. Assessments distinguish `correct_spaghetti_candidate`,
`suspected_false_spaghetti`, and `uncertain_requires_manual_review`. The CSV keeps
human_ground_truth empty and validation_label unreviewed. No precision or recall
is inferred from those observations, file names, or bed-adhesion annotations.
Human review should label positive and negative frames, record occlusions, and
verify the class definition and coordinates before computing detection metrics.

Before/after splitting uses original clip timestamps and manifest onset offset.
The intervals are [start,onset) and [onset,end). No post-onset spaghetti prediction
is automatically correct, and a missing prediction cannot be called a missed
spaghetti event merely because adhesion failed. The current model has no explicit
bed-detachment or displacement class.

These are 60-second onset clips rather than full-length print runs. Four-frame
ROI inspection does not guarantee coverage of all motion or flying debris. ROIs
were selected using the same evaluation clips, so this is exploratory analysis,
not a held-out accuracy estimate. Frame-level inference times include annotation,
ROI adaptation and warmup; they are not a controlled speed benchmark.

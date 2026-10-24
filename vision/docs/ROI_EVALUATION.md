# ROI evaluation

Run from the repository root using the project's environment:

```powershell
# Fixed pixel rectangle: x, y, width, height (not x1, y1, x2, y2).
.venv/Scripts/python.exe vision/src/evaluate_videos.py --source vision/datasets/videos/bed_adhesion_YellowEarly_Y8H8eqtemuk_onset_120s.mp4 --roi 280 590 540 130 --compare

# Select a rectangle on a representative frame at clip second 20.
.venv/Scripts/python.exe vision/src/evaluate_videos.py --source vision/datasets/videos/bed_adhesion_YellowEarly_Y8H8eqtemuk_onset_120s.mp4 --select-roi --roi-frame-seconds 20 --compare

# Original full-frame behavior; no ROI.
.venv/Scripts/python.exe vision/src/evaluate_videos.py --all
```

OpenCV selection requires a desktop GUI. Drag a rectangle and press Enter/Space
to confirm. Canceling or selecting an empty/out-of-bounds rectangle rejects that
video. In headless environments, use coordinates. With `--all --select-roi`, select
one rectangle per video. With `--all --roi ...`, the same coordinates are validated
separately against each video's dimensions. The ROI never follows the print head
or changes during a video evaluation. Choose a rectangle covering the object's
entire expected movement and possible failure debris, not just its first-frame
silhouette. Representative frames and cropping do not change sampling timestamps.

Each invocation creates a new directory under `vision/results/`. CSV columns from
the original evaluator are retained. `roi_xywh` describes the inference crop;
`detections_json` now includes full-frame pixel `bbox_xyxy` coordinates. Cropped
predictions additionally retain `bbox_roi_xyxy` coordinates. Crop annotations are
placed back at their full-frame origin, with the ROI drawn in green. `roi_selection.jpg`
records the representative frame and selected rectangle.

The original `detect_failure` is called exactly once per analyzed frame/mode.
Its response omits boxes, so a local adapter reads the corresponding retained
Ultralytics `model.predictor.results[0]` after that call. It does not change model
weights, inference thresholds, detector code, or run a second prediction. This
adapter assumes sequential evaluation and the current Ultralytics Results API.

Comparison mode creates `full_frame/` and `roi/`, each containing `frames.csv`,
`summary.json`, positive screenshots, and **all** sampled annotated previews.
Baseline previews show the candidate ROI, but baseline inference receives the
whole frame. `comparison.csv` aligns outcomes by original frame index and leaves
validation labels `unreviewed`; `comparison.json` retains both summaries and paired
counts. Model failures are unpaired/error outcomes, never negative predictions.
Timing includes annotation and ROI/box adaptation, and the first call's warmup;
it is not a controlled performance benchmark.

## YellowEarly run

Results directory (from repository root): `vision/results/20261024_022142_762322/bed_adhesion_YellowEarly_Y8H8eqtemuk_onset_120s/`.
The chosen rectangle `(280, 590, 540, 130)` covers the lower print/bed area in the
960x720 video. The moving print head occludes much of the object. This is a test
ROI, not a general-purpose validated setting for other videos.

| Metric | Full frame | ROI |
| --- | ---: | ---: |
| Frames analyzed | 30 | 30 |
| Spaghetti-positive frames | 12 | 0 |
| Maximum confidence | 0.8563 | 0 |
| First positive (clip seconds) | 4 | None |
| Average call time (ms) | 198.97 | 34.85 |
| Model/decode/screenshot errors | 0 | 0 |

Sampling is 0, 2, ..., 58 clip seconds. The source offset is 100 seconds, and
annotated **bed-adhesion** onset is source second 120 / clip second 20. Neither
that annotation nor an early model positive establishes spaghetti ground truth.

Visual inspection of the preserved baseline-positive contact sheet shows detections
on the logo and background objects. For example, second 4 boxes the Ender logo;
second 44 boxes objects behind the printer rather than the green print. These are
consistent with the reported nuisance detections. All 12 positive frames, including
their full-resolution boxes, remain available in `full_frame/`; all 30 ROI previews
remain available for checking excluded content. `baseline_positives.jpg` is a contact
sheet for review. No automatic accuracy or false-negative rate is assigned.

Zero ROI predictions do not prove better accuracy: cropping removes image context,
changes model input scaling, and may hide actual filament/debris. Validate against
manually confirmed spaghetti-positive videos and inspect both full/ROI views before
adopting this crop. Existing test images and prior result folders are unchanged.

Tests: `.venv/Scripts/python.exe -m unittest discover -s vision/tests -p test_evaluate_videos.py`

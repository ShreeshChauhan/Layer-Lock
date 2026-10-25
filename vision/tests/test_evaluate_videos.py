"""Offline sampling and error handling tests; no model weights needed."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from vision.src import evaluate_videos as evaluator


class Capture:
    def __init__(self, fps=30, count=180, available=None):
        self.fps, self.count = fps, count
        self.available = count if available is None else available
        self.position = 0
        self.released = False

    def isOpened(self):
        return True

    def get(self, prop):
        return self.fps if prop == evaluator.cv2.CAP_PROP_FPS else self.count

    def read(self):
        self.position += 1
        return ((True, np.zeros((8, 8, 3), dtype=np.uint8))
                if self.position <= self.available else (False, None))

    def release(self):
        self.released = True


class EvaluateTests(unittest.TestCase):
    def test_interactive_selection_and_cancellation(self):
        with patch.object(evaluator.cv2, 'VideoCapture', side_effect=lambda _: Capture()), \
             patch.object(evaluator.cv2, 'selectROI', return_value=(1, 2, 3, 4)) as select, \
             patch.object(evaluator.cv2, 'destroyAllWindows'):
            roi, _ = evaluator.select_video_roi(Path('test.mp4'), None, interactive=True)
            self.assertEqual(roi, (1, 2, 3, 4))
            self.assertEqual(select.call_count, 1)
        with patch.object(evaluator.cv2, 'VideoCapture', side_effect=lambda _: Capture()), \
             patch.object(evaluator.cv2, 'selectROI', return_value=(0, 0, 0, 0)), \
             patch.object(evaluator.cv2, 'destroyAllWindows'):
            with self.assertRaises(ValueError):
                evaluator.select_video_roi(Path('test.mp4'), None, interactive=True)

    def test_roi_validation_and_translation(self):
        frame = np.zeros((100, 200, 3), dtype=np.uint8)
        for roi in [(0, 0, 0, 10), (-1, 0, 10, 10), (190, 0, 11, 10), (0, 95, 10, 6)]:
            with self.assertRaises(ValueError):
                evaluator.validate_roi(roi, frame.shape)
        self.assertEqual(evaluator.validate_roi((0, 0, 200, 100), frame.shape), (0, 0, 200, 100))
        def detect(crop):
            self.assertEqual(crop.shape, (30, 40, 3))
            return {'detections': [{'type': 'spaghetti', 'confidence': .9,
                                    'bbox_xyxy': [1, 2, 10, 20]}]}, crop
        response, annotated = evaluator.roi_inference(frame, detect, (50, 40, 40, 30))
        self.assertEqual(response['detections'][0]['bbox_xyxy'], [51, 42, 60, 60])
        self.assertEqual(response['detections'][0]['bbox_roi_xyxy'], [1, 2, 10, 20])
        self.assertEqual(annotated.shape, frame.shape)
        self.assertTrue((frame == 0).all())

    def test_roi_paired_evaluation(self):
        def detect(frame):
            # Known positive in full frame, negative in cropped input.
            detections = [{'type': 'spaghetti', 'confidence': .8}] if frame.shape[1] == 8 else []
            return {'detections': detections}, frame
        with tempfile.TemporaryDirectory(dir=evaluator.ROOT) as folder:
            destination = Path(folder)
            with patch.object(evaluator.cv2, 'VideoCapture', side_effect=lambda _: Capture(count=61)):
                baseline = evaluator.evaluate(Path('test.mp4'), destination / 'full_frame', detect, {}, save_previews=True)
                cropped = evaluator.evaluate(Path('test.mp4'), destination / 'roi', detect, {}, roi=(1, 1, 4, 4), save_previews=True)
            evaluator.compare_results(destination, baseline, cropped)
            report = json.loads((destination / 'comparison.json').read_text())
            self.assertEqual(report['paired_counts']['full_only_positive'], 2)
            self.assertEqual(len(list((destination / 'full_frame').glob('spaghetti*.jpg'))), 2)
            self.assertEqual(len(list((destination / 'roi').glob('preview*.jpg'))), 2)

    def evaluate(self, capture, detector, folder):
        with patch.object(evaluator.cv2, 'VideoCapture', return_value=capture):
            summary = evaluator.evaluate(Path('test.mp4'), Path(folder), detector,
                                         {'clip_start_seconds': '100', 'failure_onset_seconds': '120'})
        with (Path(folder) / 'frames.csv').open(newline='') as handle:
            rows = list(csv.DictReader(handle))
        self.assertTrue(capture.released)
        return summary, rows

    def test_video_clock_and_manifest(self):
        def detect(frame):
            return {'detections': [{'type': 'spaghetti', 'confidence': 0.8},
                                   {'type': 'stringing', 'confidence': 0.5}]}, frame
        with tempfile.TemporaryDirectory(dir=evaluator.ROOT) as folder:
            summary, rows = self.evaluate(Capture(), detect, folder)
            self.assertEqual([int(r['frame_index']) for r in rows], [0, 60, 120])
            self.assertEqual([float(r['clip_timestamp_seconds']) for r in rows], [0, 2, 4])
            self.assertEqual(rows[1]['source_timestamp_seconds'], '102.0')
            self.assertEqual(rows[1]['clip_failure_onset_seconds'], '20.0')
            self.assertEqual(summary['spaghetti_detections'], 3)
            self.assertEqual(len(list(Path(folder).glob('*.jpg'))), 3)
        self.assertEqual(evaluator.sample_index(100, 29.97), 5994)

    def test_model_failure_is_not_negative_prediction(self):
        def broken(frame):
            raise RuntimeError('model unavailable')
        with tempfile.TemporaryDirectory(dir=evaluator.ROOT) as folder:
            summary, rows = self.evaluate(Capture(count=61), broken, folder)
            self.assertEqual(summary['model_errors'], 2)
            self.assertEqual(summary['frames_analyzed'], 0)
            self.assertEqual(rows[0]['spaghetti_detected'], '')

    def test_invalid_fps_and_corruption(self):
        for fps in [0, float('nan'), -1]:
            with tempfile.TemporaryDirectory(dir=evaluator.ROOT) as folder:
                summary, rows = self.evaluate(Capture(fps=fps), None, folder)
                self.assertEqual(summary['status'], 'error')
                self.assertEqual(rows, [])
        with tempfile.TemporaryDirectory(dir=evaluator.ROOT) as folder:
            summary, rows = self.evaluate(Capture(available=1),
                                         lambda frame: ({'detections': []}, frame), folder)
            self.assertEqual(summary['decode_errors'], 1)
            self.assertEqual(rows[-1]['status'], 'decode_error')


if __name__ == '__main__':
    unittest.main()

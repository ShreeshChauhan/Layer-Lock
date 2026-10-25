"""Pi publisher checks without YOLO loading, camera access, or real HTTP calls."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import urllib.error
from unittest.mock import Mock, patch

import numpy as np

from vision.src import pi_camera, pi_inference as pi

ROOT = Path(__file__).resolve().parents[2]


class PiInferenceTests(unittest.TestCase):
    def test_payload_formatter_and_http_contract(self):
        for confidence, expected in [(0, 0), (.6559, 66), (1, 100)]:
            result = {'confidence': confidence, 'failure_type': 'spaghetti'}
            with patch.object(pi, 'create_vision_payload', wraps=pi.create_vision_payload) as formatter, \
                 patch.object(pi.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"armed":false}')) as send:
                self.assertEqual(pi.publish_result(result, 'http://backend.test/', timeout=2), {'armed': False})
            formatter.assert_called_once_with(result)
            request = send.call_args.args[0]
            payload = json.loads(request.data)
            self.assertEqual(request.full_url, 'http://backend.test/live/update')
            self.assertEqual(request.get_method(), 'POST')
            self.assertEqual(payload['camera_confidence'], expected)
            self.assertIs(type(payload['camera_confidence']), int)
            self.assertIn('timestamp', payload)
            self.assertEqual(send.call_args.kwargs['timeout'], 2)

    def test_invalid_confidence_not_published(self):
        with patch.object(pi.urllib.request, 'urlopen') as send:
            for confidence in [-1, 2, float('nan')]:
                with self.assertRaises(ValueError):
                    pi.publish_result({'confidence': confidence}, 'http://backend.test')
            send.assert_not_called()

    def test_environment_defaults_and_cli_overrides(self):
        with patch.dict(os.environ, {'SNAPSHOT_URL': 'http://camera.test/snapshot',
                                    'BACKEND_URL': 'http://backend.test', 'PI_INTERVAL': '4',
                                    'HTTP_TIMEOUT': '2', 'HEADLESS': '1'}):
            args = pi.parse_args([])
            self.assertEqual((args.snapshot_url, args.backend_url, args.interval, args.timeout, args.headless),
                             ('http://camera.test/snapshot', 'http://backend.test', 4, 2, True))
            args = pi.parse_args(['--snapshot-url', 'http://override.test', '--backend-url', 'https://api.test',
                                  '--interval', '1', '--timeout', '3', '--conf', '.6'])
            self.assertEqual((args.snapshot_url, args.backend_url, args.interval, args.timeout, args.conf),
                             ('http://override.test', 'https://api.test', 1, 3, .6))

    def test_invalid_configuration_rejected(self):
        for args in [['--interval', '0'], ['--timeout', 'nan'], ['--conf', 'inf'], ['--conf', '1.1'],
                     ['--snapshot-url', 'file:///frame.jpg'], ['--backend-url', 'not-a-url']]:
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                pi.parse_args(args)
            self.assertEqual(error.exception.code, 2)

    def test_both_cli_entry_points(self):
        for command in [['vision/src/pi_inference.py', '--help'], ['-m', 'vision.src.pi_inference', '--help']]:
            completed = subprocess.run([sys.executable, '-B'] + command, cwd=ROOT,
                                       capture_output=True, text=True, timeout=15)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn('--headless', completed.stdout)

    def run_loop(self, detector=None, camera_effect=None, publish_effect=None, headless=True, iterations=2, gui_error=False):
        frame = np.zeros((8, 8, 3), dtype=np.uint8)
        detector = detector or Mock(return_value=({'confidence': .8}, frame))
        errors = io.StringIO()
        with patch.object(pi, 'get_pi_frame', return_value=frame, side_effect=camera_effect) as camera, \
             patch.object(pi, 'publish_result', side_effect=publish_effect) as publish, \
             patch.object(pi.time, 'sleep', side_effect=[None] * (iterations - 1) + [KeyboardInterrupt]), \
             patch.object(pi.cv2, 'imshow', side_effect=pi.cv2.error('no display') if gui_error else None) as show, \
             patch.object(pi.cv2, 'waitKey', return_value=-1) as wait, \
             patch.object(pi.cv2, 'destroyAllWindows') as close, \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
            pi.monitor(detector, snapshot_url='http://camera.test', backend_url='http://backend.test',
                       timeout=2, interval=1, headless=headless, conf=.6)
        return camera, publish, detector, show, wait, close, errors.getvalue()

    def test_headless_uses_no_gui_and_passes_threshold(self):
        camera, publish, detect, show, wait, close, _ = self.run_loop()
        self.assertEqual(publish.call_count, 2)
        camera.assert_called_with('http://camera.test', timeout=2)
        self.assertEqual(detect.call_args.kwargs['conf'], .6)
        publish.assert_called_with({'confidence': .8}, 'http://backend.test', timeout=2)
        for gui in (show, wait, close):
            gui.assert_not_called()

    def test_backend_failures_do_not_stop_sampling(self):
        for error in [TimeoutError('timeout'), urllib.error.URLError('offline'), ValueError('invalid JSON'),
                      pi.http.client.IncompleteRead(b'partial'),
                      urllib.error.HTTPError('http://backend.test/live/update', 409, 'wrong mode', {}, None),
                      urllib.error.HTTPError('http://backend.test/live/update', 503, 'unavailable', {}, None)]:
            with self.subTest(error=type(error).__name__):
                camera, publish, _, _, _, _, messages = self.run_loop(publish_effect=[error, {}])
                self.assertEqual(camera.call_count, 2)
                self.assertEqual(publish.call_count, 2)
                self.assertIn('Backend', messages)

    def test_camera_and_model_errors_do_not_publish_false_healthy_readings(self):
        frame = np.zeros((8, 8, 3), dtype=np.uint8)
        detect = Mock(side_effect=[RuntimeError('model failed'), ({'confidence': .8}, frame)])
        camera, publish, _, _, _, _, _ = self.run_loop(detector=detect, iterations=3,
                                                      camera_effect=[TimeoutError('camera failed'), frame, frame])
        self.assertEqual(camera.call_count, 3)
        publish.assert_called_once_with({'confidence': .8}, 'http://backend.test', timeout=2)

    def test_preview_failure_falls_back_to_headless(self):
        _, publish, _, show, wait, close, messages = self.run_loop(headless=False, gui_error=True)
        self.assertEqual(publish.call_count, 2)
        show.assert_called_once()
        wait.assert_not_called()
        close.assert_called_once()
        self.assertIn('continuing headless', messages)

    def test_snapshot_timeout_and_decode(self):
        frame = np.zeros((8, 8, 3), dtype=np.uint8)
        ok, encoded = pi_camera.cv2.imencode('.jpg', frame)
        self.assertTrue(ok)
        with patch.object(pi_camera.urllib.request, 'urlopen', return_value=io.BytesIO(encoded.tobytes())) as fetch:
            decoded = pi_camera.get_pi_frame('http://camera.test/snapshot', timeout=2)
        self.assertEqual(decoded.shape, frame.shape)
        self.assertEqual(fetch.call_args.kwargs['timeout'], 2)
        with patch.object(pi_camera.urllib.request, 'urlopen', return_value=io.BytesIO(b'not a JPEG')):
            with self.assertRaises(ValueError):
                pi_camera.get_pi_frame('http://camera.test/snapshot')


if __name__ == '__main__':
    unittest.main()

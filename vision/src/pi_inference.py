"""Publish Raspberry Pi YOLO readings; mode selection and arming stay manual."""
import argparse
import http.client
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

import cv2

if __package__:
    from .pi_camera import get_pi_frame
    from .payload import create_vision_payload
else:
    from pi_camera import get_pi_frame
    from payload import create_vision_payload


def publish_result(result, backend_url, timeout=5):
    """Send a fresh reading only; never change backend mode or arming state."""
    payload = create_vision_payload(result)
    confidence = payload['camera_confidence']
    if type(confidence) is not int or not 0 <= confidence <= 100:
        raise ValueError('Camera confidence must be an integer between 0 and 100')
    request = urllib.request.Request(
        backend_url.rstrip('/') + '/live/update',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'}, method='POST',
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def monitor(detect_failure, *, snapshot_url, backend_url, interval=3,
            timeout=5, headless=False, conf=0.25):
    print('LayerLock Raspberry Pi monitoring started. Mode selection and arming remain manual.')
    print('Press Ctrl+C to exit.' if headless else 'Press Q or Ctrl+C to exit.')
    preview = not headless
    try:
        while True:
            started = time.monotonic()
            annotated_frame = None
            try:
                frame = get_pi_frame(snapshot_url, timeout=timeout)
                result, annotated_frame = detect_failure(frame, conf=conf)
                print(json.dumps(result, indent=2))
            except Exception as error:
                # Do not turn camera/model failure into a fresh zero-confidence reading.
                print(f'Camera/inference error: {error}', file=sys.stderr)
            else:
                try:
                    publish_result(result, backend_url, timeout=timeout)
                except urllib.error.HTTPError as error:
                    if error.code == 409:
                        print('Backend rejected reading (409): select live mode manually in the dashboard. '
                              'No mode change or arming was requested.', file=sys.stderr)
                    else:
                        print(f'Backend rejected reading: HTTP {error.code}', file=sys.stderr)
                    error.close()
                except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException) as error:
                    print(f'Backend update failed: {error}', file=sys.stderr)

            if preview:
                try:
                    if annotated_frame is not None:
                        cv2.imshow('LayerLock Pi Camera', annotated_frame)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
                except cv2.error as error:
                    print(f'Preview unavailable; continuing headless: {error}', file=sys.stderr)
                    preview = False
            time.sleep(max(0, interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        pass
    finally:
        if not headless:
            try:
                cv2.destroyAllWindows()
            except cv2.error:
                pass


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot-url', default=os.getenv('SNAPSHOT_URL', 'http://localhost:8080/?action=snapshot'))
    parser.add_argument('--backend-url', default=os.getenv('BACKEND_URL', 'http://127.0.0.1:8000'),
                        help='Backend base URL; /live/update is appended')
    parser.add_argument('--interval', type=float, default=os.getenv('PI_INTERVAL', '3'), help='Seconds between samples')
    parser.add_argument('--timeout', type=float, default=os.getenv('HTTP_TIMEOUT', '5'), help='Timeout for each HTTP request')
    parser.add_argument('--conf', type=float, default=0.25, help='YOLO confidence threshold (default: 0.25)')
    parser.add_argument('--headless', action='store_true', default=os.getenv('HEADLESS', '0') == '1')
    args = parser.parse_args(argv)
    for name in ('snapshot_url', 'backend_url'):
        try:
            url = urlsplit(getattr(args, name))
            valid = url.scheme in ('http', 'https') and bool(url.hostname)
        except ValueError:
            valid = False
        if not valid:
            parser.error(f'--{name.replace("_", "-")} must be an HTTP(S) URL with a hostname')
    for name in ('interval', 'timeout'):
        value = getattr(args, name)
        if not math.isfinite(value) or value <= 0:
            parser.error(f'--{name} must be finite and greater than zero')
    if not math.isfinite(args.conf) or not 0 <= args.conf <= 1:
        parser.error('--conf must be finite and between 0 and 1')
    return args


def main(argv=None):
    args = parse_args(argv)
    # Parse --help/configuration before loading weights; support both entry points.
    try:
        if __package__:
            from .detector import detect_failure
        else:
            from detector import detect_failure
    except Exception as error:
        print(f'Cannot load YOLO: {error}. Install vision requirements and run '
              'python vision/src/download_model.py if weights are missing.', file=sys.stderr)
        return 2
    monitor(detect_failure, **vars(args))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

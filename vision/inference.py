import argparse
import json
import time

import cv2

from detector import detect_failure


def monitor(source=0, interval=3):
    """
    Monitor a video source and run failure detection periodically.

    source: Camera index, video path, or network stream URL.
    interval: Seconds between model inference runs.
    """

    camera = cv2.VideoCapture(source)

    if not camera.isOpened():
        raise RuntimeError(f"Cannot open video source: {source}")

    print("LayerLock vision monitoring started.")
    print("Press Q to exit.")

    last_inference = time.monotonic() - interval
    annotated_frame = None

    try:
        while True:
            success, frame = camera.read()

            if not success:
                print("Video source ended or frame capture failed.")
                break

            # Run YOLO every few seconds, rather than on every frame.
            if time.monotonic() - last_inference >= interval:
                result, annotated_frame = detect_failure(frame)

                print(json.dumps(result, indent=2))
                last_inference = time.monotonic()

            # Show model predictions when available.
            display_frame = (
                annotated_frame
                if annotated_frame is not None
                else frame
            )

            cv2.imshow("LayerLock Vision Monitor", display_frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--source",
        default="0",
        help="Camera index, video file, or stream URL"
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=3.0,
        help="Seconds between inference runs"
    )

    args = parser.parse_args()

    source = int(args.source) if args.source.isdigit() else args.source

    monitor(source=source, interval=args.interval)
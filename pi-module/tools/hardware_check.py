"""Quick check of the hardware layer. Run from the repo root:

    python -m tools.hardware_check                 # read-only: state, one frame, health
    python -m tools.hardware_check --pause         # then run an action and re-read state
    python -m tools.hardware_check --resume
    python -m tools.hardware_check --cancel
    python -m tools.hardware_check --heaters-off

Add MOCK=1 (env var) to run without any hardware.
"""
import argparse
import json
import logging

from hardware import CameraError, PrinterError, get_camera, get_health_monitor, get_printer

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main():
    ap = argparse.ArgumentParser()
    for flag in ("pause", "resume", "cancel", "heaters-off"):
        ap.add_argument(f"--{flag}", action="store_true")
    args = ap.parse_args()

    printer, camera = get_printer(), get_camera()
    monitor = get_health_monitor(printer)

    actions = {
        "pause": printer.pause_printer,
        "resume": printer.resume_printer,
        "cancel": printer.cancel_printer,
        "heaters_off": printer.heaters_off,
    }
    for name, fn in actions.items():
        if getattr(args, name):
            try:
                fn()
                print(f"{name}: ok")
            except PrinterError as e:
                print(f"{name}: FAILED: {e}")

    try:
        frame, err = camera.get_frame(), None
        frame.save("data/test_frame.jpg")
        print(f"frame: {len(frame.jpeg)} bytes, saved to data/test_frame.jpg")
    except CameraError as e:
        frame, err = None, e
        print(f"frame: FAILED: {e}")

    print(json.dumps(monitor.check_all(frame, err), indent=2))


if __name__ == "__main__":
    main()
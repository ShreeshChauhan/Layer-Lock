"""Health checks: silence or weirdness from any component is an alert.

Status values per component ("ok" is the only healthy one; "unknown" means we
could not measure, e.g. running on a laptop):
  camera:    ok | error | stale | dark | blocked | frozen
  octoprint: ok | error
  printer:   ok | unhealthy | disconnected | unknown
  pi_temp:   ok | warn | hot | throttled | unknown

Usage in the vision loop:
    try:
        frame, err = camera.get_frame(), None
    except CameraError as e:
        frame, err = None, e
    report = monitor.check_all(frame, err)
    # report["ok"], report["health"], report["details"], report["printer"]

Poll no faster than the camera actually produces new frames, or "frozen" will
false-trigger because you are looking at the same frame twice.
"""
import logging
import subprocess
import time
from pathlib import Path

from PIL import ImageChops, ImageStat

from . import config
from .camera import Frame
from .printer import HEALTHY_STATES, OctoPrintUnreachable, PrinterError

log = logging.getLogger(__name__)

THROTTLE_NOW = {0: "undervoltage", 1: "freq_capped", 2: "throttled", 3: "soft_temp_limit"}
THROTTLE_PAST = {16: "undervoltage", 17: "freq_capped", 18: "throttled", 19: "soft_temp_limit"}


class CameraHealth:
    """Stateful: remembers the previous frame to detect a frozen stream."""

    def __init__(self):
        self._prev_bytes: bytes | None = None
        self._prev_thumb = None
        self._same = 0

    def check(self, frame: Frame | None, error: Exception | None = None) -> tuple[str, str]:
        if error is not None or frame is None:
            self._prev_bytes = self._prev_thumb = None
            self._same = 0
            return "error", str(error or "no frame")

        age = time.time() - frame.t
        if age > config.FRAME_MAX_AGE_S:
            return "stale", f"frame is {age:.0f}s old"

        try:
            thumb = frame.to_pil().convert("L").resize((64, 48))
        except Exception as e:  # corrupt JPEG
            return "error", f"cannot decode frame: {e}"

        stat = ImageStat.Stat(thumb)
        mean, std = stat.mean[0], stat.stddev[0]

        # Frozen detection: count consecutive (near-)identical frames
        if self._prev_thumb is not None:
            diff = ImageStat.Stat(ImageChops.difference(thumb, self._prev_thumb)).mean[0]
            if frame.jpeg == self._prev_bytes or diff < config.FROZEN_DIFF:
                self._same += 1
            else:
                self._same = 0
        self._prev_bytes, self._prev_thumb = frame.jpeg, thumb

        if mean < config.DARK_MEAN:
            return "dark", f"mean brightness {mean:.0f}/255"
        if std < config.FLAT_STD:
            return "blocked", f"nearly uniform image (std {std:.1f})"
        if self._same >= config.FROZEN_COUNT:
            return "frozen", f"{self._same} identical frames in a row"
        return "ok", f"mean {mean:.0f}, std {std:.1f}"


def read_pi_temp() -> float | None:
    try:
        return int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000
    except (OSError, ValueError):
        return None


def read_throttled() -> int | None:
    try:
        out = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2).stdout
        return int(out.strip().split("=")[1], 16)
    except (OSError, subprocess.SubprocessError, IndexError, ValueError):
        return None


def check_pi() -> tuple[str, str]:
    temp, flags = read_pi_temp(), read_throttled()
    if temp is None and flags is None:
        return "unknown", "not a Pi (or vcgencmd unavailable)"

    now = [name for bit, name in THROTTLE_NOW.items() if flags and flags & (1 << bit)]
    past = [name for bit, name in THROTTLE_PAST.items() if flags and flags & (1 << bit)]
    detail = f"temp {temp:.0f}C" if temp is not None else "temp n/a"
    if past:
        detail += f", since boot: {','.join(past)}"

    if now:
        return "throttled", f"{detail}, now: {','.join(now)}"
    if temp is not None and temp >= config.PI_TEMP_CRIT_C:
        return "hot", detail
    if temp is not None and temp >= config.PI_TEMP_WARN_C:
        return "warn", detail
    return "ok", detail


class HealthMonitor:
    def __init__(self, printer):
        self.printer = printer
        self.camera = CameraHealth()

    def _check_printer(self) -> tuple[str, str, str, dict | None]:
        """Returns (octoprint_status, printer_status, detail, printer_state)."""
        try:
            s = self.printer.get_printer_state()
        except OctoPrintUnreachable as e:
            return "error", "unknown", str(e), None
        except PrinterError as e:
            return "error", "unknown", str(e), None
        if not s["connected"]:
            return "ok", "disconnected", f"printer link state: {s['state']}", s
        if s["state"].lower() not in HEALTHY_STATES or not s.get("healthy", True):
            return "ok", "unhealthy", f"printer state: {s['state']}", s
        return "ok", "ok", f"state: {s['state']}", s

    def check_all(self, frame: Frame | None = None, camera_error: Exception | None = None) -> dict:
        cam, cam_d = self.camera.check(frame, camera_error)
        octo, prn, prn_d, pstate = self._check_printer()
        pi, pi_d = check_pi()
        health = {"camera": cam, "octoprint": octo, "printer": prn, "pi_temp": pi}
        ok = all(v == "ok" for v in health.values() if v != "unknown")
        if not ok:
            log.warning("health problem: %s", {k: v for k, v in health.items() if v not in ("ok", "unknown")})
        return {
            "ok": ok,
            "health": health,
            "details": {"camera": cam_d, "printer": prn_d, "pi_temp": pi_d},
            "printer": pstate,
        }

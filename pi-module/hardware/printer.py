"""Printer control through the OctoPrint REST API.

Rules for this module:
  * Every request has a timeout.
  * Every failure raises PrinterError (or OctoPrintUnreachable) so callers can
    treat it as an alert. Nothing fails silently.
"""
import logging

import requests

from . import config

log = logging.getLogger(__name__)


class PrinterError(Exception):
    """OctoPrint answered, but the command or query failed."""


class OctoPrintUnreachable(PrinterError):
    """OctoPrint did not answer at all (down, wrong address, timeout)."""


class OctoPrinter:
    def __init__(self, base: str | None = None, key: str | None = None, timeout: float | None = None):
        self.base = (base or config.OCTO_URL).rstrip("/")
        key = key or config.OCTO_KEY
        if not key:
            raise PrinterError("OCTO_KEY is not set (put it in your environment or .env)")
        self.timeout = timeout or config.HTTP_TIMEOUT
        self.session = requests.Session()
        self.session.headers.update({"X-Api-Key": key})

    # -- low level ---------------------------------------------------------
    def _request(self, method: str, path: str, body: dict | None = None, ok: tuple = (200, 204)):
        try:
            r = self.session.request(method, self.base + path, json=body, timeout=self.timeout)
        except requests.RequestException as e:
            raise OctoPrintUnreachable(f"OctoPrint unreachable at {self.base}: {e}") from e
        if r.status_code not in ok:
            raise PrinterError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:200]}")
        return r

    # -- commands ----------------------------------------------------------
    def pause_printer(self) -> None:
        self._request("POST", "/api/job", {"command": "pause", "action": "pause"})
        log.warning("Printer: pause sent")

    def resume_printer(self) -> None:
        self._request("POST", "/api/job", {"command": "pause", "action": "resume"})
        log.info("Printer: resume sent")

    def cancel_printer(self) -> None:
        self._request("POST", "/api/job", {"command": "cancel"})
        log.warning("Printer: cancel sent")

    def heaters_off(self) -> None:
        """Set nozzle and bed targets to 0. Tries both even if the first fails."""
        errors = []
        for path, body in (
            ("/api/printer/tool", {"command": "target", "targets": {"tool0": 0}}),
            ("/api/printer/bed", {"command": "target", "target": 0}),
        ):
            try:
                self._request("POST", path, body)
            except PrinterError as e:
                errors.append(str(e))
        if errors:
            raise PrinterError("; ".join(errors))
        log.warning("Printer: heaters set to 0")

    def safe_stop(self, cancel: bool = True) -> dict:
        """Stop the job, then turn heaters off. Each step is attempted regardless of
        the other failing, and the result of each is returned so you can log/alert.

        cancel=True  -> cancel + heaters off (the fallback in the plan)
        cancel=False -> pause + heaters off. Note this turns heaters off immediately.
                        If you want the "wait a few minutes" behavior, call
                        pause_printer() now and heaters_off() later from the state machine.
        """
        result = {}
        steps = (("job", self.cancel_printer if cancel else self.pause_printer), ("heaters", self.heaters_off))
        for name, fn in steps:
            try:
                fn()
                result[name] = "ok"
            except PrinterError as e:
                log.error("safe_stop step %s failed: %s", name, e)
                result[name] = f"error: {e}"
        return result

    # -- queries -----------------------------------------------------------
    def get_printer_state(self) -> dict:
        """Normalized state. Raises OctoPrintUnreachable if OctoPrint is down.

        Returns:
          connected, state, port, baudrate, printing, paused, progress_pct,
          file, temps {tool0|bed: {actual, target}}
        """
        conn = self._request("GET", "/api/connection").json().get("current", {})
        state = conn.get("state", "Unknown")
        out = {
            "connected": not state.lower().startswith(("closed", "offline")),
            "state": state,
            "port": conn.get("port"),
            "baudrate": conn.get("baudrate"),
            "printing": False,
            "paused": False,
            "progress_pct": None,
            "file": None,
            "temps": {},
        }
        if not out["connected"]:
            return out

        # /api/printer returns 409 when the printer is not operational yet
        r = self._request("GET", "/api/printer", ok=(200, 409))
        if r.status_code == 409:
            out["connected"] = False
            return out
        p = r.json()
        flags = p.get("state", {}).get("flags", {})
        out["printing"] = bool(flags.get("printing"))
        out["paused"] = bool(flags.get("paused") or flags.get("pausing"))
        for name, t in p.get("temperature", {}).items():
            if isinstance(t, dict) and "actual" in t:
                out["temps"][name] = {"actual": t.get("actual"), "target": t.get("target")}

        job = self._request("GET", "/api/job").json()
        out["progress_pct"] = (job.get("progress") or {}).get("completion")
        out["file"] = ((job.get("job") or {}).get("file") or {}).get("name")
        return out

    def is_hot(self, above_c: float = 50.0) -> bool:
        """True if the nozzle or bed is still above `above_c`. Use after a stop."""
        temps = self.get_printer_state()["temps"]
        return any((t.get("actual") or 0) > above_c for t in temps.values())


class MockPrinter:
    """Same interface, no hardware. Keeps just enough state to exercise the state machine."""

    def __init__(self):
        self.state = "Printing"
        self.temps = {"tool0": {"actual": 210.0, "target": 210.0}, "bed": {"actual": 60.0, "target": 60.0}}

    def pause_printer(self):
        log.warning("[mock] pause")
        self.state = "Paused"

    def resume_printer(self):
        log.info("[mock] resume")
        self.state = "Printing"

    def cancel_printer(self):
        log.warning("[mock] cancel")
        self.state = "Operational"

    def heaters_off(self):
        log.warning("[mock] heaters off")
        for t in self.temps.values():
            t["target"] = 0.0
            t["actual"] = 25.0  # instant cooldown in mock

    def safe_stop(self, cancel: bool = True) -> dict:
        (self.cancel_printer if cancel else self.pause_printer)()
        self.heaters_off()
        return {"job": "ok", "heaters": "ok"}

    def get_printer_state(self) -> dict:
        return {
            "connected": True,
            "state": self.state,
            "port": "mock",
            "baudrate": 0,
            "printing": self.state == "Printing",
            "paused": self.state == "Paused",
            "progress_pct": 42.0,
            "file": "mock_part.gcode",
            "temps": {k: dict(v) for k, v in self.temps.items()},
        }

    def is_hot(self, above_c: float = 50.0) -> bool:
        return any(t["actual"] > above_c for t in self.temps.values())
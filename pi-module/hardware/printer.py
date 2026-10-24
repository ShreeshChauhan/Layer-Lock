"""Printer control through the OctoPrint REST API.

Rules for this module:
  * Every request has a timeout.
  * Every failure raises PrinterError (or OctoPrintUnreachable) so callers can
    treat it as an alert. Nothing fails silently.
"""
import logging
from pathlib import Path
from urllib.parse import quote

import requests

from . import config

log = logging.getLogger(__name__)


class PrinterError(Exception):
    """OctoPrint answered, but the command or query failed."""


class OctoPrintUnreachable(PrinterError):
    """OctoPrint did not answer at all (down, wrong address, timeout)."""


class ResumeBlocked(PrinterError):
    """Resume refused: heater is off or the nozzle is too cold."""


class PrintBlocked(PrinterError):
    """Start refused: printer is not idle and ready."""


def check_resume_ready(state: dict, min_temp: float | None = None) -> str | None:
    """Return a reason string if resuming is unsafe, else None."""
    min_temp = config.RESUME_MIN_TEMP_C if min_temp is None else min_temp
    tool = state.get("temps", {}).get("tool0")
    if tool is None:
        return "no nozzle temperature reading"
    if not (tool.get("target") or 0) > 0:
        return "nozzle heater is off (target 0)"
    actual = tool.get("actual") or 0
    if actual < min_temp:
        return f"nozzle is only {actual:.0f}C, needs {min_temp:.0f}C (still heating?)"
    return None


def check_start_ready(state: dict) -> str | None:
    """Return a reason string if starting a print is unsafe, else None."""
    if not state.get("connected"):
        return "printer is not connected to OctoPrint"
    if state.get("printing") or state.get("paused"):
        return "a job is already running or paused"
    if str(state.get("state", "")).lower() != "operational":
        return f"printer state is '{state.get('state')}', needs 'Operational'"
    return None


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
    def _request(self, method: str, path: str, body: dict | None = None, ok: tuple = (200, 204),
                 files=None, timeout: float | None = None):
        try:
            r = self.session.request(method, self.base + path, json=body, files=files,
                                     timeout=timeout or self.timeout)
        except requests.RequestException as e:
            raise OctoPrintUnreachable(f"OctoPrint unreachable at {self.base}: {e}") from e
        if r.status_code not in ok:
            raise PrinterError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:200]}")
        return r

    # -- commands ----------------------------------------------------------
    def pause_printer(self) -> None:
        self._request("POST", "/api/job", {"command": "pause", "action": "pause"})
        log.warning("Printer: pause sent")

    def resume_printer(self, force: bool = False) -> None:
        if not force:
            reason = check_resume_ready(self.get_printer_state())
            if reason:
                raise ResumeBlocked(f"resume blocked: {reason}")
        self._request("POST", "/api/job", {"command": "pause", "action": "resume"})
        log.info("Printer: resume sent")

    def cancel_printer(self) -> None:
        self._request("POST", "/api/job", {"command": "cancel"})
        log.warning("Printer: cancel sent")

    def heaters_on(self, nozzle_c: float = 200, bed_c: float = 60) -> None:
        self._request("POST", "/api/printer/tool", {"command": "target", "targets": {"tool0": nozzle_c}})
        self._request("POST", "/api/printer/bed", {"command": "target", "target": bed_c})
        log.warning("Printer: heaters set to %s/%s", nozzle_c, bed_c)

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

    # -- starting prints ---------------------------------------------------
    def list_files(self) -> list[dict]:
        """G-code files stored on OctoPrint (recursive). Each has name, path, size, date."""
        data = self._request("GET", "/api/files/local?recursive=true").json()
        out = []

        def walk(items):
            for f in items:
                if f.get("type") == "folder":
                    walk(f.get("children", []))
                elif f.get("type") == "machinecode":
                    out.append({"name": f.get("name"), "path": f.get("path"),
                                "size": f.get("size"), "date": f.get("date")})

        walk(data.get("files", []))
        return out

    def upload_file(self, local_path: str, remote_name: str | None = None) -> str:
        """Upload a .gcode file to OctoPrint without starting it. Returns the remote path."""
        p = Path(local_path)
        if not p.is_file():
            raise PrinterError(f"file not found: {local_path}")
        if p.suffix.lower() not in (".gcode", ".gco", ".g"):
            raise PrinterError(f"not a G-code file: {p.name} (slice it first)")
        name = remote_name or p.name
        with p.open("rb") as fh:
            r = self._request("POST", "/api/files/local", files={"file": (name, fh)},
                              ok=(200, 201), timeout=getattr(config, "UPLOAD_TIMEOUT", 120))
        path = r.json().get("files", {}).get("local", {}).get("path", name)
        log.info("Printer: uploaded %s", path)
        return path

    def start_print(self, remote_path: str, force: bool = False) -> None:
        """Select a file already on OctoPrint and start printing it."""
        if not force:
            reason = check_start_ready(self.get_printer_state())
            if reason:
                raise PrintBlocked(f"start blocked: {reason}")
        self._request("POST", f"/api/files/local/{quote(remote_path)}",
                      {"command": "select", "print": True})
        log.warning("Printer: print started: %s", remote_path)

    def print_file(self, local_path: str, force: bool = False) -> str:
        """Upload a local .gcode file and start it. Checks readiness before uploading."""
        if not force:
            reason = check_start_ready(self.get_printer_state())
            if reason:
                raise PrintBlocked(f"start blocked: {reason}")
        remote = self.upload_file(local_path)
        self.start_print(remote, force=force)
        return remote

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

    def resume_printer(self, force: bool = False):
        if not force:
            reason = check_resume_ready(self.get_printer_state())
            if reason:
                raise ResumeBlocked(f"resume blocked: {reason}")
        log.info("[mock] resume")
        self.state = "Printing"

    def cancel_printer(self):
        log.warning("[mock] cancel")
        self.state = "Operational"

    def heaters_on(self, nozzle_c: float = 200, bed_c: float = 60):
        log.warning("[mock] heaters on %s/%s", nozzle_c, bed_c)
        self.temps["tool0"].update(target=float(nozzle_c), actual=float(nozzle_c))
        self.temps["bed"].update(target=float(bed_c), actual=float(bed_c))

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

    def list_files(self):
        return [{"name": "mock_part.gcode", "path": "mock_part.gcode", "size": 1234, "date": 0}]

    def upload_file(self, local_path, remote_name=None):
        log.info("[mock] upload %s", local_path)
        return remote_name or Path(local_path).name

    def start_print(self, remote_path, force=False):
        log.warning("[mock] start %s", remote_path)
        self.state = "Printing"

    def print_file(self, local_path, force=False):
        remote = self.upload_file(local_path)
        self.start_print(remote, force=force)
        return remote
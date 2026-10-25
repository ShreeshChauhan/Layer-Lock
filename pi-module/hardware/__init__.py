"""Hardware layer. The rest of the project only imports from here.

    from hardware import get_printer, get_camera, get_health_monitor

(Run scripts from the pi-module folder. If this folder is moved into a package,
the import path changes to match, e.g. `from backend.hardware import ...`.)

MOCK=1 gives fake versions with the same interface (no Pi, printer, or camera needed).
Create ONE printer and pass it around, so mock state stays consistent:

    printer = get_printer()
    camera = get_camera()
    monitor = get_health_monitor(printer)
"""
from . import config
from .camera import CameraError, Frame, ReplayCamera, SnapshotCamera
from .health import HealthMonitor
from .printer import MockPrinter, OctoPrinter, OctoPrintUnreachable, PrinterError, ResumeBlocked, PrintBlocked


__all__ = [
    "config",
    "get_printer", "get_camera", "get_health_monitor",
    "OctoPrinter", "MockPrinter", "SnapshotCamera", "ReplayCamera", "HealthMonitor",
    "Frame", "CameraError", "PrinterError", "OctoPrintUnreachable", "ResumeBlocked", "PrintBlocked",
]


def get_printer():
    return MockPrinter() if config.MOCK else OctoPrinter()


def get_camera():
    return ReplayCamera() if config.MOCK else SnapshotCamera()


def get_health_monitor(printer=None):
    return HealthMonitor(printer or get_printer())
"""Own the local inference publisher; never arm monitoring or command the printer."""
import asyncio
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit

from printer import SETTINGS

ROOT = Path(__file__).resolve().parent


class VisionService:
    def __init__(self):
        self.process = None
        self.watcher = None
        self.lock = asyncio.Lock()
        self.disabled_by_user = False
        self.error = ''
        self.started_at = None
        self.external = False

    def prerequisites(self):
        missing = [name for name in ('cv2', 'numpy', 'torch', 'ultralytics') if importlib.util.find_spec(name) is None]
        if missing:
            return 'Install vision/requirements.txt on the backend before enabling vision.'
        if not any((ROOT / 'vision/models' / name).is_file() for name in ('layerlock.pt', 'yolov11-3d-print-failure-detection')):
            return 'Model weights are missing. Run vision/src/download_model.py on the backend.'
        try:
            url = urlsplit(SETTINGS.get('SNAPSHOT_URL', ''))
            valid_url = url.scheme in ('http', 'https') and bool(url.hostname)
        except ValueError:
            valid_url = False
        if not valid_url:
            return 'Configure SNAPSHOT_URL on the backend before enabling vision.'
        return ''

    def status(self, sensor=None):
        fresh = (not self.disabled_by_user and sensor and sensor.get('source') == 'live' and
                 sensor.get('updated_at') is not None and time.time() - sensor['updated_at'] < 10)
        managed = self.process is not None and self.process.returncode is None
        current = fresh and (not managed or sensor['updated_at'] >= self.started_at)
        problem = self.error or self.prerequisites()
        if self.disabled_by_user:
            state, message = 'disabled', 'Vision detection is disabled.'
        elif managed:
            state = 'running' if current else 'starting'
            message = 'Receiving live detections.' if current else 'Waiting for a fresh detection; check vision.log if this persists.'
        elif fresh and not self.error:
            state, message = 'running', 'Receiving detections from an external vision publisher.'
        elif self.external and not self.error:
            state, message = 'waiting', 'Waiting for the external vision publisher to send fresh readings.'
        elif problem:
            state, message = 'unavailable', problem
        else:
            state, message = 'disabled', 'Enable vision to analyze camera snapshots.'
        return {'enabled': not self.disabled_by_user and bool(managed or fresh or self.external) and not bool(self.error), 'managed': managed, 'state': state,
                'message': message, 'available': not bool(self.prerequisites())}

    async def _watch(self, process, log):
        try:
            code = await process.wait()
            if self.process is process:
                self.process = None
                self.error = f'Vision stopped (exit {code}). See vision.log on the backend.'
        finally:
            log.close()

    async def enable(self, external_fresh=False):
        async with self.lock:
            if self.process is not None and self.process.returncode is None:
                self.disabled_by_user = False
                return
            if external_fresh or self.external:
                self.disabled_by_user = False
                self.error = ''
                self.external = True
                return
            problem = self.prerequisites()
            if problem:
                self.error = problem
                raise ValueError(problem)
            log = (ROOT / 'vision.log').open('ab', buffering=0)
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            try:
                process = await asyncio.create_subprocess_exec(
                    sys.executable, '-u', '-m', 'vision.src.pi_inference', '--headless',
                    '--snapshot-url', SETTINGS['SNAPSHOT_URL'],
                    '--backend-url', SETTINGS.get('VISION_BACKEND_URL', 'http://127.0.0.1:8000'),
                    cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, creationflags=flags,
                    env={**os.environ, 'PYTHONUNBUFFERED': '1'})
            except Exception:
                log.close()
                raise
            self.process = process
            self.started_at = time.time()
            self.disabled_by_user = False
            self.error = ''
            self.watcher = asyncio.create_task(self._watch(process, log))

    async def disable(self):
        async with self.lock:
            self.disabled_by_user = True
            process = self.process
            if process is not None and process.returncode is None:
                if sys.platform == 'win32':
                    # A venv launcher may own a child Python process: stop our entire
                    # tracked process tree, never a publisher started by someone else.
                    killer = await asyncio.create_subprocess_exec('taskkill', '/PID', str(process.pid), '/T', '/F',
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
                    await asyncio.wait_for(killer.wait(), timeout=5)
                else:
                    process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            self.process = None
            if self.watcher is not None:
                await self.watcher
                self.watcher = None


vision_service = VisionService()

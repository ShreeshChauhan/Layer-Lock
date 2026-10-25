"""Backend-owned telemetry sampling; continues when the dashboard is closed."""
import asyncio
import time
from datetime import datetime, timezone
from collections import deque

from incident_db import save_event


class PrinterMonitor:
    def __init__(self, printer):
        self.printer = printer
        self.status = None
        self.error = None
        self.history = deque(maxlen=400)  # approximately 20 minutes at 3 seconds
        self.last_sample = 0
        self.lock = asyncio.Lock()

    def event(self, message):
        save_event(message, self.printer.simulated)

    async def sample(self, force=False):
        async with self.lock:
            if not force and time.monotonic() - self.last_sample < 3 and self.last_sample:
                return self.status
            try:
                current = await self.printer.get_status()
                previous = self.status
                if self.error:
                    self.event('Printer telemetry connection restored')
                if previous is None or previous['state'] != current['state']:
                    self.event(f"Printer state: {current['state']}")
                if previous is None or previous.get('file') != current.get('file'):
                    if current.get('file'):
                        self.event(f"Selected print: {current['file']}")
                old_temps = (previous or {}).get('temperatures', {})
                for name, reading in current['temperatures'].items():
                    if reading.get('target') != old_temps.get(name, {}).get('target'):
                        self.event(f"{name} target set to {reading['target']} C")
                self.history.append({'timestamp': current['sampled_at'], **{
                    f'{name}_{key}': current['temperatures'].get(name, {}).get(key)
                    for name in ('tool0', 'bed') for key in ('actual', 'target')
                }})
                self.status, self.error = current, None
            except Exception as error:
                if not self.error:
                    self.event('Printer telemetry unavailable')
                    self.history.append({'timestamp': datetime.now(timezone.utc).isoformat(),
                        **{f'{name}_{key}': None for name in ('tool0', 'bed') for key in ('actual', 'target')}})
                self.error = str(error)
            self.last_sample = time.monotonic()
            return self.status

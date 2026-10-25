"""Backend-owned telemetry sampling; continues when the dashboard is closed."""
import asyncio
import time
from datetime import datetime, timezone
from collections import deque

from backend.incident_db import save_event, save_print_action


class PrinterMonitor:
    def __init__(self, printer):
        self.printer = printer
        self.status = None
        self.error = None
        self.history = deque(maxlen=400)  # approximately 20 minutes at 3 seconds
        self.last_sample = 0
        self.lock = asyncio.Lock()
        self.expected = {}

    def expect_action(self, action, status):
        if action in ('pause', 'cancel'):
            self.expected[action] = (status.get('file'), time.monotonic() + 60)

    def observe_action(self, current, previous):
        state = current['state'].lower()
        action = 'pause' if state in ('pausing', 'paused') else 'cancel' if state in ('cancelling', 'cancelled', 'canceled', 'canceling') else None
        old_state = (previous or {}).get('state', '').lower()
        old_action = 'pause' if old_state in ('pausing', 'paused') else 'cancel' if old_state in ('cancelling', 'cancelled', 'canceled', 'canceling') else None
        if previous is None or action is None or action == old_action:
            return
        expected_file, expires = self.expected.pop(action, (None, 0))
        file = current.get('file') or previous.get('file')
        if expires > time.monotonic() and file == expected_file:
            return
        save_print_action(action, 'external / unknown', {**previous, **current, 'file': file},
                          'Observed outside the web controls; initiator unavailable', 'Observed')

    def event(self, message):
        save_event(message, self.printer.simulated)

    async def sample(self, force=False):
        async with self.lock:
            if not force and time.monotonic() - self.last_sample < 3 and self.last_sample:
                return self.status
            try:
                current = await self.printer.get_status()
                previous = self.status
                self.observe_action(current, previous)
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
                self.error = str(error) or 'Unable to reach the printer. Check the Raspberry Pi connection and OctoPrint address.'
            self.last_sample = time.monotonic()
            return self.status

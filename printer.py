"""Async printer telemetry and controls for the web app."""
import asyncio
import math
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent
SETTINGS = {**dotenv_values(ROOT / 'pi-module' / '.env'), **dotenv_values(ROOT / '.env'), **os.environ}
PRINTER_TYPE = SETTINGS.get('PRINTER_TYPE', 'mock').lower()
OCTOPRINT_URL = SETTINGS.get('OCTOPRINT_URL', SETTINGS.get('OCTO_URL', 'http://127.0.0.1:5000')).rstrip('/')
OCTOPRINT_API_KEY = SETTINGS.get('OCTOPRINT_API_KEY', SETTINGS.get('OCTO_KEY', ''))
MOONRAKER_URL = SETTINGS.get('MOONRAKER_URL', 'http://127.0.0.1:7125').rstrip('/')
RESUME_MIN_TEMP_C = float(SETTINGS.get('RESUME_MIN_TEMP_C', '180'))


class CommandBlocked(ValueError):
    """Command cannot run in the current printer state."""


def number(value):
    if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
        raise ValueError('Malformed numeric printer telemetry')
    return value


def validate_upload_name(name):
    if (not name or len(name) > 255 or any(c in name for c in '/\\')
            or any(ord(c) < 32 for c in name)
            or Path(name).suffix.lower() not in ('.gcode', '.gco', '.g')):
        raise ValueError('Choose a sliced G-code file (.gcode, .gco, or .g)')
    return name


class Printer:
    def __init__(self):
        self._client = None
        self.mock_paused = False
        self.mock_idle = False
        self.mock_file = 'mock_part.gcode'
        self.mock_files = {'mock_part.gcode': {'name': 'mock_part.gcode', 'path': 'mock_part.gcode', 'size': 1234, 'date': 0}}

    @property
    def simulated(self):
        return PRINTER_TYPE == 'mock'

    async def _octo(self, method, path, *, timeout=5, **kwargs):
        if not OCTOPRINT_API_KEY:
            raise ValueError('Configure OCTOPRINT_API_KEY (or OCTO_KEY) on the backend')
        # Reuse connections: repeated client/SSL setup can stall video forwarding.
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=5)
        response = await self._client.request(method, OCTOPRINT_URL + path,
            headers={'X-Api-Key': OCTOPRINT_API_KEY}, timeout=timeout, **kwargs)
        response.raise_for_status()
        return response

    async def close(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _printer_response(self):
        try:
            return (await self._octo('GET', '/api/printer')).json()
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 409:
                return {}  # OctoPrint reachable, printer disconnected.
            raise

    async def get_status(self):
        sampled_at = datetime.now(timezone.utc).isoformat()
        if self.simulated:
            return {
                'connected': True, 'operational': True, 'can_connect': False,
                'state': 'Operational' if self.mock_idle else 'Paused' if self.mock_paused else 'Printing',
                'printing': not self.mock_idle and not self.mock_paused,
                'paused': self.mock_paused, 'progress': None if self.mock_idle else 42.5,
                'print_time': None if self.mock_idle else 1200,
                'print_time_left': None if self.mock_idle else 1624, 'file': self.mock_file,
                'file_path': self.mock_file, 'file_origin': 'local',
                'temperatures': {'tool0': {'actual': 209.5, 'target': 210}, 'bed': {'actual': 59.8, 'target': 60}},
                'simulated': True, 'sampled_at': sampled_at,
            }
        if PRINTER_TYPE == 'octoprint':
            response, detail = await asyncio.gather(self._octo('GET', '/api/job'), self._printer_response())
            job = response.json()
            flags = detail.get('state', {}).get('flags', {})
            progress = job.get('progress') or {}
            temperatures = {
                name: {key: number(reading.get(key)) for key in ('actual', 'target')}
                for name, reading in detail.get('temperature', {}).items()
                if name != 'history' and isinstance(reading, dict)
            }
            return {
                'connected': bool(detail) and not bool(flags.get('closedOrError')),
                'can_connect': not detail and (job.get('state') or '').lower() in ('offline', 'offline after error', 'closed', 'error'),
                'operational': bool(flags.get('operational')) and not bool(flags.get('error')),
                'state': job.get('state') or detail.get('state', {}).get('text') or 'Unknown',
                'printing': bool(flags.get('printing')), 'paused': bool(flags.get('paused')),
                'progress': number(progress.get('completion')), 'print_time': number(progress.get('printTime')),
                'print_time_left': number(progress.get('printTimeLeft')),
                'file': ((job.get('job') or {}).get('file') or {}).get('name'),
                'file_path': ((job.get('job') or {}).get('file') or {}).get('path'),
                'file_origin': ((job.get('job') or {}).get('file') or {}).get('origin'),
                'temperatures': temperatures, 'simulated': False, 'sampled_at': sampled_at,
            }
        if PRINTER_TYPE == 'moonraker':
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(MOONRAKER_URL + '/printer/objects/query',
                    params={key: '' for key in ('print_stats', 'virtual_sdcard', 'extruder', 'heater_bed')})
                response.raise_for_status()
            data = response.json()['result']['status']
            state = data['print_stats']['state']
            return {'connected': True, 'operational': state != 'error', 'state': state.title(),
                'printing': state == 'printing', 'paused': state == 'paused',
                'progress': round(number(data['virtual_sdcard']['progress']) * 100, 2),
                'print_time': number(data['print_stats'].get('print_duration')), 'print_time_left': None,
                'file': data['print_stats'].get('filename'),
                'temperatures': {name: {'actual': number(data[key].get('temperature')), 'target': number(data[key].get('target'))}
                    for name, key in (('tool0', 'extruder'), ('bed', 'heater_bed'))},
                'simulated': False, 'sampled_at': sampled_at}
        raise ValueError('Unsupported printer type')

    async def connect(self):
        if self.simulated:
            raise CommandBlocked('The demo printer is already connected')
        if PRINTER_TYPE != 'octoprint':
            raise CommandBlocked('Connection control currently requires OctoPrint')
        connection = (await self._octo('GET', '/api/connection')).json()
        state = connection['current']['state'].lower()
        # OctoPrint's connect command reconnects an already connected printer.
        # Only issue it from a known disconnected state, never during a job.
        if state not in ('offline', 'offline after error', 'closed', 'error'):
            raise CommandBlocked('Printer is already connected or a connection is in progress')
        await self._octo('POST', '/api/connection', json={'command': 'connect'})
        return self._accepted('Connect')

    async def list_files(self):
        if self.simulated:
            return [dict(file) for file in self.mock_files.values()]
        if PRINTER_TYPE != 'octoprint':
            raise CommandBlocked('File selection currently requires OctoPrint')
        response = await self._octo('GET', '/api/files/local', params={'recursive': 'true', 'force': 'true'})
        files = []
        def walk(entries):
            for entry in entries:
                if entry.get('type') == 'folder':
                    walk(entry.get('children', []))
                elif entry.get('type') == 'machinecode':
                    files.append({key: entry.get(key) for key in ('name', 'path', 'size', 'date')})
        walk(response.json()['files'])
        return files

    async def upload_file(self, name, stream, size):
        """Store G-code on OctoPrint, without selecting it or starting a job.

        Mirrors pi-module's upload_file(), using its returned remote path.
        A new name is used on collisions so existing printer files are preserved.
        """
        validate_upload_name(name)
        existing = {entry['path'] for entry in await self.list_files()}
        if name in existing:
            name = f'{Path(name).stem[:230]}-{uuid.uuid4().hex[:8]}{Path(name).suffix}'
        if self.simulated:
            file = {'name': name, 'path': name, 'size': size, 'date': int(time.time())}
            self.mock_files[name] = file
            return dict(file)
        response = await self._octo('POST', '/api/files/local', timeout=120,
            files={'file': (name, stream, 'application/octet-stream')},
            data={'select': 'false', 'print': 'false'})
        file = response.json().get('files', {}).get('local', {})
        path = file.get('path')
        if not isinstance(path, str) or not path:
            raise ValueError('OctoPrint did not return the uploaded file path')
        return {'name': file.get('name') or Path(path).name, 'path': path, 'size': size, 'date': int(time.time())}

    async def start(self, path):
        status = await self.get_status()
        if not status['connected'] or not status['operational'] or status['state'].lower() != 'operational':
            raise CommandBlocked('Start requires an idle, operational printer')
        if path not in {entry['path'] for entry in await self.list_files()}:
            raise CommandBlocked('Select an existing G-code file from OctoPrint')
        if self.simulated:
            self.mock_idle, self.mock_paused, self.mock_file = False, False, path
        else:
            await self._octo('POST', '/api/files/local/' + quote(path, safe=''), json={'command': 'select', 'print': True})
        return self._accepted('Start')

    async def delete_file(self, path):
        # OctoPrint also enforces its own busy-file guard against external races.
        status = await self.get_status()
        state = status['state'].lower()
        if not status['connected'] or state not in ('operational', 'printing', 'paused', 'pausing', 'resuming', 'starting', 'finishing', 'cancelling'):
            raise CommandBlocked('Cannot verify which file is in use; restore printer telemetry first')
        if status['printing'] or status['paused'] or state != 'operational':
            active_path = status.get('file_path')
            active_name = status.get('file')
            if not active_path and not active_name:
                raise CommandBlocked('Cannot identify the active print; refresh printer telemetry')
            if status.get('file_origin') != 'sdcard' and (
                    path == active_path if active_path else Path(path).name == active_name):
                raise CommandBlocked('Cannot remove the file used by the current print')
        if path not in {entry['path'] for entry in await self.list_files()}:
            raise CommandBlocked('File no longer exists; refresh the file list')
        if self.simulated:
            del self.mock_files[path]
            if self.mock_file == path:
                self.mock_file = None
        else:
            await self._octo('DELETE', '/api/files/local/' + quote(path, safe=''))
        return self._accepted('Delete')

    async def resume(self):
        status = await self.get_status()
        if not status['paused'] or not status['operational']:
            raise CommandBlocked('Resume requires a paused, operational printer')
        tool = status['temperatures'].get('tool0', {})
        if (tool.get('target') or 0) <= 0 or (tool.get('actual') or 0) < RESUME_MIN_TEMP_C:
            raise CommandBlocked(f'Resume blocked: heat the nozzle to at least {RESUME_MIN_TEMP_C:g} C first')
        await self._job('resume')
        return self._accepted('Resume')

    async def cancel(self):
        status = await self.get_status()
        if not status['printing'] and not status['paused']:
            raise CommandBlocked('No active print to cancel')
        await self._job('cancel')
        return self._accepted('Cancel')

    async def pause(self, status=None):
        status = status or await self.get_status()
        if not status['printing'] and not status['paused']:
            raise CommandBlocked('No active print to pause')
        await self._job('pause')
        return self._accepted('Pause')

    async def _job(self, action):
        if self.simulated:
            self.mock_paused = action == 'pause'
            self.mock_idle = action == 'cancel'
        elif PRINTER_TYPE == 'octoprint':
            body = {'command': 'pause', 'action': action} if action in ('pause', 'resume') else {'command': action}
            await self._octo('POST', '/api/job', json=body)
        elif PRINTER_TYPE == 'moonraker':
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.post(f'{MOONRAKER_URL}/printer/print/{action}')
                response.raise_for_status()
        else:
            raise ValueError('Unsupported printer type')

    def _accepted(self, action):
        return {'success': True, 'message': f'{action} command accepted', 'simulated': self.simulated}

    async def reset_simulation(self):
        if not self.simulated:
            raise ValueError('Reset is only available in mock printer mode')
        self.mock_paused = self.mock_idle = False
        return self._accepted('Simulation reset')


printer = Printer()

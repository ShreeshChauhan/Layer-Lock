import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from backend.vision_service import VisionService


class FakeProcess:
    def __init__(self):
        self.pid = 12345
        self.returncode = None
        self.done = asyncio.Event()

    async def wait(self):
        await self.done.wait()
        return self.returncode

    def terminate(self):
        self.returncode = -15
        self.done.set()


class VisionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_windows_disable_targets_only_owned_process_tree(self):
        service = VisionService()
        process = FakeProcess()
        service.process = process
        async def kill_tree(*args, **kwargs):
            process.terminate()
            return SimpleNamespace(wait=AsyncMock(return_value=0))
        with patch('backend.vision_service.sys.platform', 'win32'), \
                patch('backend.vision_service.asyncio.create_subprocess_exec', new_callable=AsyncMock, side_effect=kill_tree) as spawn:
            await service.disable()
        self.assertEqual(spawn.call_args.args, ('taskkill', '/PID', '12345', '/T', '/F'))
    async def test_start_is_idempotent_and_disable_stops_only_owned_process(self):
        service = VisionService()
        process = FakeProcess()
        with tempfile.TemporaryDirectory() as folder, patch('backend.vision_service.ROOT', Path(folder)), \
                patch('backend.vision_service.SETTINGS', {'SNAPSHOT_URL': 'http://camera.test/snapshot'}), \
                patch.object(service, 'prerequisites', return_value=''), \
                patch('backend.vision_service.sys.platform', 'linux'), \
                patch('backend.vision_service.asyncio.create_subprocess_exec', new_callable=AsyncMock, return_value=process) as spawn:
            await service.enable()
            await service.enable()
            self.assertEqual(spawn.await_count, 1)
            self.assertIn('vision.src.pi_inference', spawn.call_args.args)
            self.assertEqual(service.status()['state'], 'starting')
            sensor = {'source': 'live', 'updated_at': time.time()}
            self.assertEqual(service.status(sensor)['state'], 'running')
            await service.disable()
            self.assertEqual(service.status(sensor)['state'], 'disabled')
            self.assertEqual(process.returncode, -15)
            self.assertIsNone(service.process)

    async def test_missing_prerequisites_never_spawn(self):
        service = VisionService()
        with patch.object(service, 'prerequisites', return_value='Missing model'), \
                patch('backend.vision_service.asyncio.create_subprocess_exec', new_callable=AsyncMock) as spawn:
            with self.assertRaises(ValueError):
                await service.enable()
            spawn.assert_not_called()
            self.assertEqual(service.status()['state'], 'unavailable')

    async def test_external_publisher_is_not_killed(self):
        service = VisionService()
        sensor = {'source': 'live', 'updated_at': time.time()}
        with patch.object(service, 'prerequisites', return_value='Missing local dependencies'), \
                patch('backend.vision_service.asyncio.create_subprocess_exec', new_callable=AsyncMock) as spawn:
            await service.enable(external_fresh=True)
            self.assertTrue(service.status(sensor)['enabled'])
            await service.disable()
            self.assertFalse(service.status(sensor)['enabled'])
            await service.enable()
            self.assertTrue(service.status()['enabled'])
            self.assertEqual(service.status()['state'], 'waiting')
            spawn.assert_not_called()

    async def test_unexpected_exit_shows_error_even_when_previous_reading_is_fresh(self):
        service = VisionService()
        process = FakeProcess()
        with tempfile.TemporaryDirectory() as folder, patch('backend.vision_service.ROOT', Path(folder)), \
                patch('backend.vision_service.SETTINGS', {'SNAPSHOT_URL': 'http://camera.test/snapshot'}), \
                patch.object(service, 'prerequisites', return_value=''), \
                patch('backend.vision_service.asyncio.create_subprocess_exec', new_callable=AsyncMock, return_value=process):
            await service.enable()
            process.returncode = 2
            process.done.set()
            await service.watcher
            self.assertEqual(service.status({'source': 'live', 'updated_at': time.time()})['state'], 'unavailable')

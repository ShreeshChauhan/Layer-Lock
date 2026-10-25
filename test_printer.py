"""Real OctoPrint HTTP contracts, with an isolated mocked transport."""
import unittest
import io
from unittest.mock import patch

import httpx
import printer as adapter


class OctoPrintTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.commands = []
        self.state = 'Printing'
        self.actual = 205
        self.target = 210
        self.disconnected = False
        self.fail_commands = False
        self.uploads = []
        self.deletes = []
        self.malformed_upload = False
        original_client = httpx.AsyncClient
        self.patches = [patch.object(adapter, 'PRINTER_TYPE', 'octoprint'),
                        patch.object(adapter, 'OCTOPRINT_API_KEY', 'test-key'),
                        patch.object(adapter.httpx, 'AsyncClient', side_effect=lambda **kwargs:
                            original_client(transport=httpx.MockTransport(self.handle), **kwargs))]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.printer = adapter.Printer()

    def handle(self, request):
        self.assertEqual(request.headers['X-Api-Key'], 'test-key')
        if request.method == 'DELETE':
            self.deletes.append(request.url.path)
            return httpx.Response(409 if self.fail_commands else 204)
        if request.method == 'POST' and request.url.path == '/api/files/local':
            self.uploads.append(request)
            return httpx.Response(201, json={} if self.malformed_upload else {
                'files': {'local': {'name': 'uploaded.gcode', 'path': 'uploaded.gcode'}}})
        if request.method == 'POST':
            import json
            self.commands.append((request.url.path, json.loads(request.content)))
            return httpx.Response(409 if self.fail_commands else 204)
        if request.url.path == '/api/job':
            return httpx.Response(200, json={'state': self.state,
                'job': {'file': {'name': 'cube.gcode'}},
                'progress': {'completion': 37.2, 'printTime': 300, 'printTimeLeft': 900}})
        if request.url.path == '/api/printer':
            if self.disconnected:
                return httpx.Response(409)
            return httpx.Response(200, json={'state': {'flags': {'operational': True,
                'printing': self.state == 'Printing', 'paused': self.state == 'Paused'}},
                'temperature': {'tool0': {'actual': self.actual, 'target': self.target},
                                'bed': {'actual': 58.3, 'target': 60}, 'history': []}})
        if request.url.path == '/api/files/local':
            return httpx.Response(200, json={'files': [{'type': 'folder', 'children': [
                {'type': 'machinecode', 'name': 'cube.gcode', 'path': 'parts/cube.gcode'}]}]})
        raise AssertionError(f'Unexpected HTTP: {request.url}')

    async def test_real_progress_time_and_temperatures(self):
        status = await self.printer.get_status()
        self.assertFalse(status['simulated'])
        self.assertEqual(status['progress'], 37.2)
        self.assertEqual(status['print_time'], 300)
        self.assertEqual(status['print_time_left'], 900)
        self.assertEqual(status['temperatures']['bed'], {'actual': 58.3, 'target': 60})

    async def test_delete_is_idle_only_and_propagates_rejection(self):
        with self.assertRaises(adapter.CommandBlocked):
            await self.printer.delete_file('parts/cube.gcode')
        self.assertEqual(self.deletes, [])
        self.state = 'Operational'
        with self.assertRaises(adapter.CommandBlocked):
            await self.printer.delete_file('../missing.gcode')
        await self.printer.delete_file('parts/cube.gcode')
        self.assertEqual(self.deletes, ['/api/files/local/parts/cube.gcode'])
        self.fail_commands = True
        with self.assertRaises(httpx.HTTPStatusError):
            await self.printer.delete_file('parts/cube.gcode')

    async def test_disconnected_is_not_connected(self):
        self.disconnected = True
        status = await self.printer.get_status()
        self.assertFalse(status['connected'])
        self.assertEqual(status['temperatures'], {})

    async def test_start_requires_idle_and_known_file(self):
        with self.assertRaises(adapter.CommandBlocked):
            await self.printer.start('parts/cube.gcode')
        self.state = 'Operational'
        with self.assertRaises(adapter.CommandBlocked):
            await self.printer.start('../unknown.gcode')
        await self.printer.start('parts/cube.gcode')
        self.assertEqual(self.commands[-1][1], {'command': 'select', 'print': True})
        self.assertTrue(self.commands[-1][0].endswith('/parts/cube.gcode'))

    async def test_resume_requires_paused_and_hot_nozzle(self):
        with self.assertRaises(adapter.CommandBlocked):
            await self.printer.resume()
        self.state = 'Paused'
        for self.actual, self.target in [(25, 210), (205, 0)]:
            with self.assertRaises(adapter.CommandBlocked):
                await self.printer.resume()
        self.assertEqual(self.commands, [])
        self.actual, self.target = 205, 210
        await self.printer.resume()
        self.assertEqual(self.commands[-1][1], {'command': 'pause', 'action': 'resume'})

    async def test_pause_and_cancel_use_explicit_commands(self):
        await self.printer.pause()
        await self.printer.cancel()
        self.assertEqual([body for _, body in self.commands],
                         [{'command': 'pause', 'action': 'pause'}, {'command': 'cancel'}])

    async def test_rejected_command_is_not_success(self):
        self.fail_commands = True
        with self.assertRaises(httpx.HTTPStatusError):
            await self.printer.pause()

    async def test_upload_forwards_multipart_without_starting_or_selecting(self):
        result = await self.printer.upload_file('new.gcode', io.BytesIO(b'G28\n'), 4)
        self.assertEqual(result['path'], 'uploaded.gcode')
        self.assertEqual(self.commands, [])
        request = self.uploads[0]
        self.assertIn('multipart/form-data', request.headers['Content-Type'])
        self.assertIn('Content-Length', request.headers)
        self.assertIn(b'filename="new.gcode"', request.content)
        self.assertIn(b'G28\n', request.content)
        self.assertIn(b'name="print"\r\n\r\nfalse', request.content)

    async def test_upload_uses_returned_path_and_rejects_malformed_response(self):
        self.malformed_upload = True
        with self.assertRaises(ValueError):
            await self.printer.upload_file('new.gcode', io.BytesIO(b'G28\n'), 4)


if __name__ == '__main__':
    unittest.main()

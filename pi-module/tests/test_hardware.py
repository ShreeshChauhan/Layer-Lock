"""Hardware regressions: all HTTP and device probes are mocked."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hardware import health
from hardware.camera import SnapshotCamera, CameraError
from hardware.printer import OctoPrinter, MockPrinter, PrinterError, PrintBlocked, ResumeBlocked


def response(data, status=200):
    result = Mock(status_code=status, text='test response')
    result.json.return_value = data
    return result


def readings(state='Operational'):
    return [
        {'current': {'state': state, 'port': 'mock', 'baudrate': 115200}},
        {'state': {'flags': {'operational': True, 'printing': state == 'Printing',
                            'paused': state == 'Paused', 'error': False}},
         'temperature': {'tool0': {'actual': 210, 'target': 210}}},
        {'progress': {'completion': 42}, 'job': {'file': {'name': 'part.gcode'}}},
    ]


class HardwareTests(unittest.TestCase):
    def setUp(self):
        # Prevent any real request, including accidental commands in a regression.
        transport = patch('requests.sessions.Session.request', side_effect=AssertionError('Real HTTP forbidden'))
        transport.start()
        self.addCleanup(transport.stop)
        self.printer = OctoPrinter(base='http://octoprint.test', key='test-only', timeout=2)
        self.printer.session.request = Mock()

    def feed(self, values):
        self.printer.session.request.side_effect = [response(v) for v in values]

    def test_valid_states_and_timeout(self):
        for state in ['Operational', 'Printing', 'Paused']:
            self.feed(readings(state))
            result = self.printer.get_printer_state()
            self.assertTrue(result['healthy'])
            self.assertEqual(result['progress_pct'], 42)
        for call in self.printer.session.request.call_args_list:
            self.assertEqual(call.kwargs['timeout'], 2)
            self.assertEqual(call.args[0], 'GET')

    def test_unhealthy_connected_states_and_flags(self):
        for state in ['Error', 'Unknown', 'Connecting', 'Detecting serial connection']:
            with self.subTest(state=state):
                self.feed(readings(state))
                report = health.HealthMonitor(self.printer)._check_printer()
                self.assertEqual(report[:2], ('ok', 'unhealthy'))
        for flag, value in [('error', True), ('closedOrError', True), ('operational', False)]:
            data = readings()
            data[1]['state']['flags'][flag] = value
            self.feed(data)
            self.assertEqual(health.HealthMonitor(self.printer)._check_printer()[1], 'unhealthy')

    def test_disconnected_and_conflict(self):
        self.feed([{'current': {'state': 'Closed'}}])
        self.assertEqual(health.HealthMonitor(self.printer)._check_printer()[1], 'disconnected')
        self.printer.session.request.side_effect = [response(readings()[0]), response(None, 409)]
        self.assertFalse(self.printer.get_printer_state()['healthy'])

    def test_invalid_json_at_each_query(self):
        for index in range(3):
            replies = [response(v) for v in readings()]
            replies[index].json.side_effect = ValueError('bad JSON')
            self.printer.session.request.side_effect = replies
            with self.assertRaises(PrinterError):
                self.printer.get_printer_state()

    def test_malformed_schema_is_printer_error(self):
        mutations = [
            (0, None), (0, []), (0, {}), (0, {'current': []}), (0, {'current': {'state': None}}),
            (1, []), (1, {'state': None}), (1, {'state': {'flags': []}}),
            (2, []), (2, {'progress': [], 'job': {}}), (2, {'job': {'file': []}}),
        ]
        for index, bad in mutations:
            with self.subTest(index=index, bad=bad):
                values = readings()
                values[index] = bad
                self.feed(values)
                with self.assertRaises(PrinterError):
                    self.printer.get_printer_state()
        for key, value in [('flags', {'operational': 'false'}), ('temperature', {'tool0': {'actual': 'hot'}})]:
            values = readings()
            if key == 'flags':
                values[1]['state']['flags'].update(value)
            else:
                values[1][key] = value
            self.feed(values)
            with self.assertRaises(PrinterError):
                self.printer.get_printer_state()

    def test_health_catches_malformed_response(self):
        self.feed([None])
        monitor = health.HealthMonitor(self.printer)
        with patch.object(monitor.camera, 'check', return_value=('ok', 'test')), \
             patch.object(health, 'check_pi', return_value=('ok', 'test')):
            report = monitor.check_all()
        self.assertFalse(report['ok'])
        self.assertEqual(report['health']['octoprint'], 'error')

    def test_nullable_idle_job_and_temperature(self):
        values = readings()
        values[1]['temperature']['tool0'] = {'actual': None, 'target': None}
        values[2] = {'progress': None, 'job': {'file': {'name': None}}}
        self.feed(values)
        result = self.printer.get_printer_state()
        self.assertIsNone(result['progress_pct'])
        self.assertIsNone(result['file'])

    def test_file_listing_rejects_bad_schema(self):
        for bad in [[], {}, {'files': None}, {'files': [None]},
                    {'files': [{'type': 'folder', 'children': 'bad'}]},
                    {'files': [{'type': 'machinecode', 'name': 'part.gcode'}]}]:
            self.feed([bad])
            with self.assertRaises(PrinterError):
                self.printer.list_files()
        self.feed([{'files': [{'type': 'folder', 'children': [
            {'type': 'machinecode', 'name': 'part.gcode', 'path': 'folder/part.gcode', 'size': 10}]}]}])
        self.assertEqual(self.printer.list_files()[0]['path'], 'folder/part.gcode')

    def test_upload_requires_returned_path(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'part.gcode'
            file.write_text('; mock only')
            for data in [None, {}, {'files': []}, {'files': {'local': {}}}]:
                self.feed([data])
                with self.assertRaises(PrinterError):
                    self.printer.upload_file(str(file))
            self.feed([{'files': {'local': {'path': 'part.gcode'}}}])
            self.assertEqual(self.printer.upload_file(str(file)), 'part.gcode')

    def test_mock_and_real_start_readiness_match(self):
        for state in ['Printing', 'Paused', 'Error', 'Closed', 'Operational']:
            mock = MockPrinter()
            mock.state = state
            snapshot = mock.get_printer_state()
            for printer in [mock, self.printer]:
                with patch.object(printer, 'get_printer_state', return_value=snapshot), \
                     patch.object(printer, '_request', create=True) as command:
                    if state == 'Operational':
                        printer.start_print('part.gcode')
                    else:
                        with self.assertRaises(PrintBlocked):
                            printer.start_print('part.gcode')
                        command.assert_not_called()
                with patch.object(printer, 'get_printer_state', return_value=snapshot), \
                     patch.object(printer, 'upload_file', return_value='part.gcode') as upload, \
                     patch.object(printer, 'start_print'):
                    if state == 'Operational':
                        printer.print_file('part.gcode')
                        upload.assert_called_once()
                    else:
                        with self.assertRaises(PrintBlocked):
                            printer.print_file('part.gcode')
                        upload.assert_not_called()

    def test_mock_and_real_resume_guard_and_force(self):
        for printer in [MockPrinter(), self.printer]:
            for temp in [{'actual': 25, 'target': 210}, {'actual': 210, 'target': 0}]:
                with patch.object(printer, 'get_printer_state', return_value={'temps': {'tool0': temp}}), \
                     patch.object(printer, '_request', create=True) as command:
                    with self.assertRaises(ResumeBlocked):
                        printer.resume_printer()
                    command.assert_not_called()
                    printer.resume_printer(force=True)
            with patch.object(printer, 'get_printer_state', side_effect=AssertionError('guard bypass')), \
                 patch.object(printer, '_request', create=True):
                printer.start_print('part.gcode', force=True)

    def test_snapshot_network_errors_and_bad_content(self):
        camera = SnapshotCamera(url='http://camera.test', timeout=2)
        import requests
        with patch.object(camera.session, 'get', side_effect=requests.Timeout('mock')):
            with self.assertRaises(CameraError):
                camera.get_frame()
        with patch.object(camera.session, 'get', return_value=Mock(status_code=200, content=b'bad')):
            with self.assertRaises(CameraError):
                camera.get_frame()


if __name__ == '__main__':
    unittest.main()

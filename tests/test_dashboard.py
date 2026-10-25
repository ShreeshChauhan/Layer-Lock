"""Dashboard lifecycle and persistent incident/event integration."""
import unittest
from contextlib import closing
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient
from backend import incident_db
from backend import main
from backend.telemetry import PrinterMonitor
from tests import test_api as api_tests


class DashboardTests(unittest.TestCase):
    tearDown = api_tests.TestLayerLockAPI.tearDown
    post_reading = api_tests.TestLayerLockAPI.post_reading

    def setUp(self):
        api_tests.TestLayerLockAPI.setUp(self)
        main.printer.mock_idle = False
        files_patch = patch.object(main.printer, 'mock_files', {
            'mock_part.gcode': {'name': 'mock_part.gcode', 'path': 'mock_part.gcode', 'size': 1234, 'date': 0}})
        files_patch.start()
        self.addCleanup(files_patch.stop)
        main.printer.mock_file = 'mock_part.gcode'
        self.monitor_patch = patch.object(main, 'monitor', PrinterMonitor(main.printer))
        self.monitor_patch.start()
        self.addCleanup(self.monitor_patch.stop)

    def test_dashboard_returns_telemetry_and_deduplicated_events(self):
        first = self.client.get('/dashboard').json()
        second = self.client.get('/dashboard').json()
        self.assertEqual(first['printer']['print_time_left'], 1624)
        self.assertEqual(first['printer']['temperatures']['bed']['target'], 60)
        self.assertEqual(len(first['temperature_history']), 1)
        self.assertEqual(first['events'], second['events'])

    def test_empty_timeout_message_is_visible_and_does_not_repeat_events(self):
        with patch.object(main.printer, 'get_status', new_callable=AsyncMock,
                          side_effect=httpx.ConnectTimeout('')):
            first = self.client.get('/dashboard').json()
            main.monitor.last_sample = 0
            second = self.client.get('/dashboard').json()
        self.assertIn('Unable to reach the printer', first['printer_error'])
        self.assertEqual(first['printer_error'], second['printer_error'])
        failures = [event for event in second['events'] if event['message'] == 'Printer telemetry unavailable']
        self.assertEqual(len(failures), 1)
        main.monitor.last_sample = 0
        restored = self.client.get('/dashboard').json()
        self.assertIsNone(restored['printer_error'])
        self.assertTrue(any(event['message'] == 'Printer telemetry connection restored' for event in restored['events']))

    def test_connect_endpoint_records_request_and_acceptance(self):
        with patch.object(main.printer, 'connect', new_callable=AsyncMock,
                          return_value={'success': True, 'message': 'Connect command accepted', 'simulated': True}) as connect:
            response = self.client.post('/printer/connect')
        self.assertEqual(response.status_code, 200)
        connect.assert_awaited_once()
        events = self.client.get('/dashboard').json()['events']
        self.assertTrue(any(event['message'] == 'Connect command accepted' for event in events))

    def test_vision_toggle_never_arms_and_disabled_readings_are_rejected(self):
        self.client.post('/mode/live')
        with patch.object(main.vision_service, 'enable', new_callable=AsyncMock) as enable:
            self.assertEqual(self.client.post('/vision/enable').status_code, 200)
            enable.assert_awaited_once()
        self.assertFalse(self.client.get('/risk/status').json()['armed'])
        self.assertEqual(self.client.post('/live/update', json={'camera_confidence': 0}).status_code, 200)
        self.assertEqual(self.client.post('/risk/arm').status_code, 200)
        self.assertEqual(self.client.post('/vision/disable').status_code, 200)
        self.assertFalse(self.client.get('/risk/status').json()['armed'])
        self.assertEqual(self.client.post('/live/update', json={'camera_confidence': 99}).status_code, 409)
        self.assertIsNone(self.client.get('/dashboard').json()['sensor']['updated_at'])

    def test_vision_missing_dependencies_reports_failure_without_spawning(self):
        self.client.post('/mode/live')
        with patch.object(main.vision_service, 'prerequisites', return_value='Model weights are missing'), \
                patch('backend.vision_service.asyncio.create_subprocess_exec') as spawn:
            result = self.client.post('/vision/enable')
            self.assertEqual(result.status_code, 503)
            self.assertIn('Model weights', result.json()['detail'])
            spawn.assert_not_called()

    def test_known_detector_exit_blocks_arming_despite_recent_reading(self):
        self.client.post('/mode/live')
        self.client.post('/live/update', json={'camera_confidence': 0})
        main.vision_service.error = 'Vision exited'
        self.assertEqual(self.client.post('/risk/arm').status_code, 409)

    def test_homing_routes_require_idle_and_log_accepted_commands(self):
        for target in ('head', 'bed'):
            self.assertEqual(self.client.post(f'/printer/home/{target}').status_code, 409)
        main.printer.mock_idle = True
        for target in ('head', 'bed'):
            self.assertEqual(self.client.post(f'/printer/home/{target}').status_code, 200)
        events = self.client.get('/dashboard').json()['events']
        self.assertTrue(any('Head homing command accepted' == event['message'] for event in events))
        self.assertTrue(any('Bed homing command accepted' == event['message'] for event in events))

    def test_delete_requires_idle_and_existing_file_without_confirmation(self):
        path = '/printer/files?path=mock_part.gcode'
        self.assertEqual(self.client.delete(path).status_code, 409)
        self.assertEqual(self.client.delete(path + '&confirmed=true').status_code, 409)
        main.printer.mock_idle = True
        self.assertEqual(self.client.delete(path).status_code, 200)
        self.assertEqual(self.client.get('/printer/files').json()['files'], [])
        self.assertEqual(self.client.delete(path + '&confirmed=true').status_code, 409)
        self.assertTrue(any('File removed' in event['message'] for event in self.client.get('/dashboard').json()['events']))

    def test_delete_other_file_during_print_preserves_current_job(self):
        result = self.client.post('/printer/files/upload?filename=other.gcode', content=b'G28\n')
        path = result.json()['file']['path']
        self.assertEqual(self.client.delete('/printer/files', params={'path': path}).status_code, 200)
        self.assertEqual(self.client.delete('/printer/files', params={'path': 'mock_part.gcode'}).status_code, 409)
        status = self.client.get('/printer/status').json()
        self.assertTrue(status['printing'])
        self.assertEqual(status['file_path'], 'mock_part.gcode')

    def test_manual_pause_and_cancel_record_file_time_and_reason(self):
        self.assertEqual(self.client.post('/printer/pause').status_code, 200)
        self.assertEqual(self.client.post('/printer/cancel').status_code, 200)
        history = self.client.get('/dashboard').json()['print_history']
        self.assertEqual([row['action'] for row in history], ['cancel', 'pause'])
        for row in history:
            self.assertEqual(row['reason'], 'manual')
            self.assertEqual(row['file_name'], 'mock_part.gcode')
            self.assertIn('T', row['timestamp'])
            self.assertIn('+00:00', row['timestamp'])
            self.assertEqual(row['print_time'], 1200)

    def test_old_manual_commands_are_recovered_once(self):
        with closing(incident_db.connect()) as connection:
            connection.execute("DELETE FROM schema_migrations WHERE name='manual_action_history'")
            connection.commit()
        incident_db.save_event('Selected print: old.gcode', False)
        incident_db.save_event('Cancel command accepted', False)
        incident_db.init_db()
        incident_db.init_db()
        history = incident_db.get_print_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['file_name'], 'old.gcode')
        self.assertEqual(history[0]['reason'], 'manual')
        self.assertIsNone(history[0]['print_time'])

    def test_automatic_pause_history_is_not_duplicated_by_polling(self):
        self.client.get('/dashboard')
        self.client.post('/risk/arm')
        self.post_reading(runout=True)
        main.monitor.last_sample = 0
        history = self.client.get('/dashboard').json()['print_history']
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['reason'], 'automatic')

    def test_external_pause_is_recorded_without_guessing_initiator(self):
        self.client.get('/dashboard')
        main.printer.mock_paused = True
        main.monitor.last_sample = 0
        history = self.client.get('/dashboard').json()['print_history']
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['reason'], 'external / unknown')
        main.monitor.last_sample = 0
        self.assertEqual(len(self.client.get('/dashboard').json()['print_history']), 1)

    def test_reviewed_resume_keeps_history_and_rearms_lifecycle(self):
        self.client.post('/risk/arm')
        failure = self.post_reading(runout=True).json()
        incident = self.client.get('/dashboard').json()['active_incident']
        self.assertEqual(incident['id'], failure['incident_id'])
        self.assertEqual(incident['file_name'], 'mock_part.gcode')
        self.assertEqual(self.client.post('/printer/resume', json={}).status_code, 409)
        resumed = self.client.post('/printer/resume', json={'confirmed': True})
        self.assertEqual(resumed.status_code, 200)
        self.assertFalse(main.risk_engine.paused)
        self.assertTrue(main.risk_engine.armed)
        row = self.client.get('/incidents').json()['incidents'][0]
        self.assertEqual(row['resolution'], 'resume_requested')
        self.assertIsNotNone(row['resolved_at'])
        self.assertTrue(self.post_reading(runout=True).json()['paused'])
        self.assertEqual(len(self.client.get('/incidents').json()['incidents']), 2)

    def test_cancel_start_and_confirmation(self):
        self.client.post('/risk/arm')
        self.post_reading(runout=True)
        self.assertEqual(self.client.post('/printer/cancel', json={'confirmed': True}).status_code, 200)
        self.assertFalse(main.risk_engine.armed)
        self.assertEqual(self.client.get('/incidents').json()['incidents'][0]['resolution'], 'cancel_requested')
        self.assertEqual(self.client.post('/printer/start', json={'path': 'mock_part.gcode'}).status_code, 409)
        self.assertEqual(self.client.post('/printer/start', json={'path': 'mock_part.gcode', 'confirmed': True}).status_code, 200)
        self.assertEqual(self.client.get('/printer/status').json()['state'], 'Printing')
        self.assertTrue(any('Start command accepted' in row['message'] for row in incident_db.get_events()))

    def test_simulation_cannot_act_on_real_printer(self):
        with patch('backend.printer.PRINTER_TYPE', 'octoprint'), patch.object(main.printer, 'pause', new_callable=AsyncMock) as pause:
            self.assertEqual(self.post_reading(runout=True).status_code, 409)
            pause.assert_not_awaited()

    def test_failed_pause_is_logged_and_notified(self):
        self.client.post('/risk/arm')
        with patch.object(main.printer, 'pause', new_callable=AsyncMock, side_effect=httpx.ConnectError('offline')):
            self.assertEqual(self.post_reading(runout=True).status_code, 503)
        row = self.client.get('/incidents').json()['incidents'][0]
        self.assertFalse(row['pause_success'])
        self.assertTrue(row['notification_sent'])
        self.mock_discord.assert_awaited_once()

    def test_idle_printer_does_not_trigger_failure_pause(self):
        main.printer.mock_idle = True
        self.client.post('/risk/arm')
        result = self.post_reading(runout=True).json()
        self.assertIsNone(result['pause_result'])
        self.assertEqual(incident_db.get_incident_stats()['total'], 0)

    def test_telemetry_failure_does_not_fake_healthy_values(self):
        self.client.get('/dashboard')
        with patch.object(main.printer, 'get_status', new_callable=AsyncMock, side_effect=httpx.ConnectError('offline')):
            main.monitor.last_sample = 0
            result = self.client.get('/dashboard').json()
        self.assertIsNotNone(result['printer_error'])
        self.assertEqual(result['printer']['state'], 'Printing')  # last known, explicitly unavailable

    def test_rejected_resume_keeps_incident_pending(self):
        self.client.post('/risk/arm')
        self.post_reading(runout=True)
        with patch.object(main.printer, 'resume', new_callable=AsyncMock, side_effect=httpx.ConnectError('offline')):
            result = self.client.post('/printer/resume', json={'confirmed': True})
        self.assertEqual(result.status_code, 503)
        self.assertTrue(main.risk_engine.paused)
        self.assertEqual(incident_db.get_incidents()[0]['resolution'], 'pending')

    def test_live_incident_resume_requires_fresh_vision(self):
        self.client.post('/mode/live')
        self.post_reading(camera=10, endpoint='/live/update')
        self.client.post('/risk/arm')
        self.post_reading(runout=True, endpoint='/live/update')
        main.latest_sensor['updated_at'] -= 20
        self.assertEqual(self.client.post('/printer/resume', json={'confirmed': True}).status_code, 409)
        self.post_reading(camera=10, endpoint='/live/update')
        self.assertEqual(self.client.post('/printer/resume', json={'confirmed': True}).status_code, 200)

    def test_external_state_changes_are_recorded_once(self):
        self.client.get('/dashboard')
        main.printer.mock_paused = True
        main.monitor.last_sample = 0
        self.client.get('/dashboard')
        self.client.get('/dashboard')
        self.assertEqual(sum(row['message'] == 'Printer state: Paused' for row in incident_db.get_events()), 1)

    def test_upload_select_print_pause_resume_cancel(self):
        main.printer.mock_idle = True
        upload = self.client.post('/printer/files/upload?filename=new.gcode', content=b'G28\n')
        self.assertEqual(upload.status_code, 201)
        path = upload.json()['file']['path']
        self.assertIn(path, [file['path'] for file in self.client.get('/printer/files').json()['files']])
        self.assertEqual(self.client.get('/printer/status').json()['state'], 'Operational')
        self.assertEqual(self.client.post('/printer/start', json={'path': path, 'confirmed': True}).status_code, 200)
        self.assertEqual(self.client.get('/printer/status').json()['file'], path)
        self.assertEqual(self.client.post('/printer/pause').status_code, 200)
        self.assertEqual(self.client.get('/printer/status').json()['state'], 'Paused')
        self.assertEqual(self.client.post('/printer/resume', json={'confirmed': True}).status_code, 200)
        self.assertEqual(self.client.get('/printer/status').json()['state'], 'Printing')
        self.assertEqual(self.client.post('/printer/cancel', json={'confirmed': True}).status_code, 200)
        self.assertEqual(self.client.get('/printer/status').json()['state'], 'Operational')
        self.assertIn(path, [file['path'] for file in self.client.get('/printer/files').json()['files']])

    def test_invalid_empty_and_oversized_uploads_do_not_reach_printer(self):
        with patch.object(main.printer, 'upload_file', new_callable=AsyncMock) as upload:
            for name in ['part.stl', '../part.gcode', 'folder/part.gcode', 'folder\\part.gcode']:
                result = self.client.post('/printer/files/upload', params={'filename': name}, content=b'G28')
                self.assertEqual(result.status_code, 400)
            self.assertEqual(self.client.post('/printer/files/upload?filename=part.gcode', content=b'').status_code, 400)
            with patch.object(main, 'MAX_UPLOAD_BYTES', 3):
                self.assertEqual(self.client.post('/printer/files/upload?filename=part.gcode', content=b'G28\n').status_code, 413)
            upload.assert_not_awaited()

    def test_duplicate_upload_preserves_existing_file(self):
        original = dict(main.printer.mock_files['mock_part.gcode'])
        result = self.client.post('/printer/files/upload?filename=mock_part.gcode', content=b'G28\n')
        self.assertEqual(result.status_code, 201)
        self.assertNotEqual(result.json()['file']['path'], 'mock_part.gcode')
        self.assertEqual(main.printer.mock_files['mock_part.gcode'], original)

    def test_upload_failure_is_reported_without_starting_print(self):
        main.printer.mock_idle = True
        with patch.object(main.printer, 'upload_file', new_callable=AsyncMock, side_effect=httpx.ConnectError('offline')):
            self.assertEqual(self.client.post('/printer/files/upload?filename=new.gcode', content=b'G28\n').status_code, 503)
        self.assertTrue(main.printer.mock_idle)


if __name__ == '__main__':
    unittest.main()

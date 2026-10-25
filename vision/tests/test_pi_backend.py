"""Exercise the real backend contract with an in-process client and mock printer."""
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import incident_db
import main as backend
from vision.src import pi_inference as pi


class PiBackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.db_patch = patch.object(incident_db, 'DB_PATH', Path(self.temporary.name) / 'incidents.db')
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        incident_db.init_db()
        backend.mode = 'simulation'
        backend.latest_sensor = dict(camera_confidence=0, filament_runout=False, source='simulation', updated_at=None)
        backend.risk_engine.reset_simulation()
        self.pause_patch = patch.object(backend.printer, 'pause', new_callable=AsyncMock)
        self.pause = self.pause_patch.start()
        self.addCleanup(self.pause_patch.stop)
        self.notify_patch = patch.object(backend, 'send_discord_alert', new_callable=AsyncMock)
        self.notify = self.notify_patch.start()
        self.addCleanup(self.notify_patch.stop)
        self.client = TestClient(backend.app)
        self.addCleanup(self.client.close)
        self.requests = []

    def transport(self, request, timeout):
        self.requests.append((request.get_method(), request.full_url, timeout))
        response = self.client.post('/live/update', json=json.loads(request.data))
        if response.status_code >= 400:
            raise urllib.error.HTTPError(request.full_url, response.status_code, response.text, {}, None)
        return io.BytesIO(response.content)

    def test_simulation_rejection_does_not_change_mode_or_arm(self):
        with patch.object(pi.urllib.request, 'urlopen', side_effect=self.transport):
            with self.assertRaises(urllib.error.HTTPError) as error:
                pi.publish_result({'confidence': 1}, 'http://backend.test')
        self.assertEqual(error.exception.code, 409)
        error.exception.close()
        self.assertEqual(backend.mode, 'simulation')
        self.assertFalse(backend.risk_engine.armed)
        self.assertIsNone(backend.latest_sensor['updated_at'])
        self.pause.assert_not_awaited()

    def test_live_readings_refresh_health_without_arming_or_pausing(self):
        # Mode selection is an operator action, not performed by the publisher.
        self.assertEqual(self.client.post('/mode/live').status_code, 200)
        self.assertEqual(self.client.get('/sensors/health').json()['status'], 'WAITING')
        with patch.object(pi.urllib.request, 'urlopen', side_effect=self.transport):
            for confidence in [.6559, 1]:
                result = pi.publish_result({'confidence': confidence, 'failure_type': 'spaghetti'},
                                           'http://backend.test', timeout=2)
                self.assertFalse(result['armed'])
                self.assertIsNone(result['pause_result'])
        self.assertEqual(self.client.get('/sensors/health').json()['status'], 'CONNECTED')
        self.assertEqual(backend.latest_sensor['camera_confidence'], 100)
        self.assertFalse(backend.latest_sensor['filament_runout'])
        self.assertEqual(self.requests, [('POST', 'http://backend.test/live/update', 2)] * 2)
        self.pause.assert_not_awaited()
        self.notify.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()

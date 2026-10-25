
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend import main
from backend import incident_db
from backend.vision_service import VisionService
from backend.printer import printer
from backend.risk_engine import risk_engine


class TestLayerLockAPI(unittest.TestCase):

    def setUp(self):
        # Create an isolated database for each test.
        self.temp_dir = tempfile.TemporaryDirectory()

        self.db_patch = patch.object(
            incident_db,
            "DB_PATH",
            Path(self.temp_dir.name) / "test_incidents.db"
        )
        self.db_patch.start()
        incident_db.init_db()

        # Never send real Discord messages during tests.
        self.discord_patch = patch.object(
            main,
            "send_discord_alert",
            new_callable=AsyncMock,
            return_value=True
        )
        self.mock_discord = self.discord_patch.start()

        # Force mock printer mode.
        self.printer_type_patch = patch(
            "backend.printer.PRINTER_TYPE",
            "mock"
        )
        self.printer_type_patch.start()
        self.vision_patch = patch.object(main, 'vision_service', VisionService())
        self.vision_patch.start()

        # Reset all shared backend state.
        main.mode = "simulation"
        main.latest_sensor = {
            "camera_confidence": 12.0,
            "filament_runout": False,
            "source": "simulation",
            "updated_at": None
        }

        risk_engine.reset_simulation()
        risk_engine.events.clear()
        printer.mock_paused = False

        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        self.vision_patch.stop()
        self.discord_patch.stop()
        self.printer_type_patch.stop()
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def post_reading(
        self,
        camera=10,
        runout=False,
        endpoint="/risk/update"
    ):
        return self.client.post(
            endpoint,
            json={
                "camera_confidence": camera,
                "filament_runout": runout
            }
        )

    def test_backend_health(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["status"],
            "healthy"
        )

    def test_initial_mode_is_simulation(self):
        response = self.client.get("/mode")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["mode"],
            "simulation"
        )

    def test_invalid_mode_rejected(self):
        response = self.client.post(
            "/mode/invalid"
        )

        self.assertEqual(response.status_code, 400)

    def test_invalid_sensor_confidence_rejected(self):
        response = self.post_reading(camera=150)

        self.assertEqual(response.status_code, 422)

    def test_low_risk_does_not_pause(self):
        self.client.post("/risk/arm")

        response = self.post_reading(camera=15)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["paused"])

        status = self.client.get(
            "/printer/status"
        ).json()

        self.assertEqual(
            status["state"],
            "Printing"
        )

        self.mock_discord.assert_not_awaited()

    def test_filament_runout_full_pipeline(self):
        self.client.post("/risk/arm")

        response = self.post_reading(
            camera=10,
            runout=True
        )

        self.assertEqual(response.status_code, 200)

        result = response.json()

        self.assertTrue(result["paused"])
        self.assertEqual(result["risk_score"], 100)
        self.assertTrue(
            result["pause_result"]["success"]
        )
        self.assertTrue(result["notification_sent"])
        self.assertIn("incident_id", result)

        self.mock_discord.assert_awaited_once()

        printer_status = self.client.get(
            "/printer/status"
        ).json()

        self.assertEqual(
            printer_status["state"],
            "Paused"
        )

        history = self.client.get(
            "/incidents"
        ).json()

        self.assertEqual(history["stats"]["total"], 1)
        self.assertEqual(history["stats"]["paused"], 1)
        self.assertEqual(history["stats"]["notified"], 1)

        incident = history["incidents"][0]

        self.assertEqual(
            incident["failure_type"],
            "Filament Runout"
        )
        self.assertEqual(
            incident["id"],
            result["incident_id"]
        )

    def test_camera_failure_after_five_seconds(self):
        self.client.post("/risk/arm")

        with patch(
            "backend.risk_engine.time.monotonic"
        ) as mock_clock:

            mock_clock.return_value = 100.0

            first = self.post_reading(
                camera=95
            )

            mock_clock.return_value = 104.0

            second = self.post_reading(
                camera=95
            )

            mock_clock.return_value = 106.0

            third = self.post_reading(
                camera=95
            )

        self.assertFalse(first.json()["paused"])
        self.assertFalse(second.json()["paused"])
        self.assertTrue(third.json()["paused"])

        history = self.client.get(
            "/incidents"
        ).json()

        self.assertEqual(
            history["incidents"][0]["failure_type"],
            "Camera Failure"
        )

        self.mock_discord.assert_awaited_once()

    def test_reset_after_failure(self):
        self.client.post("/risk/arm")

        self.post_reading(
            camera=10,
            runout=True
        )

        response = self.client.post(
            "/simulation/reset"
        )

        self.assertEqual(response.status_code, 200)

        result = response.json()

        self.assertFalse(result["paused"])
        self.assertFalse(result["armed"])
        self.assertEqual(result["state"], "IDLE")

        printer_status = self.client.get(
            "/printer/status"
        ).json()

        self.assertEqual(
            printer_status["state"],
            "Printing"
        )

        # Reset should not erase historical incidents.
        history = self.client.get(
            "/incidents"
        ).json()

        self.assertEqual(
            history["stats"]["total"],
            1
        )

    def test_live_update_rejected_in_simulation(self):
        response = self.post_reading(
            endpoint="/live/update"
        )

        self.assertEqual(response.status_code, 409)

    def test_live_mode_requires_fresh_reading(self):
        switch = self.client.post(
            "/mode/live"
        )

        self.assertEqual(switch.status_code, 200)

        arm_before_data = self.client.post(
            "/risk/arm"
        )

        self.assertEqual(
            arm_before_data.status_code,
            409
        )

        reading = self.post_reading(
            camera=15,
            endpoint="/live/update"
        )

        self.assertEqual(reading.status_code, 200)

        arm_after_data = self.client.post(
            "/risk/arm"
        )

        self.assertEqual(
            arm_after_data.status_code,
            200
        )
        self.assertTrue(
            arm_after_data.json()["armed"]
        )

    def test_stale_live_data_disarms_monitoring(self):
        self.client.post("/mode/live")

        self.post_reading(
            camera=15,
            endpoint="/live/update"
        )

        self.client.post("/risk/arm")

        self.assertTrue(risk_engine.armed)

        # Simulate the last reading arriving
        # more than 10 seconds ago.
        main.latest_sensor["updated_at"] -= 15

        response = self.client.get(
            "/sensors/health"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["status"],
            "STALE"
        )

        self.assertFalse(risk_engine.armed)

    def test_discord_failure_still_records_incident(self):
        self.mock_discord.return_value = False

        self.client.post("/risk/arm")

        response = self.post_reading(
            camera=10,
            runout=True
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["paused"])
        self.assertFalse(
            response.json()["notification_sent"]
        )

        history = self.client.get(
            "/incidents"
        ).json()

        self.assertEqual(history["stats"]["total"], 1)
        self.assertEqual(history["stats"]["notified"], 0)

    def test_manual_pause(self):
        response = self.client.post(
            "/printer/pause"
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])

        printer_status = self.client.get(
            "/printer/status"
        ).json()

        self.assertEqual(
            printer_status["state"],
            "Paused"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

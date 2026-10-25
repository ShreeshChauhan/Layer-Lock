
import unittest
from unittest.mock import patch

from backend.risk_engine import RiskEngine


class TestRiskEngine(unittest.TestCase):

    def setUp(self):
        # Each test gets its own independent risk engine.
        self.engine = RiskEngine()

    def test_starts_disarmed(self):
        status = self.engine.status()

        self.assertFalse(status["armed"])
        self.assertFalse(status["paused"])
        self.assertEqual(status["state"], "IDLE")

    def test_low_risk_does_not_pause(self):
        self.engine.arm()

        status, should_pause = self.engine.process(
            camera=15,
            filament_runout=False
        )

        self.assertEqual(status["risk_score"], 15)
        self.assertFalse(should_pause)
        self.assertEqual(status["state"], "WATCHING")

    def test_disarmed_system_does_not_pause(self):
        status, should_pause = self.engine.process(
            camera=95,
            filament_runout=True
        )

        self.assertFalse(should_pause)
        self.assertFalse(status["armed"])

    def test_filament_runout_pauses_immediately(self):
        self.engine.arm()

        status, should_pause = self.engine.process(
            camera=10,
            filament_runout=True
        )

        self.assertTrue(should_pause)
        self.assertEqual(status["risk_score"], 100)
        self.assertEqual(status["state"], "WARNING")

        self.engine.confirm_pause()

        self.assertTrue(self.engine.status()["paused"])
        self.assertEqual(self.engine.status()["state"], "PAUSED")

    
    def test_camera_failure_requires_five_seconds(self):
        self.engine.arm()

        with patch("backend.risk_engine.time.monotonic") as mock_time:
            mock_time.return_value = 100.0

            _, first_pause = self.engine.process(
                camera=95,
                filament_runout=False
            )

            mock_time.return_value = 104.9

            _, second_pause = self.engine.process(
                camera=95,
                filament_runout=False
            )

            mock_time.return_value = 105.1

            _, third_pause = self.engine.process(
                camera=95,
                filament_runout=False
            )

        self.assertFalse(first_pause)
        self.assertFalse(second_pause)
        self.assertTrue(third_pause)


    
    def test_camera_risk_must_be_continuous(self):
        self.engine.arm()

        with patch("backend.risk_engine.time.monotonic") as mock_time:
            mock_time.return_value = 100.0
            _, first = self.engine.process(95, False)

            mock_time.return_value = 103.0
            _, second = self.engine.process(20, False)

            mock_time.return_value = 110.0
            _, third = self.engine.process(95, False)

            mock_time.return_value = 114.0
            _, fourth = self.engine.process(95, False)

        self.assertFalse(first)
        self.assertFalse(second)
        self.assertFalse(third)
        self.assertFalse(fourth)


    def test_reset_clears_paused_state(self):
        self.engine.arm()
        self.engine.process(10, True)
        self.engine.confirm_pause()

        result = self.engine.reset_simulation()

        self.assertFalse(result["paused"])
        self.assertFalse(result["armed"])
        self.assertEqual(result["risk_score"], 0)
        self.assertEqual(result["state"], "IDLE")

    def test_cannot_arm_while_paused(self):
        self.engine.arm()
        self.engine.confirm_pause()

        result = self.engine.arm()

        self.assertFalse(result["armed"] is False)
        self.assertTrue(result["paused"])

    def test_risk_score_stays_in_range(self):
        self.assertEqual(
            self.engine.calculate_risk(150), 100
        )

        self.assertEqual(
            self.engine.calculate_risk(-20), 0
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

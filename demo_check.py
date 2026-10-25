
"""
Print Guardian — Pre-Demo Reliability Check

Run:
    python demo_check.py

Uses:
    - FastAPI TestClient
    - Mock printer
    - Mock Discord notification
    - Temporary SQLite database

No running backend server is required.
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import incident_db
import main
import printer as printer_module
from printer import printer
from risk_engine import risk_engine


class DemoCheck:
    def __init__(self, client):
        self.client = client
        self.passed = 0
        self.failed = 0

    def check(self, label, condition, details=""):
        if condition:
            self.passed += 1
            print(f"[PASS] {label}")
        else:
            self.failed += 1
            print(f"[FAIL] {label}")

            if details:
                print(f"       {details}")

    def post(self, endpoint, payload=None):
        if payload is None:
            return self.client.post(endpoint)

        return self.client.post(
            endpoint,
            json=payload
        )

    def run(self):
        print()
        print("=" * 55)
        print(" PRINT GUARDIAN — PRE-DEMO RELIABILITY CHECK")
        print("=" * 55)
        print()

        # -------------------------------------
        # 1. Backend health
        # -------------------------------------

        response = self.client.get("/health")

        self.check(
            "Backend health endpoint",
            response.status_code == 200
            and response.json().get("status") == "healthy"
        )

        # -------------------------------------
        # 2. Simulation mode
        # -------------------------------------

        response = self.client.get("/mode")

        self.check(
            "Simulation mode active",
            response.status_code == 200
            and response.json().get("mode") == "simulation"
        )

        # -------------------------------------
        # 3. Initial printer state
        # -------------------------------------

        response = self.client.get("/printer/status")
        printer_status = response.json()

        self.check(
            "Mock printer is printing",
            response.status_code == 200
            and printer_status.get("state") == "Printing"
            and printer_status.get("simulated") is True
        )

        # -------------------------------------
        # 4. Arm monitoring
        # -------------------------------------

        response = self.post("/risk/arm")

        self.check(
            "Monitoring can be armed",
            response.status_code == 200
            and response.json().get("armed") is True
        )

        # -------------------------------------
        # 5. Normal sensor reading
        # -------------------------------------

        normal_reading = {
            "camera_confidence": 15,
            "filament_runout": False
        }

        response = self.post(
            "/risk/update",
            normal_reading
        )

        self.check(
            "Normal readings do not trigger pause",
            response.status_code == 200
            and response.json().get("paused") is False
            and response.json().get("pause_result") is None
        )

        # -------------------------------------
        # 6. Filament runout
        # -------------------------------------

        failure_reading = {
            "camera_confidence": 10,
            "filament_runout": True
        }

        response = self.post(
            "/risk/update",
            failure_reading
        )

        failure_result = (
            response.json()
            if response.status_code == 200
            else {}
        )

        self.check(
            "Filament runout triggers automatic pause",
            response.status_code == 200
            and failure_result.get("paused") is True
            and failure_result.get("risk_score") == 100
            and bool(
                (failure_result.get("pause_result") or {})
                .get("success")
            ),
            f"HTTP status: {response.status_code}"
        )

        # -------------------------------------
        # 7. Printer is paused
        # -------------------------------------

        response = self.client.get("/printer/status")

        self.check(
            "Printer state changes to Paused",
            response.status_code == 200
            and response.json().get("state") == "Paused"
        )

        # -------------------------------------
        # 8. Incident history
        # -------------------------------------

        response = self.client.get("/incidents")

        history = (
            response.json()
            if response.status_code == 200
            else {}
        )

        incidents = history.get("incidents", [])

        self.check(
            "Failure saved to SQLite",
            response.status_code == 200
            and len(incidents) == 1
            and incidents[0].get("failure_type")
                == "Filament Runout"
            and bool(incidents[0].get("pause_success"))
        )

        # -------------------------------------
        # 9. Discord notification result
        # -------------------------------------

        self.check(
            "Discord notification pipeline invoked",
            failure_result.get("notification_sent") is True
        )

        # -------------------------------------
        # 10. Reset simulation
        # -------------------------------------

        response = self.post("/simulation/reset")

        reset_result = (
            response.json()
            if response.status_code == 200
            else {}
        )

        self.check(
            "Simulation reset succeeds",
            response.status_code == 200
            and reset_result.get("paused") is False
            and reset_result.get("armed") is False
        )

        # -------------------------------------
        # 11. Printer returns to printing
        # -------------------------------------

        response = self.client.get("/printer/status")

        self.check(
            "Mock printer returns to Printing",
            response.status_code == 200
            and response.json().get("state") == "Printing"
        )

        # -------------------------------------
        # 12. History survives reset
        # -------------------------------------

        response = self.client.get("/incidents")

        history_after_reset = (
            response.json()
            if response.status_code == 200
            else {}
        )

        self.check(
            "Incident history survives reset",
            response.status_code == 200
            and history_after_reset.get(
                "stats", {}
            ).get("total") == 1
        )

        # -------------------------------------
        # Final report
        # -------------------------------------

        print()
        print("=" * 55)
        print(" DEMO CHECK RESULTS")
        print("=" * 55)

        print(f"Passed: {self.passed}")
        print(f"Failed: {self.failed}")
        print(f"Total:  {self.passed + self.failed}")

        print()

        if self.failed == 0:
            print("SUCCESS: Core simulation checks passed.")
        else:
            print("WARNING: Fix failed checks before the demo.")

        print("=" * 55)

        return self.failed == 0


def main_check():
    # Each run gets a fresh temporary database.
    with tempfile.TemporaryDirectory() as temp_dir:
        database_path = (
            Path(temp_dir) / "demo_check.db"
        )

        with (
            patch.object(
                incident_db,
                "DB_PATH",
                database_path
            ),
            patch.object(
                printer_module,
                "PRINTER_TYPE",
                "mock"
            ),
            patch.object(
                main,
                "send_discord_alert",
                new_callable=AsyncMock,
                return_value=True
            )
        ):
            incident_db.init_db()

            # Reset shared application state.
            main.mode = "simulation"

            main.latest_sensor = {
                "camera_confidence": 12.0,
                "filament_runout": False,
                "source": "simulation",
                "updated_at": None
            }

            printer.mock_paused = False
            risk_engine.reset_simulation()
            risk_engine.events.clear()

            with TestClient(main.app) as client:
                checker = DemoCheck(client)
                return checker.run()


if __name__ == "__main__":
    try:
        success = main_check()
        sys.exit(0 if success else 1)

    except Exception as error:
        print()
        print("[ERROR] Demo check could not complete.")
        print(f"{type(error).__name__}: {error}")
        sys.exit(1)

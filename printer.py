import os
import httpx
from dotenv import load_dotenv

load_dotenv()

PRINTER_TYPE = os.getenv("PRINTER_TYPE", "mock").lower()

OCTOPRINT_URL = os.getenv(
    "OCTOPRINT_URL", "http://127.0.0.1:5000"
).rstrip("/")

OCTOPRINT_API_KEY = os.getenv("OCTOPRINT_API_KEY", "")

MOONRAKER_URL = os.getenv(
    "MOONRAKER_URL", "http://127.0.0.1:7125"
).rstrip("/")


class Printer:
    def __init__(self):
        self.mock_paused = False

    async def get_status(self):
        if PRINTER_TYPE == "mock":
            return {
                "connected": True,
                "state": "Paused" if self.mock_paused else "Printing",
                "progress": 42.5,
                "simulated": True
            }

        async with httpx.AsyncClient(timeout=5.0) as client:
            if PRINTER_TYPE == "octoprint":
                response = await client.get(
                    f"{OCTOPRINT_URL}/api/job",
                    headers={"X-Api-Key": OCTOPRINT_API_KEY}
                )
                response.raise_for_status()
                data = response.json()

                return {
                    "connected": True,
                    "state": data.get("state"),
                    "progress": data.get("progress", {}).get("completion"),
                    "simulated": False
                }

            if PRINTER_TYPE == "moonraker":
                response = await client.get(
                    f"{MOONRAKER_URL}/printer/objects/query",
                    params={
                        "print_stats": "",
                        "virtual_sdcard": ""
                    }
                )
                response.raise_for_status()
                data = response.json()["result"]["status"]

                return {
                    "connected": True,
                    "state": data["print_stats"]["state"],
                    "progress": round(
                        data["virtual_sdcard"]["progress"] * 100, 2
                    ),
                    "simulated": False
                }

        raise ValueError("Unsupported printer type")

    async def reset_simulation(self):
        if PRINTER_TYPE != "mock":
            raise ValueError("Reset is only available in mock printer mode")

        self.mock_paused = False

        return {
            "success": True,
            "message": "Simulated printer reset and resumed",
            "simulated": True
        }

    async def pause(self):
        if PRINTER_TYPE == "mock":
            self.mock_paused = True

            return {
                "success": True,
                "message": "Simulated printer paused",
                "simulated": True
            }

        async with httpx.AsyncClient(timeout=5.0) as client:
            if PRINTER_TYPE == "octoprint":
                response = await client.post(
                    f"{OCTOPRINT_URL}/api/job",
                    headers={"X-Api-Key": OCTOPRINT_API_KEY},
                    json={"command": "pause", "action": "pause"}
                )

            elif PRINTER_TYPE == "moonraker":
                response = await client.post(
                    f"{MOONRAKER_URL}/printer/print/pause"
                )

            else:
                raise ValueError("Unsupported printer type")

            response.raise_for_status()

            return {
                "success": True,
                "message": "Pause command accepted",
                "simulated": False
            }


printer = Printer()
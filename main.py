
import asyncio
import logging
import time

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from notification import send_discord_alert
from printer import printer
from risk_engine import risk_engine
from incident_db import (
    get_incidents,
    get_incident_stats,
    save_incident
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Print Guardian API",
    version="0.6.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173"
    ],
    allow_methods=["*"],
    allow_headers=["*"]
)

risk_lock = asyncio.Lock()

STALE_THRESHOLD_SECONDS = 10

mode = "simulation"

latest_sensor = {
    "camera_confidence": 12.0,
    "filament_runout": False,
    "source": "simulation",
    "updated_at": None
}


class SensorData(BaseModel):
    camera_confidence: float = Field(ge=0, le=100)
    filament_runout: bool = False


def sensor_health():
    timestamp = latest_sensor["updated_at"]

    if timestamp is None:
        return {
            "status": "WAITING",
            "age_seconds": None,
            "stale": False,
            "threshold_seconds": STALE_THRESHOLD_SECONDS,
            "message": "Waiting for first sensor reading"
        }

    age = max(0, time.time() - timestamp)
    stale = age > STALE_THRESHOLD_SECONDS

    return {
        "status": "STALE" if stale else "CONNECTED",
        "age_seconds": round(age, 1),
        "stale": stale,
        "threshold_seconds": STALE_THRESHOLD_SECONDS,
        "message": (
            "No recent sensor readings"
            if stale
            else "Sensor readings are current"
        )
    }


async def enforce_live_health():
    if mode != "live":
        return

    health = sensor_health()

    if health["status"] != "CONNECTED":
        async with risk_lock:
            if mode != "live":
                return

            current = sensor_health()

            if (
                current["status"] != "CONNECTED"
                and risk_engine.armed
            ):
                risk_engine.disarm()
                risk_engine.log(
                    "Live sensor unavailable; monitoring disarmed"
                )


@app.get("/")
def home():
    return {
        "project": "Print Guardian",
        "status": "Backend running",
        "mode": mode
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/mode")
def get_mode():
    return {"mode": mode}


@app.post("/mode/{new_mode}")
async def change_mode(new_mode: str):
    global mode, latest_sensor

    if new_mode not in ("simulation", "live"):
        raise HTTPException(
            status_code=400,
            detail="Mode must be simulation or live"
        )

    async with risk_lock:
        if risk_engine.paused:
            raise HTTPException(
                status_code=409,
                detail="Reset the paused simulation before switching modes"
            )

        if mode != new_mode:
            mode = new_mode
            risk_engine.reset_simulation()

            latest_sensor = {
                "camera_confidence": (
                    12.0 if mode == "simulation" else 0.0
                ),
                "filament_runout": False,
                "source": mode,
                "updated_at": None
            }

            risk_engine.log(
                f"Switched to {mode} mode"
            )

    return {
        "mode": mode,
        "message": f"{mode.title()} mode enabled",
        "monitoring_armed": False
    }


@app.get("/sensors/latest")
async def get_latest_sensor():
    await enforce_live_health()

    return {
        **latest_sensor,
        "health": sensor_health()
    }


@app.get("/sensors/health")
async def get_sensor_health():
    await enforce_live_health()

    return {
        "mode": mode,
        "source": latest_sensor["source"],
        **sensor_health()
    }


@app.get("/printer/status")
async def printer_status():
    try:
        return await printer.get_status()
    except (httpx.HTTPError, ValueError, KeyError) as error:
        logger.error(
            "Printer status error: %s",
            error
        )

        raise HTTPException(
            status_code=503,
            detail="Unable to retrieve printer status"
        ) from error


@app.post("/printer/pause")
async def pause_printer():
    async with risk_lock:
        try:
            result = await printer.pause()

            if result.get("success"):
                risk_engine.confirm_pause()

            return result

        except (httpx.HTTPError, ValueError) as error:
            logger.error(
                "Manual pause failed: %s",
                error
            )

            raise HTTPException(
                status_code=503,
                detail="Printer pause failed"
            ) from error


@app.get("/risk/status")
async def get_risk_status():
    await enforce_live_health()
    return risk_engine.status()


@app.post("/risk/arm")
async def arm_monitoring():
    async with risk_lock:
        if mode == "live":
            health = sensor_health()

            if health["status"] != "CONNECTED":
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Cannot arm live monitoring: "
                        "sensor data is missing or stale"
                    )
                )

        return risk_engine.arm()


@app.post("/risk/disarm")
async def disarm_monitoring():
    async with risk_lock:
        return risk_engine.disarm()


async def process_sensor_update(data: SensorData, source: str):
    global latest_sensor

    async with risk_lock:
        if source != mode:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cannot submit {source} readings "
                    f"in {mode} mode"
                )
            )

        latest_sensor = {
            "camera_confidence": data.camera_confidence,
            "filament_runout": data.filament_runout,
            "source": source,
            "updated_at": time.time()
        }

        status, should_pause = risk_engine.process(
            camera=data.camera_confidence,
            filament_runout=data.filament_runout
        )

        if not should_pause:
            return {
                **status,
                "pause_result": None,
                "notification_sent": None
            }

        failure_type = (
            "Filament Runout"
            if data.filament_runout
            else "Camera Failure"
        )

        try:
            pause_result = await printer.pause()

            if not pause_result.get("success"):
                raise ValueError(
                    "Printer did not confirm pause"
                )

            risk_engine.confirm_pause()
            status = risk_engine.status()

        except (httpx.HTTPError, ValueError) as error:
            logger.error(
                "Automatic pause failed: %s",
                error
            )

            risk_engine.log(
                "Printer pause command failed"
            )

            save_incident(
                mode=source,
                failure_type=failure_type,
                risk_score=status["risk_score"],
                camera_confidence=data.camera_confidence,
                filament_runout=data.filament_runout,
                pause_success=False,
                pause_message=str(error),
                notification_sent=False
            )

            raise HTTPException(
                status_code=503,
                detail="Printer pause failed"
            ) from error

        notification_sent = False

        try:
            notification_sent = bool(
                await send_discord_alert(
                    failure_type=failure_type,
                    risk_score=status["risk_score"],
                    printer_status=(
                        "Paused (Simulation)"
                        if pause_result.get("simulated")
                        else "Pause Command Accepted"
                    )
                )
            )
        except Exception as error:
            logger.error(
                "Discord notification error: %s",
                error
            )

        risk_engine.log(
            "Discord notification sent"
            if notification_sent
            else "Discord notification failed"
        )

        incident_id = save_incident(
            mode=source,
            failure_type=failure_type,
            risk_score=status["risk_score"],
            camera_confidence=data.camera_confidence,
            filament_runout=data.filament_runout,
            pause_success=True,
            pause_message=pause_result.get(
                "message",
                "Pause command accepted"
            ),
            notification_sent=notification_sent
        )

        risk_engine.log(
            f"Incident #{incident_id} recorded"
        )

        return {
            **status,
            "pause_result": pause_result,
            "notification_sent": notification_sent,
            "incident_id": incident_id
        }


@app.post("/risk/update")
async def update_simulation(data: SensorData):
    return await process_sensor_update(
        data,
        "simulation"
    )


@app.post("/live/update")
async def update_live(data: SensorData):
    return await process_sensor_update(
        data,
        "live"
    )


@app.get("/incidents")
def list_incidents(limit: int = 100):
    limit = max(1, min(limit, 500))

    return {
        "incidents": get_incidents(limit),
        "stats": get_incident_stats()
    }


@app.post("/simulation/reset")
async def reset_simulation():
    global latest_sensor

    async with risk_lock:
        if mode != "simulation":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Reset & Resume is only available "
                    "in simulation mode"
                )
            )

        try:
            result = await printer.reset_simulation()
        except ValueError as error:
            raise HTTPException(
                status_code=403,
                detail=str(error)
            ) from error

        status = risk_engine.reset_simulation()

        latest_sensor = {
            "camera_confidence": 12.0,
            "filament_runout": False,
            "source": "simulation",
            "updated_at": time.time()
        }

        return {
            **status,
            "printer_result": result
        }


@app.post("/notifications/test")
async def test_discord_notification():
    sent = await send_discord_alert(
        failure_type="Simulated Print Failure",
        risk_score=92.0,
        printer_status="Test Mode",
        is_test=True
    )

    if not sent:
        raise HTTPException(
            status_code=502,
            detail="Discord notification failed"
        )

    return {
        "success": True,
        "message": "Discord notification sent"
    }

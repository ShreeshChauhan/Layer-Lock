
import asyncio
import logging
import os
import time
from tempfile import SpooledTemporaryFile
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from notification import send_discord_alert
from printer import printer, CommandBlocked, validate_upload_name
from telemetry import PrinterMonitor
from risk_engine import risk_engine
from camera_feed import router as camera_router
from incident_db import (
    get_incidents, get_print_history, save_print_action,
    get_incident_stats,
    save_incident, update_notification, resolve_incident, open_incident, get_events
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

monitor = PrinterMonitor(printer)


async def poll_printer():
    while True:
        try:
            await monitor.sample()
            await enforce_live_health()
        except Exception:
            logger.exception('Background printer monitoring failed; retrying')
        await asyncio.sleep(3)


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(poll_printer())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await printer.close()


app = FastAPI(
    title="Print Guardian API",
    version="0.7.0", lifespan=lifespan
)

app.include_router(camera_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        *[origin.strip() for origin in os.getenv('CORS_ORIGINS', '').split(',') if origin.strip()]
    ],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Frame-Received-At"]
)

risk_lock = asyncio.Lock()

STALE_THRESHOLD_SECONDS = 10

mode = "simulation" if printer.simulated else "live"

latest_sensor = {
    "camera_confidence": 12.0,
    "filament_runout": False,
    "source": "simulation",
    "updated_at": None
}


class SensorData(BaseModel):
    camera_confidence: float = Field(ge=0, le=100)
    filament_runout: bool = False
    failure_type: str | None = Field(default=None, max_length=100)


class StartPrint(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    confirmed: bool = False


class ReviewPrint(BaseModel):
    confirmed: bool = False


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
            if new_mode == 'simulation' and not printer.simulated:
                raise HTTPException(409, 'Simulation requires a mock printer; real printer control is configured')
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


@app.get('/dashboard')
async def dashboard():
    await monitor.sample()
    await enforce_live_health()
    current = monitor.status
    return {
        'printer': current, 'printer_error': monitor.error,
        'temperature_history': list(monitor.history), 'mode': mode,
        'sensor': {**latest_sensor, 'health': sensor_health()},
        'risk': risk_engine.status(), 'events': get_events(),
        'incidents': get_incidents(100), 'incident_stats': get_incident_stats(),
        'print_history': get_print_history(),
        'active_incident': open_incident(mode, current.get('file')) if current else None,
    }


@app.get('/printer/files')
async def printer_files():
    try:
        return {'files': await printer.list_files()}
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        raise HTTPException(503, 'Unable to list printer files') from error


MAX_UPLOAD_BYTES = 100 * 1024 * 1024
upload_lock = asyncio.Lock()


@app.delete('/printer/files')
async def delete_printer_file(path: str = Query(min_length=1)):
    async with risk_lock:
        async with upload_lock:
            try:
                result = await printer.delete_file(path)
                monitor.event(f'File removed: {path}')
                return result
            except CommandBlocked as error:
                raise HTTPException(409, str(error)) from error
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
                raise HTTPException(503, 'Unable to remove file; refresh the file list') from error


@app.post('/printer/files/upload', status_code=201)
async def upload_printer_file(request: Request, filename: str = Query(min_length=1, max_length=255)):
    try:
        validate_upload_name(filename)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    # Stream the browser's file into a bounded spool, then forward as OctoPrint multipart.
    # Uploading never sends a select/start command and does not hold the control lock.
    size = 0
    with SpooledTemporaryFile(max_size=1024 * 1024, mode='w+b') as stream:
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(413, 'G-code upload exceeds the 100 MB limit')
            stream.write(chunk)
        if size == 0:
            raise HTTPException(400, 'The selected file is empty')
        stream.seek(0)
        try:
            async with upload_lock:
                file = await printer.upload_file(filename, stream, size)
            monitor.event(f"File uploaded: {file['path']}")
            return {'file': file}
        except CommandBlocked as error:
            raise HTTPException(409, str(error)) from error
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            monitor.event(f'File upload failed: {filename}')
            raise HTTPException(503, 'File upload failed; check OctoPrint connection and storage') from error


async def run_command(action, path=None):
    async with risk_lock:
        requested = False
        try:
            before = await printer.get_status()
            incident = open_incident(mode, before.get('file'))
            if action == 'resume' and incident and mode == 'live' and sensor_health()['status'] != 'CONNECTED':
                raise CommandBlocked('Restore fresh vision readings before resuming this incident')
            monitor.event(f'{action.title()} requested' + (f': {path}' if path else ''))
            monitor.expect_action(action, before)
            requested = True
            result = await printer.start(path) if action == 'start' else await getattr(printer, action)()
            if action in ('pause', 'cancel'):
                save_print_action(action, 'manual', before, 'Dashboard control')
            if action in ('resume', 'cancel'):
                risk_engine.recover(resume=action == 'resume')
                if incident:
                    resolve_incident(incident['id'], f'{action}_requested')
            elif action == 'start':
                risk_engine.recover()
                if mode == 'live' and sensor_health()['status'] == 'CONNECTED':
                    risk_engine.arm()
            elif action == 'pause':
                risk_engine.confirm_pause()
            monitor.event(result['message'])
        except CommandBlocked as error:
            monitor.expected.pop(action, None)
            raise HTTPException(409, str(error)) from error
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            monitor.expected.pop(action, None)
            if requested and action in ('pause', 'cancel'):
                save_print_action(action, 'manual', before, 'Dashboard control', 'Failed or unconfirmed')
            monitor.event(f'{action.title()} command failed')
            raise HTTPException(503, f'{action.title()} command failed; check printer connection') from error
    await monitor.sample(force=True)
    return result


@app.post('/printer/start')
async def start_print(data: StartPrint):
    if not data.confirmed:
        raise HTTPException(409, 'Confirm that the bed is clear and the printer is ready')
    return await run_command('start', data.path)


@app.post('/printer/resume')
async def resume_print(data: ReviewPrint):
    if not data.confirmed:
        raise HTTPException(409, 'Inspect the print and confirm the issue is resolved before resuming')
    return await run_command('resume')


@app.post('/printer/cancel')
async def cancel_print():
    return await run_command('cancel')


@app.post("/printer/pause")
async def pause_printer():
    return await run_command('pause')


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
            raise HTTPException(409, f"Cannot submit {source} readings in {mode} mode")
        if source == 'simulation' and not printer.simulated:
            raise HTTPException(409, 'Simulated readings cannot control a real printer')
        if source == 'live' and sensor_health()['status'] != 'CONNECTED':
            risk_engine.high_risk_since = None
        try:
            job = await printer.get_status()
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            raise HTTPException(503, 'Cannot verify printer state for monitoring') from error

        latest_sensor = {
            'camera_confidence': data.camera_confidence,
            'filament_runout': data.filament_runout,
            'source': source, 'updated_at': time.time()
        }
        if not job.get('printing') and not job.get('paused'):
            risk_engine.disarm()
        status, should_pause = risk_engine.process(data.camera_confidence, data.filament_runout)
        if not job.get('printing'):
            should_pause = False
            risk_engine.high_risk_since = None
        if not should_pause:
            return {**status, 'pause_result': None, 'notification_sent': None}

        failure_type = 'Filament Runout' if data.filament_runout else (data.failure_type or 'Camera Failure')
        pause_error = None
        monitor.expect_action('pause', job)
        try:
            pause_result = await printer.pause(status=job)
            if not pause_result.get('success'):
                raise ValueError('Printer did not accept pause')
            risk_engine.confirm_pause()
            monitor.event(f'Issue detected: {failure_type}; automatic pause command accepted')
        except (httpx.HTTPError, ValueError) as error:
            monitor.expected.pop('pause', None)
            pause_error = str(error)
            pause_result = {'success': False, 'message': pause_error}
            risk_engine.log('Printer pause command failed')
            monitor.event(f'Issue detected: {failure_type}; automatic pause FAILED')

        status = risk_engine.status()
        incident_id = save_incident(
            mode=source, failure_type=failure_type, risk_score=status['risk_score'],
            camera_confidence=data.camera_confidence, filament_runout=data.filament_runout,
            pause_success=pause_result['success'], pause_message=pause_result.get('message', ''),
            notification_sent=False, file_name=job.get('file'),
            print_progress=job.get('progress'), print_time=job.get('print_time'))
        risk_engine.log(f'Incident #{incident_id} recorded')

    # Network notification work must not block the operator's recovery controls.
    notification_sent = False
    try:
        notification_sent = bool(await send_discord_alert(
            failure_type=failure_type, risk_score=status['risk_score'],
            printer_status='PAUSE FAILED - inspect immediately' if pause_error else
                'Paused (Simulation)' if pause_result.get('simulated') else 'Pause Command Accepted',
            action_message='Pause command failed' if pause_error else 'Pause command accepted'))
    except Exception:
        logger.exception('Discord notification failed')
    update_notification(incident_id, notification_sent)
    risk_engine.log('Discord notification sent' if notification_sent else 'Discord notification failed')
    if pause_error:
        raise HTTPException(503, 'Printer pause failed; incident recorded')
    return {**status, 'pause_result': pause_result,
            'notification_sent': notification_sent, 'incident_id': incident_id}


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

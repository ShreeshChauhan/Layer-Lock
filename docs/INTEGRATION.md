# LayerLock integration and operation

LayerLock combines an OctoPrint-connected printer and camera with a FastAPI backend, a managed vision worker, and a React dashboard. The Raspberry Pi provides OctoPrint and camera endpoints; the application host runs the backend and vision inference.

## Setup and startup

Follow the [main README](../README.md#run-layerlock) to install dependencies, download model weights, and configure the root `.env` file. From the repository root, run:

```powershell
.\start-dev.ps1
```

Alternatively, run `npm.cmd run dev` in `frontend`. Vite starts `backend.main:app` when needed and verifies the API before serving the dashboard. It reuses an existing healthy backend. Closing the launcher stops only the backend it owns, including its vision worker. Keep the terminal open during operation.

For a separately managed backend, run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

The frontend proxies `/api` to port 8000, including video and file uploads. A production host needs an equivalent reverse proxy, or `VITE_API_URL` and matching backend `CORS_ORIGINS`. Run one backend worker: monitoring state and temperature history are process-local. Application authentication and public internet deployment are not configured.

## Configuration and persistent data

The backend reads root `.env`, with process environment variables taking precedence. Printer and camera adapters also accept legacy Pi settings from `pi-module/.env`. Root settings override those legacy values. API keys remain on the backend.

- `PRINTER_TYPE=octoprint` enables the real printer; `mock` uses simulated printer behavior.
- `OCTOPRINT_URL` and `OCTOPRINT_API_KEY` configure printer access.
- `SNAPSHOT_URL` and `STREAM_URL` configure camera capture and continuous video.
- `VISION_BACKEND_URL` defaults to `http://127.0.0.1:8000` for the managed vision publisher.
- `DISCORD_WEBHOOK_URL` enables optional failure notifications.
- `RESUME_MIN_TEMP_C` defaults to 180 °C.
- `INCIDENT_DB_PATH` optionally overrides the persistent SQLite database location.

The default database remains `print_guardian.db` in the repository root to preserve existing print history across the project rename and directory reorganization. It is ignored by Git. Local credentials, model weights, logs, and configuration backups are also ignored. Logs are written to `backend.log`, `backend-error.log`, and `vision.log` in the root.

## Telemetry, video, and files

The backend samples printer telemetry every three seconds independently of the browser. Dashboard clients share the latest state and up to 400 temperature samples, approximately 20 minutes. Temperature history resets on backend restart; events and print issue history persist in SQLite.

Live View forwards MJPEG continuously. It does not refresh at the telemetry polling interval. Camera errors trigger reconnection, and Refresh replaces the stream connection. Streaming proxies must permit long-lived connections and disable buffering. The preview is raw video; detection confidence is displayed separately.

Uploads accept sliced `.gcode`, `.gco`, or `.g` files up to 100 MB. Files are stored on OctoPrint; duplicate names receive a suffix. Uploading or selecting a file does not start it. Selection is locked during active jobs. Other files can be deleted while printing, but the current print file is protected by its full path. LayerLock does not slice STL files.

## Printer controls and recovery

Connect uses OctoPrint's existing serial preferences. Start requires an operational, idle printer and a selected file. Start and Resume use review dialogs; Pause, Cancel, and file removal execute immediately. Resume requires a paused printer, an active nozzle target, and an actual nozzle temperature at or above the configured minimum.

Manual pause/cancel actions and detected incidents are saved with file, timestamp, progress, elapsed time, reason, and outcome. External pause/cancel transitions are labeled external/unknown. Polling can miss brief external transitions. Command acceptance is recorded separately from subsequently observed printer state.

## Vision and automatic pauses

Enable vision starts a managed, headless publisher using the project's Python environment and downloaded weights. Model initialization appears as Starting; Running requires fresh detections. Enable does not arm monitoring. Disable stops the managed publisher, clears reading freshness, rejects further live readings, and disarms automatic pauses. Video remains independent.

While armed and printing, spaghetti confidence of at least 70 sustained for five seconds across fresh samples requests a pause. Readings older than ten seconds disarm monitoring and reset the sustained-risk timer. Missing readings are not treated as healthy results. Synthetic readings cannot control a real printer.

Starting a print from the dashboard arms monitoring when live vision readings are fresh. Prints started elsewhere require manual arming. After an incident, inspect the printer and choose reviewed Resume or Cancel. Resume after a live incident also requires fresh vision readings. Incident resolution is saved without deleting history.

The backend records the intervention before attempting the optional Discord notification. Notification delivery occurs outside the printer-control lock. A failed pause request is also recorded and reported in the dashboard.

An independently managed publisher can use the [vision CLI](../vision/docs/PI_INFERENCE.md). If fresh external readings already exist, Enable reuses them. Disable rejects those readings but cannot stop a process on another host.

## Printer motion configuration

Head and bed homing controls are available only for an operational, idle printer. They use firmware endstops. Working endstops, correct travel limits, and a clear machine are required.

The supplied default [G-code hooks](../pi-module/gcode_scripts/) keep pause/resume stationary and turn heaters and fan off on cancel/completion. They introduce no parking, homing, retraction, or motor release. Do not move axes manually while paused and then resume.

Preview the scripts from the repository root:

```powershell
.\.venv\Scripts\python.exe -m tools.configure_motion_scripts
```

Install only with the printer idle or offline:

```powershell
.\.venv\Scripts\python.exe -m tools.configure_motion_scripts --apply
```

The installer backs up affected settings under ignored `local-backups/`, updates the hooks, and reads them back for verification. It sends no movement commands. It does not modify uploaded G-code or slicer profiles; motion embedded in a print file remains the printer's responsibility.

Automatic parking is not enabled on the current printer because intermittent homing/endstop problems require physical resolution. Optional verified configurations are available:

- `--verified-um2-homing`: installs the Ultimaker 2+ cancel hook that homes Z before X/Y.
- `--parking-config <path>`: generates paired pause/resume/cancel scripts from physically verified limits and positions. Start from [parking.example.json](../pi-module/gcode_scripts/parking.example.json); all verification flags intentionally default to false.

Coordinate parking supports single-tool, absolute-XYZ jobs streamed through OctoPrint. It uses captured positions, preserves bed clearance, and restores the saved position on resume. Missing or invalid return coordinates prevent unsafe resumption. The tool never supplies guessed travel limits. Firmware limits and endstops must protect all movement sources, including uploaded G-code.

## Validation and references

See [Testing and validation](TESTING.md) for isolated regression checks.

- [OctoPrint job API](https://docs.octoprint.org/en/main/api/job.html)
- [OctoPrint printer API](https://docs.octoprint.org/en/main/api/printer.html)
- [OctoPrint file API](https://docs.octoprint.org/en/main/api/files.html)
- [OctoPrint G-code scripts](https://docs.octoprint.org/en/main/features/gcode_scripts.html)

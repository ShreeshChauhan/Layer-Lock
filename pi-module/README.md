# LayerLock Pi integration

Standalone printer commands, camera snapshots, and health checks for OctoPrint on a Raspberry Pi. The web application uses the asynchronous adapter in `backend/printer.py`; this synchronous library supports direct command-line operation.

Design rule: every request has a timeout and every failure raises an exception, so problems become alerts instead of failing silently.

## Quick start

Run everything from the `pi-module` folder:

```powershell
pip install -r ../requirements.txt
copy .env.example .env            # defaults to MOCK=1; fill in OCTO_KEY and set MOCK=0 for hardware
python -m tools.hardware_check    # confirms OctoPrint, camera, and printer all respond
```

No hardware? Run in mock mode, and clear the variable afterwards (shell variables override `.env`):

```powershell
$env:MOCK = "1"
python -m tools.hardware_check
Remove-Item Env:MOCK
```

## Files

### `hardware/` (the library; the rest of the project imports only from here)

| File | Role |
|---|---|
| `__init__.py` | Public entry point. `get_printer()`, `get_camera()`, and `get_health_monitor()` return real or mock objects depending on `MOCK`. Create one printer and pass it around. |
| `config.py` | All settings, read from environment variables or `.env`. Nothing secret is hardcoded. |
| `printer.py` | Talks to OctoPrint's REST API: pause, resume, cancel, heaters, starting prints, and printer state. Includes safety checks (won't resume with a cold nozzle, won't start a print unless the printer is idle) and a `MockPrinter` with the same interface. |
| `camera.py` | Fetches JPEG snapshots from OctoPi's camera URL and returns them as `Frame` objects. Raises `CameraError` rather than returning stale data. Includes a `ReplayCamera` mock that plays saved frames or generates fake ones. |
| `health.py` | Checks the camera (dark, blocked, frozen, stale), OctoPrint, the printer connection, and the Pi's temperature and throttling. Returns one report whose `ok` flag is false if anything is wrong. |

### `tools/` (command-line scripts)

| Script | Role | How to run |
|---|---|---|
| `hardware_check.py` | First thing to run when something seems wrong. Fetches a frame (saved to `data/test_frame.jpg`) and prints a health report. Optional flags send a command first, then re-check. | `python -m tools.hardware_check` (flags: `--pause`, `--resume`, `--cancel`, `--heaters-off`) |
| `start_print.py` | Starts a print without the OctoPrint dashboard. Asks "Is the bed clear?" first. Needs sliced G-code for the Ultimaker 2+, not an STL. | `python -m tools.start_print --list`<br>`python -m tools.start_print C:\path\part.gcode`<br>`python -m tools.start_print --remote part.gcode` (add `--yes` to skip the prompt) |

Always run tools as modules (`python -m tools.<name>`) from `pi-module`, or the imports will fail.

## Configuration (`.env`)

Lives in `pi-module/`, is gitignored, and holds the API key, so never commit or paste it. The settings you'll actually touch:

```
OCTO_URL=http://<pi-address>                              # on the Pi: http://localhost
OCTO_KEY=<your key>
SNAPSHOT_URL=http://<pi-address>/webcam/?action=snapshot  # on the Pi: http://localhost:8080/?action=snapshot
MOCK=0                                                    # 1 = fake printer and camera
```

Health thresholds (`DARK_MEAN`, `FLAT_STD`, `FROZEN_DIFF`, `FROZEN_COUNT`, `FRAME_MAX_AGE_S`, `PI_TEMP_WARN_C`, `PI_TEMP_CRIT_C`) and `RESUME_MIN_TEMP_C` (default 180) also live in `config.py` and can be overridden the same way.

## Mock mode

`MOCK=1` swaps in `MockPrinter` and `ReplayCamera`, so teammates can build without the Pi, printer, or camera. It proves the flow and imports work, but it never contacts OctoPrint, so it can't tell you whether a real command would be accepted.

## OctoPrint G-code scripts (on the Pi)

OctoPrint runs these itself on pause, resume, and cancel, whether the command comes from the web UI or from this code. They're edited under **Settings, GCODE Scripts** and live in `~/.octoprint/scripts/gcode/`. They are the same files, so there's nothing to sync.

The tracked `gcode_scripts/` hooks now use stationary pause/resume and heater/fan
shutdown on cancel/completion. They deliberately contain no park, lift, retract,
home, or motor-release commands. See the [integration guide](../docs/INTEGRATION.md) for installation,
backups, existing uploaded-file limitations, and required physical-limit checks.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `OctoPrint unreachable` | Wrong `OCTO_URL`, Pi off, or the Pi's IP changed (`hostname -I` on the Pi). |
| `OCTO_KEY is not set` | Add it to `pi-module/.env`. |
| Camera error | Open `SNAPSHOT_URL` in a browser; it should show an image. |
| Mock mode seems stuck on | Run `Remove-Item Env:MOCK`. |
| Resume refused | Heaters are off or the nozzle is too cold. Turn them on, wait, retry. |
| Start refused | A job is already running, or the printer isn't `Operational`. |

## Security

- Never paste the API key into chat or commit it. Regenerate it in OctoPrint (Settings, API) if it has been exposed.
- Never port-forward the camera stream (port 8080); it has no authentication. Share it over the same network, a hotspot, or Tailscale.
- Automatic pause coordination runs in the web backend; this command-line library alone does not provide failure monitoring.

## Health and API boundaries

Printer health requires a recognized healthy connection state and operational flags without an error. A connected `Error`, `Unknown`, or transitional connection state is not healthy. Invalid JSON, malformed nested objects, invalid flags, and invalid numeric readings raise `PrinterError`; health checks report OctoPrint `error` and printer `unknown`. Missing Pi telemetry remains `unknown` and is excluded from the aggregate health decision, so laptop mock checks can run.

The backend still uses `backend/printer.py`: asynchronous `pause()` / `get_status()`, `PRINTER_TYPE`, `OCTOPRINT_URL`, and `OCTOPRINT_API_KEY`. This library uses synchronous `pause_printer()` / `get_printer_state()`, `MOCK`, `OCTO_URL`, and `OCTO_KEY`. These are separate adapters and settings; no automatic bridge or health-to-backend endpoint is implemented. Hardware frames are RGB; convert to BGR before passing to the existing OpenCV YOLO detector. The Pi vision publisher remains independent and submits camera confidence to `/live/update`; it never arms monitoring.


## Automated validation

From the repository root (install `vision/requirements.txt` too for vision tests):

```powershell
$env:PYTHON_DOTENV_DISABLED="1"
$env:PRINTER_TYPE="mock"
$env:MOCK="1"
python -m unittest discover -s pi-module/tests -v
python -m unittest discover -s vision/tests -v
python -m unittest discover -s tests -t . -v
```

Tests replace HTTP transports and printer/notification actions with mocks. Physical camera connectivity, device telemetry, and OctoPrint-version compatibility still require deployment validation.

# Layer-Lock: `pi-module` (hardware layer)

The hardware layer for Print Guardian: camera-only failure detection for an Ultimaker 2+ running OctoPrint on a Raspberry Pi. It controls the printer, fetches camera frames, and reports the health of every component. The stop decision runs locally on the Pi; the cloud is only for viewing and alerts.

Design rule: every request has a timeout and every failure raises an exception, so problems become alerts instead of failing silently.

## Quick start

Run everything from the `pi-module` folder:

```powershell
pip install requests pillow python-dotenv
copy .env.example .env            # then fill in OCTO_KEY
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
| `printer_test.py` | Exercises pause, resume, cancel, and heaters-off on the real printer. **Moves the printer**, so only run it with a print in progress and your hand near the controls. | `python -m tools.printer_test` |
| `record_frames.py` | Saves camera frames to disk as training data. Run it during every print, with a separate folder per print. | `python -m tools.record_frames` |
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

- `afterPrintPaused`: retracts, lowers the bed, parks the head at X=0 Y=224.5.
- `beforePrintResumed`: returns to the saved position, then un-retracts. Needs **Log position on pause** enabled.
- `afterPrintCancelled`: heaters and fan off, retract, bed down, park the head.

Keep a copy of these in the repo so a rebuilt Pi can restore them.

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
- The stop decision should always read the camera locally on the Pi, so a network drop never affects safety.
# Dashboard and OctoPrint integration

The dashboard gets a combined `/dashboard` response every three seconds. A backend
sampler runs independently of the browser, records observed printer state, file,
and temperature-target changes in SQLite, and retains up to 400 temperature samples
in memory (roughly 20 minutes; cleared on backend restart). Multiple viewers share
that history. There is no frontend-generated printer progress, timing, or sensor feed.
Mock printer mode is explicitly labeled as demo telemetry.

## Connect a real printer

Copy root `.env.example` to root `.env`, then set:

```dotenv
PRINTER_TYPE=octoprint
OCTOPRINT_URL=http://<pi-address>
OCTOPRINT_API_KEY=<your OctoPrint API key>
SNAPSHOT_URL=http://<pi-address>/webcam/?action=snapshot
STREAM_URL=http://<pi-address>/webcam/?action=stream
DISCORD_WEBHOOK_URL=<optional Discord webhook>
```

Keep keys in the backend config. Never use a `VITE_` variable for secrets.
The adapter also accepts legacy `OCTO_URL` and `OCTO_KEY` from `pi-module/.env`.
Process environment overrides root `.env`, which overrides legacy Pi settings.
`PRINTER_TYPE` must explicitly be `octoprint`; legacy `MOCK=0` alone does not enable
hardware. Restart the backend after changing printer configuration.

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

After dependencies are installed, run `.\start-dev.ps1` from the repository root
or `npm run dev` in `frontend` to start both services together. Vite checks API health
before opening the dashboard, starts the backend when absent, and reuses an existing
healthy Layer-Lock backend. Ctrl+C stops only the backend this launcher started,
including its vision worker. Startup failures appear in the terminal; backend logs
are appended to `backend.log` and `backend-error.log`. Keep the terminal open while
using the app. After a backend restart, check vision and arm automatic pauses again.

Development requests use Vite's `/api` proxy to port 8000, including file uploads
and camera snapshots. This also works if Vite chooses another port. A deployed
frontend needs an equivalent `/api` reverse proxy, or a build-time `VITE_API_URL`
and matching backend `CORS_ORIGINS`. These control endpoints currently have no
application authentication; deploy within the existing trusted local setup.
Run one backend worker: monitoring state and temperature history are process-local.

Live View opens `/camera/stream` automatically. The backend forwards the configured
MJPEG stream without collecting entire responses or polling for frames. The browser
renders frames at the camera's rate and reconnects after stream errors. Reverse
proxies must disable buffering and permit long-lived responses. Each viewer opens
one upstream stream; camera resolution, Wi-Fi and viewer count affect performance.
`/camera/snapshot` remains available for snapshots and inference.

## Dashboard behavior

- Printer Controls includes Home bed (Z) and Home head (X/Y). These send
  OctoPrint's home command, using firmware endstops rather than guessed coordinates.
  Both the UI and backend require a connected, operational, idle printer and reject
  homing while printing or paused. This preserves saved pause/resume coordinates.
  Clear the bed and home the bed before traversing the head. The reported homing
  fault must be repaired before these physical movements are used. Accepted requests
  are recorded in the event log; acceptance is not confirmation that homing finished.
  These controls have been tested with mocked HTTP only; no physical homing was run.

- Machine Status includes Connect printer for an offline OctoPrint printer. It
  uses OctoPrint's existing port/baudrate preferences (or auto-detection), records
  the command in the event log, and waits for telemetry to confirm connection.
  The backend rejects reconnects while connected or already connecting. The API
  key requires OctoPrint's CONNECTION permission. File removal uses an unfilled
  red trash icon beside each file.

- Printer state, filename, completion, elapsed time, and remaining-time estimate come
  from OctoPrint `/api/job`. Missing estimates display as unavailable, never zero.
- Tool0 and bed actual/target readings come from `/api/printer`. Disconnected printers
  and failed requests are shown as unavailable. Last-known history remains visible,
  with a gap for lost telemetry. The graph is not persisted across restarts.
- The event log persists web command requests/acceptances/failures and observed
  printer states, selected files, and heater target changes. Actions from OctoPrint
  are reflected by the sampled changes. Very short external transitions between
  samples can be missed; this is not an OctoPrint event-stream subscription.
- Printer controls and uploaded files sit to the right of Live View; temperature
  history stays below. The filament sensor and separate current-temperature panel
  are no longer shown.
- Upload G-code opens a local file picker and stores `.gcode`, `.gco`, or `.g` files
  (up to 100 MB) in OctoPrint's local uploads. It never starts or selects a job.
  The uploaded file is highlighted in the dashboard list, ready for the Print button.
  Existing files with the same name are preserved by assigning the new upload a suffix.
  Files remain on OctoPrint across dashboard refreshes and backend restarts.
- Select a row in Uploaded files, then Print, to select and print that remote file,
  only from `Operational` state. Pause changes to Resume when telemetry reports paused.
  Refresh retrieves files added outside the dashboard; search filters the list.
  Uploads have their own timeout and do not hold the printer-control lock, so pause
  and cancel remain available during an upload. The web interface does not slice STLs.
- Start and resume have a review dialog. Cancel and file removal act immediately.
  Trash buttons sit inside the file row. During a print, selection is locked and
  other files can be removed; the current print file is protected by full path.
  Resume requires an actually paused
  operational printer and a tool0 target above zero with actual nozzle temperature
  at least `RESUME_MIN_TEMP_C` (default 180 C), matching the Pi library's guard.
- Cancel uses OctoPrint's job-cancel command. Pause/park/resume/cancel motion and
  heater behavior remain defined by the printer's existing OctoPrint G-code scripts.

The async root adapter owns web requests. The synchronous `pi-module/hardware`
CLI library remains available; it is not called on FastAPI's event loop.
OctoPrint contracts: https://docs.octoprint.org/en/main/api/job.html,
https://docs.octoprint.org/en/main/api/printer.html,
https://docs.octoprint.org/en/main/api/files.html.

## Detection, notifications, and recovery

Run the existing vision publisher, after installing vision dependencies and weights:

```powershell
.\.venv\Scripts\python.exe -m vision.src.pi_inference --snapshot-url "http://<pi-address>/webcam/?action=snapshot" --backend-url http://127.0.0.1:8000 --headless
```

Real printer configuration starts the backend in live sensor mode. Once readings
are fresh, arm monitoring in the dashboard. A web-started print automatically arms
if live vision readings are fresh; otherwise it starts with monitoring disarmed,
which the dashboard explicitly shows. Starting in OctoPrint requires manually arming.

While armed and actually printing, sustained high camera confidence (>=70 for five
seconds across fresh samples) or reported filament runout requests a pause. A gap
in live readings resets the sustained-risk timer. Simulation readings cannot control
real hardware. Monitoring freshness checks run without requiring an open browser;
stale vision currently disarms monitoring, rather than pausing the printer.

Each detected intervention is saved before sending Discord notification, including
filename, progress, elapsed time, risk, failure type, and whether the pause request
was accepted. A failed pause is recorded and also attempts an alert. Discord work
runs outside the printer-control lock. The dashboard shows a persistent issue panel;
Discord delivery requires the configured webhook. No notification permission is
required for the in-app panel.

Inspect the print, then choose reviewed resume or cancel. Resume after a live
incident additionally requires fresh vision readings. Accepted recovery requests
update the stored resolution without deleting the incident. A command acceptance
is not physical completion; actual pause/resume state comes from later telemetry.

The camera preview is independent of inference and shows continuous raw MJPEG video. The graph
and controls do not run inference. No filament sensor firmware/publisher is supplied;
absence of a runout report does not establish connected filament hardware.

## Validation

```powershell
$env:PYTHON_DOTENV_DISABLED="1"
$env:PRINTER_TYPE="mock"
python -m unittest test_api test_risk test_camera_feed test_printer test_dashboard test_motion_scripts
python -m unittest discover -s pi-module/tests
cd frontend
npm.cmd run lint
npm.cmd run build
```

Tests use mocked HTTP/printer/notification operations and isolated databases.
Physical camera connectivity, nozzle behavior, pause scripts and printer-version
compatibility need an actual hardware check before deployment.

## Motion safety: Ultimaker 2+

The inspected Pi scripts commanded Z=208.75 and Y=224.5 on cancellation and an
unchecked relative Z+20 on pause. The OctoPrint profile is 200 x 200 x 200 mm;
the manufacturer's nominal UM2+ build volume is 223 x 223 x 205 mm. Neither a
profile nor a build-volume specification proves physical travel limits or firmware
endstop enforcement. Do not substitute guessed maximum coordinates.

`pi-module/gcode_scripts` now contains conservative **stationary** pause/resume,
cancel and completion hooks. Pause/resume do not move, retract, change coordinate
modes, or release motors. Cancel/complete disable heaters and fans, without parking
or disabling holding torque. A stationary hot nozzle may mark/ooze on the part;
inspect promptly. Do not jog or manually move axes while paused and then resume.
Firmware idle motor timeouts still apply; these hooks cannot override them.

To install after reviewing, with the printer idle or offline:

```powershell
.\.venv\Scripts\python.exe configure_motion_scripts.py --apply
```

The installer backs up only the old scripts in ignored `local-backups/`, updates
only the four hooks, and reads them back to verify. It never sends motion or job
commands. Stop other operators from starting a job while changing configuration.
The repository's two sample G-code footers also use stationary shutdown now.
**Already uploaded files and slicer profiles are not changed:** re-slice or replace
their unsafe end G-code before printing. A completion hook runs after file G-code;
it cannot undo an unsafe move embedded in the file.

Before restoring automatic parking: establish the installed firmware version,
verify physical endstops and software travel limits with a supervised machine
check, and correct the printer/slicer profiles. Home using the manufacturer's
procedure with a clear bed at print start. Do not blindly re-home over a partly
printed object on cancel or resume. Homing establishes coordinates, not guaranteed
collision protection; firmware limits must protect every motion source. This app
cannot guarantee safety for arbitrary uploaded G-code or a misconfigured machine.

References:
- https://um-support-files.ultimaker.com/Product-datasheet/Other/Ultimaker%202%2B%20series%20-%20Product%20data%20sheet.pdf
- https://docs.octoprint.org/en/main/features/gcode_scripts.html
- https://marlinfw.org/docs/hardware/endstops.html

## Dashboard refinements and action history

The progress card emphasizes time remaining, omitting zero hours (for example,
`27 minutes remaining`). Completion percentage sits beside elapsed time below the progress bar.
File icons sit on the left of each row, with red trash icons inside the right edge.
The Live View Refresh button immediately replaces the stream connection. Normal
temperature history omits its source badge; unavailable/demo states remain labeled.
Live View's header contains just the title and Refresh control; the live-stream
badge is omitted.
Progress, elapsed time and remaining-time estimate share one card. The event log
has one internal scrollbar; a new event returns it to the newest entry at the top.
SQLite `print_actions` records manual pause/cancel requests with file, UTC timestamp,
progress, elapsed time and outcome. The history view combines these with automatic
incidents and renders full local date/time. Existing accepted manual command events
are backfilled once, preserving their timestamps; unavailable elapsed/progress are
left blank. New external pause/cancel transitions are recorded as external/unknown,
not guessed to be manual or automatic. Polling can miss short external transitions;
this is not an exhaustive OctoPrint event subscription.

The printer adapter now pools its HTTP connections. This avoids synchronous client
setup during each telemetry poll, which was blocking MJPEG delivery. A local
12-second check after the change measured 131 frames and a 0.11-second maximum gap
(previous proxy sample: 1.26 seconds). Actual results depend on camera/network load.

### Cancel parking remains disabled on the current printer

The owner reports intermittent failure of the printer's own homing operations.
Do not enable automatic cancel homing until that fault is resolved. Leveling changes
nozzle clearance; it does not provide force-feedback collision detection. Moving
an axis manually can invalidate assumed coordinates. Inspect endstop actuation,
wiring and free travel using the manufacturer's troubleshooting procedure; do not
repeat movements that grind or collide to diagnose them remotely.

An optional UM2+-specific cancel hook is prepared in
`pi-module/gcode_scripts/ultimaker2plus/afterPrintCancelled`. After physical
verification of stock UM2+ homing/endstops, `configure_motion_scripts.py --apply
--verified-um2-homing` installs it: heaters off, Z homing to the bottom endstop first,
then X/Y homing. It uses no guessed parking coordinates. This option is **not
installed** on the current machine. Pause/resume and completion remain stationary.
Reference: https://support.makerbot.com/s/article/1667337905185

### Paired pause/resume coordinate parking (prepared, not enabled)

`parking_scripts.py` builds matched pause/resume/cancel hooks from a verified
configuration. Copy `pi-module/gcode_scripts/parking.example.json` to an ignored
local file and fill in physically verified travel limits and an interior parking
position. All verification flags intentionally default to false; coordinates have
no defaults. Install the updated root requirements before using this tool.

For a stock UM2+ where positive Z lowers the bed, pause first lowers the bed to
the verified park Z, then moves the head to park XY. It uses OctoPrint's captured
`pause_position`; resume first ensures bed clearance, returns to the saved XY,
then restores saved Z, E coordinate and feedrate. It never homes or extrudes
filament during the pause/resume sequence and does not change extrusion mode.
Only single-tool, absolute-XYZ prints streamed from OctoPrint are supported.
Do not jog, release motors, change leveling, or move the bed/head manually while
paused. Position capture cannot detect physical movement or skipped motor steps.

If the saved print height leaves less than the configured clearance below park Z,
both pause and resume remain stationary. Missing/out-of-range return coordinates
skip parking and abort a later resume with OctoPrint's `@cancel` host command.
Cancel always disables heaters and fan; it parks only if its captured position
is valid and there is sufficient clearance. Parking reduces contact/ooze on the
part; it does not guarantee prevention of hot-end clogs or heat creep.

After hardware repair and supervised verification, preview and install with:

```powershell
.\.venv\Scripts\python.exe configure_motion_scripts.py --parking-config local-backups/parking.json
.\.venv\Scripts\python.exe configure_motion_scripts.py --parking-config local-backups/parking.json --apply
```

The installer requires idle/offline state, checks the single-extruder profile,
backs up the scripts and position-logging flags, enables position logging for
both pause and cancel, and reads back the installed settings. It leaves the
completion hook stationary. The current Pi still uses stationary hooks because
intermittent endstop/travel failure has been reported. Do not enable parking just
to test whether an unsafe machine will collide again.

Reference: https://docs.octoprint.org/en/main/features/gcode_scripts.html

## Where to see and test detections

The Monitoring connection panel includes **Enable vision / Disable vision** in
live mode. Enable starts the existing inference publisher as a backend-owned,
headless process using this environment, `SNAPSHOT_URL`, and `VISION_BACKEND_URL`
(default `http://127.0.0.1:8000`). Its output goes to ignored `vision.log`. Model
loading initially shows Starting; Running requires a fresh live reading. Missing
dependencies/weights and unexpected process exits appear as Unavailable.

Enable does not arm automatic pause monitoring. Disable stops the managed process,
disarms monitoring, clears the current reading timestamp, and rejects incoming live
readings. The camera stream continues independently. Backend shutdown stops its
managed vision child, and repeated enable calls do not spawn duplicate workers.
If a publisher already runs externally, the toggle enables/disables acceptance of
its readings; stopping that external process must be done on its own host.
One-time dependency/model installation is still required for a fresh checkout;
the button never installs software or downloads a model automatically.

Fresh readings appear in Failure Signal and the confidence below Live View. A
sustained high-confidence failure while armed and printing produces a Print issue
detected banner with resume/cancel controls, a Printer event log message, and an
automatic pause row in Print issue history. The raw Live View does not draw model
boxes; inference and publication run separately. Unavailable/WAITING indicates no
fresh publisher results, not a healthy-print assessment.

For real camera recognition, install/download the vision components once, then
use Enable vision in the dashboard. Alternatively run the external publisher:

```powershell
.\.venv\Scripts\python.exe -m pip install -r vision/requirements.txt
.\.venv\Scripts\python.exe vision/src/download_model.py
.\.venv\Scripts\python.exe -m vision.src.pi_inference --snapshot-url "http://<pi-address>/webcam/?action=snapshot" --backend-url http://127.0.0.1:8000 --headless
```

Wait for fresh confidence values, then arm monitoring for a supervised print.
The threshold is confidence >=70 sustained for at least five seconds across fresh
samples. The publisher never arms monitoring itself. Do not change bed leveling
or force collisions to demonstrate failure. To test only response/logging, use a
separate mock backend and isolated database; synthetic results do not validate
the vision model. Never inject synthetic results into the live printer backend.

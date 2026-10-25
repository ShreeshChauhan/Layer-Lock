# Dashboard integration

The React dashboard already polls the FastAPI backend every three seconds.

| Page component | Data source | Remaining work |
|---|---|---|
| Printer state and progress | `/printer/status` | Defaults to mock; configure the existing OctoPrint/Moonraker backend adapter for real telemetry. |
| Failure risk, monitoring, events, chart | `/risk/status` | Real YOLO input requires the separate vision publisher; the chart is browser-session history. |
| Detection confidence and freshness | `/sensors/latest`, `/sensors/health` | Select live mode and run the Pi publisher; simulation mode uses generated readings. |
| Camera preview | `/camera/snapshot` | Configure backend `SNAPSHOT_URL`; refreshes at most once every 3 seconds per viewer, without overlapping requests. |
| Incidents and recovery guidance | `/incidents` | SQLite-backed; recovery/reset is simulation-only. Real resume remains manual. |
| Filament sensor | `filament_runout` in sensor readings | No Arduino publisher/firmware is present. The vision publisher defaults this field to false; that does not prove a sensor is connected. |
| Pi temperature and hardware health | Separate `pi-module` library | Not exposed by the backend or represented as live dashboard telemetry yet. |

Camera preview is independent of simulation/live sensor mode. It shows raw snapshots, not bounding boxes or the exact YOLO-sampled image. Its timestamp is backend receipt time, not camera capture time. Image failures hide the previous frame and retry; they do not inject healthy detection readings or change monitoring state.

## Run locally (PowerShell, repository root)

For persistent camera configuration, copy the root `.env.example` to `.env` and
set `SNAPSHOT_URL=http://10.26.82.5/webcam/?action=snapshot`. The local `.env` is
gitignored. The camera endpoint reads it by absolute repository path when no
process-level `SNAPSHOT_URL` is set, including when the file is created after
startup. A shell environment variable takes precedence. Configure the backend
the page actually uses (normally port 8000), not only a separate test server.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r vision/requirements.txt
$env:PRINTER_TYPE="mock"
$env:SNAPSHOT_URL="http://10.26.82.5/webcam/?action=snapshot"
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

Open http://127.0.0.1:5173. The supplied `?action=stream` URL is MJPEG; the backend uses `?action=snapshot` to fetch one JPEG. Backend requests have a five-second timeout and a 5 MB image limit. Missing configuration and camera failures are shown in the panel. The configured URL is server-side only; the endpoint does not accept arbitrary URLs or forward camera credentials to the browser.

For live detection, launch `vision.src.pi_inference` with the same snapshot URL and `--backend-url http://127.0.0.1:8000 --headless --conf 0.25`, then select live mode in the dashboard. Keep monitoring disarmed while validating: the existing backend can pause only when manually armed or explicitly commanded; the new camera endpoint never performs printer actions.

`frontend/.env.example` documents `VITE_API_URL`, shared by the dashboard, camera, and recovery panel. This is a build-time public URL, not a secret. For remote browsers, configure that URL and backend CORS origins together; the default setup supports localhost port 5173 only. Model weights remain local and gitignored.

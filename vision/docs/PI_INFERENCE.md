# Raspberry Pi snapshot inference

Install `requirements.txt` for the backend and `vision/requirements.txt` for vision.
Keep the existing weights in `vision/models/layerlock.pt`; for a fresh checkout,
run `python vision/src/download_model.py` first. The dashboard can launch the publisher with Enable vision after dependencies and weights are installed.

Run from the repository root, using the project's Python environment:

```powershell
python -m vision.src.pi_inference --snapshot-url "http://<pi-address>/webcam/?action=snapshot" --backend-url http://127.0.0.1:8000 --headless
# Direct script execution is also supported:
python vision/src/pi_inference.py --headless
```

| Option | Environment fallback | Default |
|---|---|---|
| `--snapshot-url` | `SNAPSHOT_URL` | `http://localhost:8080/?action=snapshot` |
| `--backend-url` | `BACKEND_URL` | `http://127.0.0.1:8000` |
| `--interval` | `PI_INTERVAL` | 3 seconds |
| `--timeout` | `HTTP_TIMEOUT` | 5 seconds per HTTP request |
| `--headless` | `HEADLESS=1` | Preview enabled |
| `--conf` | — | 0.25 |

CLI values override their environment fallbacks. These are process environment
variables; this script does not load a `.env` file. The backend URL is the base
URL, without `/live/update`. With `--headless`, no OpenCV window functions run.
If an enabled preview fails, inference continues with the preview disabled.
Ctrl+C stops either mode; Q also stops an active preview.

## Backend contract and operator control

The publisher calls `create_vision_payload()` and sends JSON to `POST /live/update`.
`camera_confidence` is an integer 0–100. The backend accepts numeric confidence in
that range and defaults `filament_runout` to false. The formatter's `failure_type`
and `timestamp` fields are currently ignored by the backend; freshness is based
on server receipt time. The publisher does not manufacture runout readings.

Real printer configuration starts in **live mode**. Mock printer operation can select Live vision source in the dashboard. While the backend remains
in simulation mode, updates receive HTTP 409; the publisher reports this and
continues sampling. Successful readings refresh the dashboard even while
monitoring is disarmed. Missing/stale readings prevent live arming; the current
backend freshness threshold is 10 seconds. Keep successful sampling plus inference
and network time below that threshold.

This program never switches mode, arms monitoring, or calls printer-control
endpoints. The backend applies the configured automatic-pause rules only when monitoring is armed and a print is active. Keep monitoring disarmed and the backend in mock
printer mode while validating the publisher. This publisher is not an isolation
boundary against an already-armed backend.

Camera/model failures skip publication rather than sending a false healthy zero.
HTTP errors, timeouts, and invalid backend responses are reported without stopping
the loop. The next sample is fresh; old readings are not queued or replayed.
Network and camera URLs must be reachable from the machine running this script.

## Tests

```powershell
python -m unittest discover -s vision/tests -p "test_*.py" -v
python -m unittest discover -s tests -t . -v
```

The backend contract test requires the root backend dependencies. Tests use mocked
camera/transport/printer operations and an isolated database; no real hardware,
printer commands, or notifications are sent. Actual Pi/OctoPrint connectivity,
headless deployment and sustained frame timing still need hardware validation.

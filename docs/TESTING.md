# Testing and validation

Run commands from the repository root after installing the backend and vision requirements. Tests use mocked printer/network operations and isolated temporary databases; they do not validate physical printer motion or model accuracy.

## Backend and integration tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t .
.\.venv\Scripts\python.exe -m unittest discover -s vision/tests
.\.venv\Scripts\python.exe -m unittest discover -s pi-module/tests
```

Backend coverage includes telemetry, file operations, command guards, sustained failure detection, pause/recovery, history persistence, camera streaming, vision process management, and conservative G-code generation. Vision tests cover publishing, the backend contract, and evaluation utilities. Pi tests exercise the standalone hardware library.

## Frontend and launcher checks

```powershell
cd frontend
node --test dev-backend.test.mjs
npm.cmd run lint
npm.cmd run build
```

Launcher tests use disposable local HTTP fixtures to check startup readiness, reuse of an existing service, failure reporting, and owned-process cleanup.

## Model evaluation

[Dataset evaluation](../vision/docs/DATASET_EVALUATION.md), [ROI evaluation](../vision/docs/ROI_EVALUATION.md), and [video evaluation](../vision/docs/TEST_VIDEOS.md) describe the separate model-evaluation workflows. Synthetic API readings test response and logging; they do not establish recognition accuracy.

Real printer validation requires supervised checks of camera placement, network connectivity, telemetry, endstops, installed motion scripts, and pause/resume behavior. Use the [integration guide](INTEGRATION.md) for operational constraints.

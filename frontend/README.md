# LayerLock dashboard

React and Vite interface for camera monitoring, printer control, temperature history, and incident review. Recharts renders telemetry and Lucide provides interface icons.

## Start

Install root Python dependencies and model weights using the [project setup guide](../README.md#run-layerlock), then run from this directory:

```powershell
npm.cmd ci
npm.cmd run dev
```

The development server starts the FastAPI backend when absent and proxies `/api` to it. An existing healthy backend is reused. Configuration is in `vite.config.js`; process management is in `dev-backend.mjs`.

## Source layout

- `src/App.jsx`: dashboard layout and shared command handling.
- `src/PrinterControls.jsx`: file management and printer actions.
- `src/CameraFeed.jsx`: continuous MJPEG video and reconnection.
- `src/RecoveryPanel.jsx`: detected-issue review and recovery.
- `src/TemperatureChart.jsx` and `src/RiskDial.jsx`: telemetry displays.
- `src/useDashboard.js` and `src/api.js`: polling, requests, and API configuration.
- `public/`: active branding assets.

Use npm with the committed `package-lock.json` for reproducible dependencies.

## Checks

```powershell
node --test dev-backend.test.mjs
npm.cmd run lint
npm.cmd run build
```

Production builds are written to ignored `dist/`. Deployment requires an API reverse proxy and appropriate access controls; see the [integration guide](../docs/INTEGRATION.md).

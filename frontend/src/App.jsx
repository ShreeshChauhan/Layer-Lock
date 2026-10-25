
import { useEffect, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Camera,
  CirclePower,
  Gauge,
  Printer,
  Radio,
  ShieldCheck,
  Terminal,
  History,
  RefreshCw,
  Wifi,
  WifiOff,
  Clock
} from "lucide-react";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid
} from "recharts";

import {
  initialReadings,
  generateMockReadings,
  toBackendPayload
} from "./mockData";

import RecoveryPanel from "./RecoveryPanel";
import "./App.css";

import { API } from "./api";
import CameraFeed from "./CameraFeed";
import RiskDial from "./RiskDial";

export default function App() {
  const [mode, setMode] = useState("simulation");
  const [switchingMode, setSwitchingMode] = useState(false);
  const [readings, setReadings] = useState(initialReadings);

  const [riskStatus, setRiskStatus] = useState({
    armed: false,
    state: "IDLE",
    risk_score: 0,
    paused: false,
    events: []
  });

  const [printer, setPrinter] = useState({
    state: "Connecting",
    progress: 0,
    simulated: true
  });

  const [sensorHealth, setSensorHealth] = useState({
    status: "WAITING",
    age_seconds: null,
    stale: false,
    threshold_seconds: 10,
    message: "Waiting for first sensor reading"
  });

  const [, setBackendReady] = useState(false);
  const [autoFeed, setAutoFeed] = useState(false);
  const [failureTesting, setFailureTesting] = useState(false);
  const [failureType, setFailureType] = useState(null);
  const [resetting, setResetting] = useState(false);
  const [pausing, setPausing] = useState(false);
  const [history, setHistory] = useState([]);
  const [error, setError] = useState("");

  const [incidents, setIncidents] = useState([]);
  const [incidentStats, setIncidentStats] = useState({
    total: 0,
    paused: 0,
    notified: 0,
    average_risk: 0
  });
  const [incidentsLoading, setIncidentsLoading] = useState(false);

  const [events, setEvents] = useState([
    {
      time: new Date().toLocaleTimeString(),
      text: "Dashboard initialized"
    }
  ]);

  const latestReadings = useRef(initialReadings);
  const failureTestingRef = useRef(false);
  const modeRef = useRef("simulation");

  const armed = riskStatus.armed;
  const risk = riskStatus.risk_score;
  const isPaused = printer.state?.toLowerCase() === "paused";
  const isWarning = riskStatus.state === "WARNING";
  const isLive = mode === "live";
  const sensorConnected = sensorHealth.status === "CONNECTED";
  const sensorStale = sensorHealth.status === "STALE";

  function addEvent(text) {
    setEvents(previous => [
      {
        time: new Date().toLocaleTimeString(),
        text
      },
      ...previous
    ].slice(0, 12));
  }

  async function request(path, options = {}) {
    const response = await fetch(`${API}${path}`, options);

    if (!response.ok) {
      const details = await response.json().catch(() => ({}));

      throw new Error(
        details.detail || `Request failed: ${response.status}`
      );
    }

    return response.json();
  }

  async function refreshPrinter() {
    try {
      const data = await request("/printer/status");
      setPrinter(data);
      return data;
    } catch (err) {
      console.error(err);
      setError("Unable to retrieve printer status");
      return null;
    }
  }

  async function refreshRisk() {
    try {
      const data = await request("/risk/status");
      setRiskStatus(data);
      setBackendReady(true);
      return data;
    } catch (err) {
      console.error(err);
      setBackendReady(false);
      setError("Risk engine disconnected");
      return null;
    }
  }

  async function refreshSensors() {
    try {
      const data = await request("/sensors/latest");

      if (data.health) {
        setSensorHealth(data.health);
      }

      if (modeRef.current === "live") {
        const next = {
          cameraConfidence: data.camera_confidence,
          progress: latestReadings.current.progress
        };

        latestReadings.current = next;
        setReadings(next);
      }

      return data;
    } catch (err) {
      console.error(err);
      return null;
    }
  }

  async function refreshSensorHealth() {
    try {
      const data = await request("/sensors/health");
      setSensorHealth(data);
      return data;
    } catch (err) {
      console.error(err);

      setSensorHealth(previous => ({
        ...previous,
        status: "DISCONNECTED",
        message: "Cannot reach sensor health API"
      }));

      return null;
    }
  }

  async function refreshIncidents() {
    setIncidentsLoading(true);

    try {
      const data = await request("/incidents?limit=100");

      setIncidents(data.incidents || []);
      setIncidentStats(data.stats || {
        total: 0,
        paused: 0,
        notified: 0,
        average_risk: 0
      });
    } catch (err) {
      console.error("Incident history error:", err);
    } finally {
      setIncidentsLoading(false);
    }
  }

  async function sendSensorData(data) {
    try {
      const result = await request("/risk/update", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(toBackendPayload(data))
      });

      setRiskStatus(result);
      setBackendReady(true);
      setError("");

      if (result.pause_result) {
        addEvent("Automatic printer pause triggered");

        if (result.notification_sent === true) {
          addEvent("Discord notification sent");
        } else if (result.notification_sent === false) {
          addEvent("Discord notification failed");
        }

        if (result.incident_id) {
          addEvent(
            `Incident #${result.incident_id} saved to history`
          );
        }

        await refreshPrinter();
        await refreshIncidents();
      }

      return result;
    } catch (err) {
      console.error(err);
      setError(err.message);
      return null;
    }
  }

  async function changeMode(nextMode) {
    if (
      switchingMode ||
      failureTestingRef.current ||
      resetting ||
      nextMode === mode
    ) {
      return;
    }

    setSwitchingMode(true);
    setAutoFeed(false);

    try {
      const result = await request(`/mode/${nextMode}`, {
        method: "POST"
      });

      modeRef.current = result.mode;
      setMode(result.mode);

      const next = {
        ...initialReadings,
        cameraConfidence: nextMode === "live" ? 0 : 12
      };

      latestReadings.current = next;
      setReadings(next);
      setHistory([]);
      setError("");

      setSensorHealth({
        status: "WAITING",
        age_seconds: null,
        stale: false,
        threshold_seconds: 10,
        message: "Waiting for first sensor reading"
      });

      await refreshRisk();
      await refreshSensors();

      addEvent(`Switched to ${nextMode.toUpperCase()} mode`);

      if (nextMode === "simulation") {
        setAutoFeed(true);
      }
    } catch (err) {
      console.error(err);
      setError(err.message);

      if (modeRef.current === "simulation") {
        setAutoFeed(true);
      }
    } finally {
      setSwitchingMode(false);
    }
  }

  async function toggleArm() {
    if (switchingMode || resetting || failureTesting) return;

    try {
      const endpoint = armed ? "disarm" : "arm";

      const result = await request(`/risk/${endpoint}`, {
        method: "POST"
      });

      setRiskStatus(result);
      setError("");

      addEvent(
        armed ? "Monitoring disarmed" : "Monitoring armed"
      );
    } catch (err) {
      setError(err.message);
    }
  }

  async function pausePrinter() {
    if (pausing || isPaused) return;

    setPausing(true);

    try {
      await request("/printer/pause", {
        method: "POST"
      });

      addEvent("Manual printer pause requested");

      await refreshPrinter();
      await refreshRisk();
    } catch (err) {
      setError(err.message);
      addEvent("Printer pause failed");
    } finally {
      setPausing(false);
    }
  }

  async function simulateCameraFailure() {
    if (
      isLive ||
      !armed ||
      isPaused ||
      failureTestingRef.current ||
      resetting
    ) {
      return;
    }

    failureTestingRef.current = true;
    setFailureTesting(true);
    setFailureType("camera");
    setAutoFeed(false);

    const failureData = {
      cameraConfidence: 95,
      progress: latestReadings.current.progress
    };

    latestReadings.current = failureData;
    setReadings(failureData);

    addEvent("Camera failure simulation started");

    try {
      for (let i = 0; i < 8; i++) {
        const result = await sendSensorData(failureData);

        if (!result) break;

        if (result.paused) {
          addEvent("Camera failure detected");
          break;
        }

        await new Promise(resolve =>
          setTimeout(resolve, 1000)
        );
      }

      await refreshPrinter();
    } finally {
      failureTestingRef.current = false;
      setFailureTesting(false);
      setFailureType(null);
    }
  }

  async function resetSensors() {
    if (isLive || failureTestingRef.current || resetting) return;

    setAutoFeed(false);

    const next = { ...initialReadings };

    latestReadings.current = next;
    setReadings(next);

    await sendSensorData(next);
    addEvent("Sensor readings reset");

    setAutoFeed(true);
  }

  async function resetAndResume() {
    if (
      isLive ||
      failureTestingRef.current ||
      resetting
    ) {
      return;
    }

    setResetting(true);
    setAutoFeed(false);

    try {
      const result = await request("/simulation/reset", {
        method: "POST"
      });

      const next = { ...initialReadings };

      latestReadings.current = next;
      setReadings(next);
      setRiskStatus(result);
      setHistory([]);
      setError("");

      addEvent("Simulation reset and resumed");

      await refreshPrinter();
      await refreshIncidents();
      await refreshSensorHealth();

      setAutoFeed(true);
    } catch (err) {
      setError(err.message);
      throw err;
    } finally {
      setResetting(false);
    }
  }

  useEffect(() => {
    let active = true;

    async function initialize() {
      try {
        const current = await request("/mode");

        if (!active) return;

        modeRef.current = current.mode;
        setMode(current.mode);
        setAutoFeed(current.mode === "simulation");
      } catch (err) {
        console.error(err);
        setAutoFeed(false);
        setError("Unable to load backend mode");
      }

      if (!active) return;

      await Promise.all([
        refreshPrinter(),
        refreshRisk(),
        refreshSensors(),
        refreshSensorHealth(),
        refreshIncidents()
      ]);
    }

    initialize();

    const timer = setInterval(async () => {
      if (!active) return;

      await Promise.all([
        refreshPrinter(),
        refreshRisk(),
        refreshSensors(),
        refreshSensorHealth(),
        refreshIncidents()
      ]);
    }, 3000);

    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!autoFeed || isLive) return;

    let stopped = false;
    let timer;

    async function updateSensors() {
      if (stopped) return;

      const next = generateMockReadings(
        latestReadings.current
      );

      latestReadings.current = next;
      setReadings(next);

      await sendSensorData(next);

      if (!stopped) {
        timer = setTimeout(updateSensors, 1000);
      }
    }

    timer = setTimeout(updateSensors, 1000);

    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [autoFeed, isLive]);

  useEffect(() => {
    setHistory(previous => [
      ...previous,
      {
        time: new Date().toLocaleTimeString(),
        risk: riskStatus.risk_score
      }
    ].slice(-30));
  }, [riskStatus.risk_score]);

  function formatDate(timestamp) {
    if (!timestamp) return "—";
    return new Date(timestamp).toLocaleString();
  }

  function healthColor(status) {
    if (status === "CONNECTED") return "var(--ok)";
    if (status === "STALE") return "var(--warning)";
    return "var(--fault)";
  }

  return (
    <div className="dashboard">
      <main className="main">
        <header className="topbar">
          <div>
            <div className="header-brand">
              <img className="brand-logo" src="/brand/wolf-engine.svg" alt="LayerLock wolf engine emblem" />
              <span>LAYER<span className="brand-accent">LOCK</span></span>
            </div>
            <div className="eyebrow">
              SBUHACKS STEEL &amp; STEAM / 3D PRINT MONITORING
            </div>

          </div>

          <button
            className={`arm-button ${armed ? "armed" : ""}`}
            onClick={toggleArm}
            disabled={switchingMode || failureTesting || resetting}
          >
            <CirclePower size={17} />
            {armed ? "System Armed" : "System Disarmed"}
          </button>
        </header>

        {error && (
          <div className="error-banner">{error}</div>
        )}

        <section
          className="panel source-panel"
          style={{ marginBottom: "20px", padding: "20px" }}
        >
          <div className="panel-header">
            <h2>
              <Radio size={18} />
              Data Source
            </h2>

            <span className="tag">
              {isLive ? "LIVE MODE" : "SIMULATION MODE"}
            </span>
          </div>

          <p style={{ marginBottom: "14px", color: "var(--muted)" }}>
            {isLive
              ? "Waiting for readings from connected components."
              : "Using simulated camera readings."}
          </p>

          <div
            style={{
              display: "flex",
              gap: "10px",
              flexWrap: "wrap"
            }}
          >
            <button
              className="secondary-btn"
              onClick={() => changeMode("simulation")}
              disabled={
                !isLive ||
                switchingMode ||
                failureTesting ||
                isPaused
              }
              style={{
                borderColor: !isLive ? "var(--ok)" : undefined
              }}
            >
              Simulation Mode
            </button>

            <button
              className="secondary-btn"
              onClick={() => changeMode("live")}
              disabled={
                isLive ||
                switchingMode ||
                failureTesting ||
                isPaused
              }
              style={{
                borderColor: isLive ? "var(--ok)" : undefined
              }}
            >
              Live Mode
            </button>
          </div>
        </section>

        {isLive && (
          <section
            className="panel health-panel"
            style={{
              padding: "20px",
              marginBottom: "20px",
              borderColor: sensorStale
                ? "var(--warning)"
                : undefined
            }}
          >
            <div className="panel-header">
              <h2>
                {sensorConnected ? (
                  <Wifi size={18} />
                ) : (
                  <WifiOff size={18} />
                )}
                Sensor Connection Health
              </h2>

              <span
                className="tag"
                style={{
                  color: healthColor(sensorHealth.status),
                  borderColor: healthColor(sensorHealth.status)
                }}
              >
                {sensorHealth.status}
              </span>
            </div>

            <div
              style={{
                display: "flex",
                gap: "24px",
                flexWrap: "wrap",
                marginTop: "12px"
              }}
            >
              <div>
                <p style={{ color: "var(--muted)", fontSize: "12px" }}>
                  LAST READING
                </p>

                <h3 style={{ marginTop: "6px" }}>
                  <Clock size={16} />{" "}
                  {sensorHealth.age_seconds === null
                    ? "Never"
                    : `${sensorHealth.age_seconds.toFixed(1)}s ago`}
                </h3>
              </div>

              <div>
                <p style={{ color: "var(--muted)", fontSize: "12px" }}>
                  STALE THRESHOLD
                </p>

                <h3 style={{ marginTop: "6px" }}>
                  {sensorHealth.threshold_seconds}s
                </h3>
              </div>

              <div>
                <p style={{ color: "var(--muted)", fontSize: "12px" }}>
                  MONITORING
                </p>

                <h3 style={{ marginTop: "6px" }}>
                  {armed ? "ARMED" : "DISARMED"}
                </h3>
              </div>
            </div>

            <p
              style={{
                marginTop: "16px",
                color: healthColor(sensorHealth.status)
              }}
            >
              {sensorHealth.message}
            </p>

            {!sensorConnected && (
              <p
                style={{
                  marginTop: "8px",
                  color: "var(--warning)",
                  fontSize: "13px"
                }}
              >
                Live monitoring cannot be armed until fresh
                sensor readings are received.
              </p>
            )}
          </section>
        )}

        {isWarning && (
          <div className="warning-banner">
            <AlertTriangle size={20} />
            HIGH FAILURE RISK DETECTED — CHECK PRINTER
          </div>
        )}

        {/* Recovery panel appears when a printer needs attention */}
        <RecoveryPanel
          printer={printer}
          riskStatus={riskStatus}
          mode={mode}
          onReset={resetAndResume}
          resetting={resetting}
        />

        <section className="stats-grid">
          <div className="panel stat">
            <div className="stat-label">
              <Printer size={18} />
              MACHINE STATUS
            </div>

            <div className="stat-value">
              {printer.state}
            </div>

            <div className="stat-footer">
              {printer.simulated
                ? "Simulation Printer"
                : "Connected Printer"}
            </div>
          </div>

          <div className={`panel stat risk-stat ${isWarning ? "risk-alert" : ""}`}>
            <div className="stat-label">
              <Gauge size={18} />
              FAILURE RISK
            </div>
            <RiskDial value={risk} />

            <div
              className={`stat-value ${
                isWarning ? "danger" : "green"
              }`}
            >
              {risk}%
            </div>

            <div className="stat-footer">
              {risk >= 70
                ? "High Risk"
                : risk >= 40
                ? "Moderate"
                : "Low Risk"}
            </div>
          </div>

          <div className="panel stat">
            <div className="stat-label">
              <Activity size={18} />
              PRINT PROGRESS
            </div>

            <div className="stat-value">
              {printer.progress ?? 0}%
            </div>

            <div className="progress-track">
              <div
                style={{
                  width: `${printer.progress ?? 0}%`
                }}
              />
            </div>
          </div>

          <div className="panel stat">
            <div className="stat-label">
              <ShieldCheck size={18} />
              MONITORING STATE
            </div>

            <div className="stat-value">
              {armed ? "ACTIVE" : "OFF"}
            </div>

            <div className="stat-footer">
              {isLive ? "Live Source" : "Simulation Source"}
            </div>
          </div>
        </section>

        <section className="content-grid">
          <div className="panel camera-panel">
            <CameraFeed />

            <div className="camera-footer">
              <span>
                <Radio size={15} />
                {isLive ? "Spaghetti confidence" : "Simulated detection confidence"}
              </span>

              <strong>
                {readings.cameraConfidence.toFixed(1)}%
              </strong>
            </div>
          </div>

          <div className="panel">
            <div className="panel-header">
              <h2>
                <Camera size={18} />
                Camera Detection
              </h2>

              <span className="tag">
                {isLive ? "LIVE DATA" : "MOCK DATA"}
              </span>
            </div>

            <div className="sensor">
              <div className="sensor-top">
                <span>{isLive ? "Spaghetti confidence" : "Simulated detection confidence"}</span>

                <strong>
                  {readings.cameraConfidence.toFixed(1)}%
                </strong>
              </div>

              <div className="sensor-track">
                <div
                  style={{
                    width: `${readings.cameraConfidence}%`
                  }}
                />
              </div>
            </div>

          </div>

          <div className="panel chart-panel">
            <div className="panel-header">
              <h2>
                <Activity size={18} />
                Failure Risk History
              </h2>

              <span className="tag">LAST 30 SAMPLES</span>
            </div>

            <div className="chart-container">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={history}>
                  <CartesianGrid
                    stroke="var(--line)"
                    strokeDasharray="3 3"
                  />

                  <XAxis dataKey="time" hide />

                  <YAxis
                    domain={[0, 100]}
                    stroke="var(--muted)"
                  />

                  <Tooltip contentStyle={{ background: "var(--iron)", border: "1px solid var(--brass)", borderRadius: 0 }} />

                  <Line
                    type="monotone"
                    dataKey="risk"
                    stroke="var(--brass)"
                    strokeWidth={3}
                    dot={false}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="panel logs-panel">
            <div className="panel-header">
              <h2>
                <Terminal size={18} />
                Event Log
              </h2>

              <span className="tag">SYSTEM EVENTS</span>
            </div>

            {[
              ...(riskStatus.events || []).map(event => ({
                time: event.time,
                text: event.message
              })),
              ...events
            ].map((event, index) => (
              <div className="event" key={index}>
                <span>{event.time}</span>
                <p>{event.text}</p>
              </div>
            ))}
          </div>
        </section>

        <section
          className="panel controls-panel"
          style={{ marginBottom: "20px" }}
        >
          <div>
            <h2>System Controls</h2>

            <p>
              Manual controls and failure simulation
            </p>
          </div>

          <div className="controls">
            <button
              className="secondary-btn"
              onClick={simulateCameraFailure}
              disabled={
                isLive ||
                !armed ||
                failureTesting ||
                resetting ||
                isPaused
              }
            >
              {failureTesting && failureType === "camera"
                ? "Testing Camera..."
                : "Simulate Camera Failure"}
            </button>



            <button
              className="secondary-btn"
              onClick={resetSensors}
              disabled={isLive || failureTesting || resetting}
            >
              Reset Sensors
            </button>

            <button
              className="secondary-btn"
              onClick={resetAndResume}
              disabled={
                isLive ||
                failureTesting ||
                resetting ||
                isPaused
              }
              title={
                isPaused
                  ? "Use the Recovery Panel to confirm reset"
                  : "Reset the simulation"
              }
            >
              {resetting ? "Resetting..." : "Reset & Resume"}
            </button>

            <button
              className="danger-btn"
              onClick={pausePrinter}
              disabled={pausing || isPaused || resetting}
            >
              {pausing ? "Pausing..." : "Pause Printer"}
            </button>
          </div>
        </section>

        <section
          className="panel"
          style={{ padding: "20px", marginBottom: "24px" }}
        >
          <div className="panel-header">
            <h2>
              <History size={18} />
              Incident Log
            </h2>

            <button
              className="secondary-btn"
              onClick={refreshIncidents}
              disabled={incidentsLoading}
            >
              <RefreshCw size={15} />
              {incidentsLoading ? "Loading..." : "Refresh"}
            </button>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns:
                "repeat(auto-fit, minmax(140px, 1fr))",
              gap: "12px",
              marginBottom: "20px"
            }}
          >
            {[
              ["Total Incidents", incidentStats.total],
              ["Successful Pauses", incidentStats.paused],
              ["Discord Alerts", incidentStats.notified],
              [
                "Average Risk",
                `${Number(
                  incidentStats.average_risk || 0
                ).toFixed(1)}%`
              ]
            ].map(([label, value]) => (
              <div
                key={label}
                style={{
                  padding: "16px",
                  border: "1px solid var(--line)",
                  borderRadius: "2px"
                }}
              >
                <p
                  style={{
                    color: "var(--muted)",
                    fontSize: "12px",
                    marginBottom: "8px"
                  }}
                >
                  {label}
                </p>

                <strong
                  style={{
                    fontSize: "24px",
                    color: "var(--ok)"
                  }}
                >
                  {value}
                </strong>
              </div>
            ))}
          </div>

          {incidents.length === 0 ? (
            <div
              style={{
                textAlign: "center",
                padding: "30px",
                color: "var(--muted)"
              }}
            >
              <History size={30} />

              <p style={{ marginTop: "12px" }}>
                No failure incidents recorded yet.
              </p>

              <p>
                Simulate a failure to create your first incident.
              </p>
            </div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table
                style={{
                  width: "100%",
                  borderCollapse: "collapse",
                  textAlign: "left",
                  fontSize: "13px"
                }}
              >
                <thead>
                  <tr>
                    {[
                      "ID",
                      "Time",
                      "Mode",
                      "Failure",
                      "Risk",
                      "Pause",
                      "Discord"
                    ].map(heading => (
                      <th
                        key={heading}
                        style={{
                          padding: "12px",
                          borderBottom: "1px solid var(--line)",
                          color: "var(--muted)"
                        }}
                      >
                        {heading}
                      </th>
                    ))}
                  </tr>
                </thead>

                <tbody>
                  {incidents.map(incident => (
                    <tr key={incident.id}>
                      <td style={{ padding: "12px" }}>
                        #{incident.id}
                      </td>

                      <td style={{ padding: "12px" }}>
                        {formatDate(incident.timestamp)}
                      </td>

                      <td style={{ padding: "12px" }}>
                        {incident.mode}
                      </td>

                      <td style={{ padding: "12px" }}>
                        {incident.failure_type}
                      </td>

                      <td style={{ padding: "12px" }}>
                        {incident.risk_score}%
                      </td>

                      <td
                        style={{
                          padding: "12px",
                          color: incident.pause_success
                            ? "var(--ok)"
                            : "var(--fault)"
                        }}
                      >
                        {incident.pause_success
                          ? "SUCCESS"
                          : "FAILED"}
                      </td>

                      <td
                        style={{
                          padding: "12px",
                          color: incident.notification_sent
                            ? "var(--ok)"
                            : "var(--fault)"
                        }}
                      >
                        {incident.notification_sent
                          ? "SENT"
                          : "FAILED"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

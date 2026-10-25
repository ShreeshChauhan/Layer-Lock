
import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  RotateCcw,
  ShieldAlert,
  ShieldCheck
} from "lucide-react";

import { API } from "./api";

const recoveryInstructions = {
  "Filament Runout": [
    "Inspect the printer and filament path.",
    "Replace or reload the filament.",
    "Check that the nozzle can extrude normally.",
    "Confirm the printer is ready before restarting."
  ],
  "Camera Failure": [
    "Inspect the print for detached or deformed layers.",
    "Check whether the print has separated from the bed.",
    "Remove any loose material around the nozzle.",
    "Confirm that the print can safely continue."
  ]
};

export default function RecoveryPanel({
  printer,
  riskStatus,
  mode,
  onReset,
  resetting
}) {
  const [incident, setIncident] = useState(null);
  const [confirmed, setConfirmed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const paused =
    printer?.state?.toLowerCase() === "paused";

  const simulated = printer?.simulated === true;

  useEffect(() => {
    setConfirmed(false);

    if (!paused) {
      setIncident(null);
      setError("");
      return;
    }

    let cancelled = false;

    async function loadIncident() {
      setLoading(true);

      try {
        const response = await fetch(
          `${API}/incidents?limit=1`
        );

        if (!response.ok) {
          throw new Error(
            "Unable to retrieve incident history"
          );
        }

        const data = await response.json();
        const latest = data.incidents?.[0] || null;

        if (cancelled) return;

        // An old incident should never be presented
        // as the cause of the current pause.
        const age = latest
          ? Date.now() - new Date(latest.timestamp).getTime()
          : Infinity;

        const recent =
          age >= 0 &&
          age <= 120000 &&
          latest.mode === mode;

        setIncident(recent ? latest : null);
        setError("");
      } catch (err) {
        if (!cancelled) {
          setError(err.message);
          setIncident(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadIncident();

    return () => {
      cancelled = true;
    };
  }, [paused, mode]);

  if (!paused) {
    return (
      <section
        className="panel recovery-idle"
        style={{
          padding: "22px",
          marginBottom: "20px"
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "12px"
          }}
        >
          <ShieldCheck
            size={25}
            color="var(--ok)"
          />

          <div>
            <h2>Printer Recovery</h2>
            <p style={{ color: "var(--muted)" }}>
              No active printer pause requiring recovery.
            </p>
          </div>
        </div>
      </section>
    );
  }

  const failureType =
    incident?.failure_type || "Printer Paused";

  const instructions =
    recoveryInstructions[failureType] || [
      "Inspect the printer to determine why it paused.",
      "Check the print bed, nozzle, and filament.",
      "Resolve any physical issue before continuing.",
      "Confirm that the printer is safe to operate."
    ];

  const canReset =
    simulated &&
    mode === "simulation" &&
    confirmed &&
    !resetting;

  async function handleReset() {
    if (!canReset) return;

    setError("");

    try {
      await onReset();
    } catch (err) {
      setError(err.message || "Reset failed");
    }
  }

  return (
    <section
      className="panel recovery-alert"
      style={{
        padding: "24px",
        marginBottom: "20px",
        border: "1px solid var(--copper)"
      }}
    >
      <div
        style={{
          display: "flex",
          gap: "12px",
          alignItems: "flex-start",
          marginBottom: "20px"
        }}
      >
        <AlertTriangle
          size={28}
          color="var(--warning)"
        />

        <div>
          <h2 style={{ color: "var(--warning)" }}>
            Printer Paused — Action Required
          </h2>

          <p style={{ color: "var(--muted)" }}>
            Review the incident before restarting
            the simulated printer.
          </p>
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns:
            "repeat(auto-fit, minmax(160px, 1fr))",
          gap: "12px",
          marginBottom: "22px"
        }}
      >
        <div>
          <p style={{ color: "var(--muted)" }}>
            FAILURE TYPE
          </p>

          <strong>{failureType}</strong>
        </div>

        <div>
          <p style={{ color: "var(--muted)" }}>
            RISK SCORE
          </p>

          <strong>
            {incident
              ? `${incident.risk_score}%`
              : `${riskStatus?.risk_score ?? 0}%`}
          </strong>
        </div>

        <div>
          <p style={{ color: "var(--muted)" }}>
            PRINTER MODE
          </p>

          <strong>
            {simulated ? "Simulation" : "Real Printer"}
          </strong>
        </div>

        <div>
          <p style={{ color: "var(--muted)" }}>
            PAUSE STATUS
          </p>

          <strong style={{ color: "var(--warning)" }}>
            PAUSED
          </strong>
        </div>
      </div>

      {incident && (
        <div
          style={{
            marginBottom: "18px",
            color: "var(--muted)",
            fontSize: "13px"
          }}
        >
          <Clock
            size={14}
            style={{
              display: "inline",
              marginRight: "6px"
            }}
          />

          Recent incident #{incident.id} recorded{" "}
          {new Date(incident.timestamp).toLocaleString()}
        </div>
      )}

      {loading && (
        <p style={{ color: "var(--muted)" }}>
          Checking recent incident history...
        </p>
      )}

      <h3 style={{ marginBottom: "12px" }}>
        Recommended Recovery Steps
      </h3>

      <ol
        style={{
          paddingLeft: "22px",
          lineHeight: "2",
          color: "var(--text)",
          marginBottom: "20px"
        }}
      >
        {instructions.map(step => (
          <li key={step}>{step}</li>
        ))}
      </ol>

      <div
        style={{
          padding: "16px",
          background: "rgba(245, 166, 35, 0.08)",
          border: "1px solid rgba(245, 166, 35, 0.25)",
          borderRadius: "2px",
          marginBottom: "18px"
        }}
      >
        <div
          style={{
            display: "flex",
            gap: "10px",
            alignItems: "flex-start"
          }}
        >
          <ShieldAlert
            size={20}
            color="var(--warning)"
          />

          <p style={{ fontSize: "13px" }}>
            This panel cannot verify physical printer
            safety. Reset & Resume only changes the
            simulated printer state. Never use it to
            automatically resume real hardware.
          </p>
        </div>
      </div>

      {simulated && mode === "simulation" ? (
        <>
          <label
            style={{
              display: "flex",
              alignItems: "center",
              gap: "10px",
              cursor: "pointer",
              marginBottom: "18px"
            }}
          >
            <input
              type="checkbox"
              checked={confirmed}
              onChange={event =>
                setConfirmed(event.target.checked)
              }
            />

            <span>
              I have reviewed the recovery steps
              and want to reset this simulation.
            </span>
          </label>

          <button
            className="secondary-btn"
            disabled={!canReset}
            onClick={handleReset}
          >
            <RotateCcw size={17} />
            {resetting
              ? "Resetting..."
              : "Confirm Reset & Resume"}
          </button>
        </>
      ) : (
        <p style={{ color: "var(--warning)" }}>
          Automatic recovery is unavailable for
          real printer mode.
        </p>
      )}

      {error && (
        <p
          style={{
            marginTop: "12px",
            color: "var(--fault)"
          }}
        >
          {error}
        </p>
      )}
    </section>
  );
}

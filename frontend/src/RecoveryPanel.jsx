import { AlertTriangle } from 'lucide-react';

export default function RecoveryPanel({ printer, riskStatus, incident, unavailable, busy, onReview }) {
  if (!printer?.paused && !riskStatus?.paused && !incident) return null;
  const needsReview = printer?.paused || riskStatus?.paused;
  return <section className="panel recovery-alert" role="alert">
    <div className="panel-header"><h2><AlertTriangle size={22} /> {incident ? 'Print issue detected' : 'Print paused'}</h2>
      <span className="tag">{printer?.paused ? 'PAUSED' : riskStatus?.paused ? 'PAUSE REQUESTED' : 'REVIEW REQUIRED'}</span></div>
    <p>{incident ? `${incident.failure_type} — incident #${incident.id}. ${incident.file_name || 'Current print'}` : 'Inspect the print before continuing.'}</p>
    {incident && <p className="muted">{incident.pause_success ? 'Pause command accepted.' : 'Automatic pause failed. Inspect the printer immediately.'} Discord alert: {incident.notification_sent ? 'sent' : 'not sent'}.</p>}
    <p>Check the print, nozzle, bed adhesion, and filament. Resolve the issue before resuming, or cancel the print.</p>
    <div className="controls">
      <button className="secondary-btn" disabled={busy || unavailable || !printer?.paused} onClick={() => onReview('resume')}>Review & resume</button>
      <button className="danger-btn" disabled={busy || unavailable || (!printer?.printing && !needsReview)} onClick={() => onReview('cancel')}>Cancel print</button>
    </div>
    {!printer?.paused && riskStatus?.paused && <p className="muted">Waiting for printer telemetry to confirm the pause.</p>}
  </section>;
}

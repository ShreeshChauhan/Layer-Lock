import { useEffect, useRef, useState } from 'react';
import { Activity, CirclePower, Clock, Gauge, History, Printer, RefreshCw, Terminal } from 'lucide-react';
import CameraFeed from './CameraFeed';
import PrinterControls from './PrinterControls';
import RecoveryPanel from './RecoveryPanel';
import RiskDial from './RiskDial';
import TemperatureChart from './TemperatureChart';
import useDashboard, { request } from './useDashboard';
import './App.css';
import { stateClass } from './printerState';

function duration(seconds) {
  if (seconds == null) return '—';
  const minutes = Math.floor(Math.max(0, seconds) / 60);
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}
function date(value) { return value ? new Date(value).toLocaleString() : '—'; }

function ReviewDialog({ action, file, busy, error, onClose, onConfirm }) {
  const [confirmed, setConfirmed] = useState(false);
  const dialog = useRef(null);
  useEffect(() => {
    const element = dialog.current;
    element.showModal();
    return () => element.close();
  }, []);
  const descriptions = {
    start: `Start ${file}? Confirm that the bed is clear and the printer is ready.`,
    resume: 'Inspect the printer and resolve the issue before resuming. The nozzle must be hot enough to resume.',
    cancel: 'Cancel the current print? This job cannot be resumed after cancellation.',
  };
  return <dialog ref={dialog} className="panel command-dialog" aria-labelledby="review-title"
    onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
      <h2 id="review-title">{action} print</h2>
      <p>{descriptions[action]}</p>
      {error && <p className="error-banner" role="alert">{error}</p>}
      <label className="confirmation"><input autoFocus type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />
        {action === 'cancel' ? 'I want to cancel this print.' : 'I have checked the printer and it is ready.'}</label>
      <div className="controls"><button className="secondary-btn" disabled={busy} onClick={onClose}>Go back</button>
        <button className={action === 'cancel' ? 'danger-btn' : 'secondary-btn'} disabled={!confirmed || busy} onClick={onConfirm}>
          {busy ? 'Sending…' : `Confirm ${action}`}</button></div>
  </dialog>;
}

export default function App() {
  const { data, error: connectionError, refresh } = useDashboard();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [review, setReview] = useState(null);
  const [selectedFile, setSelectedFile] = useState('');
  const printer = data?.printer;
  const risk = data?.risk;
  const sensor = data?.sensor;
  const unavailable = Boolean(connectionError || data?.printer_error || !printer?.connected);
  const simulated = printer?.simulated === true;
  const live = data?.mode === 'live';
  const freshSensor = sensor?.health?.status === 'CONNECTED';
  const validTelemetry = printer && !unavailable;
  const progress = validTelemetry ? printer.progress : null;

  async function command(path, body) {
    if (busy) return;
    setBusy(true); setError('');
    try {
      await request(path, { method: 'POST', ...(body ? { body: JSON.stringify(body) } : {}) });
      setReview(null);
      await refresh();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  function openReview(action) { setError(''); setReview(action); }
  return <div className="dashboard"><main className="main">
    <header className="topbar"><div>
      <div className="header-brand"><img className="brand-logo" src="/brand/wolf-engine.svg" alt="LayerLock emblem" />
        <span>LAYER<span className="brand-accent">LOCK</span></span></div>
      <div className="eyebrow">3D PRINT MONITORING / {simulated ? 'MOCK PRINTER' : 'CONNECTED PRINTER'}</div>
    </div><button className={`arm-button ${risk?.armed ? 'armed' : ''}`}
      disabled={busy || !data || Boolean(connectionError) || (!risk?.armed && (unavailable || risk?.paused || (live && !freshSensor)))}
      onClick={() => command(`/risk/${risk?.armed ? 'disarm' : 'arm'}`)}>
      <CirclePower size={17} />{risk?.armed ? 'Monitoring armed' : 'Arm monitoring'}</button></header>

    {(error || connectionError || data?.printer_error) && <div className="error-banner" role="alert">{error || connectionError || data.printer_error}</div>}
    <section className="panel connection-panel">
      <div><h2><Activity size={18} /> Monitoring connection</h2>
        <p className="muted">{simulated ? 'Demo printer telemetry. Configure OctoPrint on the backend for real readings.' : 'Printer telemetry and actions are provided by OctoPrint.'}</p>
        <p>Vision: <strong>{live ? sensor?.health?.status || 'WAITING' : 'SIMULATION SOURCE'}</strong>
          {sensor?.health?.age_seconds != null && ` · last reading ${sensor.health.age_seconds.toFixed(1)}s ago`}</p>
        <p className="muted">{risk?.armed ? 'Detected issues automatically pause the print and create an incident.' : 'Arm monitoring to enable automatic failure pauses.'}</p>
      </div>
      {simulated && <div className="controls"><button className="secondary-btn" disabled={busy || !live || risk?.paused}
        onClick={() => command('/mode/simulation')}>Simulation source</button>
        <button className="secondary-btn" disabled={busy || live || risk?.paused}
          onClick={() => command('/mode/live')}>Live vision source</button></div>}
    </section>

    <RecoveryPanel printer={validTelemetry ? printer : null} riskStatus={risk} incident={data?.active_incident}
      unavailable={unavailable} busy={busy} onReview={openReview} />
    <section className="stats-grid">
      <article className="panel stat"><div className="stat-label"><Printer /> MACHINE STATUS</div>
        <div className={`stat-value ${stateClass(validTelemetry ? printer.state : 'Unavailable')}`}>{validTelemetry ? printer.state : data ? 'Unavailable' : 'Connecting'}</div>
        <div className="stat-footer">{validTelemetry ? printer.file || 'No file selected' : 'Waiting for printer telemetry'}</div></article>
      <article className="panel stat"><div className="stat-label"><Activity /> PRINT PROGRESS</div>
        <div className="stat-value">{progress == null ? '—' : `${progress.toFixed(1)}%`}</div>
        <div className="progress-track"><div style={{ width: `${Math.max(0, Math.min(100, progress || 0))}%` }} /></div></article>
      <article className="panel stat"><div className="stat-label"><Clock /> TIME REMAINING</div>
        <div className="stat-value">{duration(validTelemetry ? printer.print_time_left : null)}</div>
        <div className="stat-footer">Elapsed: {duration(validTelemetry ? printer.print_time : null)} · OctoPrint estimate</div></article>
      <article className={`panel stat risk-stat ${risk?.state === 'WARNING' ? 'risk-alert' : ''}`}>
        <div className="stat-label"><Gauge /> FAILURE SIGNAL</div>
        <RiskDial value={freshSensor ? risk?.risk_score : 0} />
        <div className="stat-value">{freshSensor ? `${risk?.risk_score}%` : '—'}</div>
        <div className="stat-footer">{freshSensor ? risk?.state : 'No fresh detection'}</div></article>
    </section>

    <section className="content-grid monitor-grid">
      <div className="panel camera-panel"><CameraFeed /><div className="camera-footer">
        <span>Spaghetti detection confidence</span><strong>{freshSensor ? `${sensor.camera_confidence.toFixed(1)}%` : 'Unavailable'}</strong></div></div>
      <PrinterControls printer={printer} unavailable={unavailable} busy={busy} selectedFile={selectedFile}
        onSelect={setSelectedFile} onReview={openReview} onCommand={command} />
    </section>
    <section className="content-grid telemetry-grid">
      <TemperatureChart history={data?.temperature_history} simulated={simulated} unavailable={unavailable} />
      <section className="panel logs-panel"><div className="panel-header"><h2><Terminal size={18} /> Printer event log</h2><span className="tag">LATEST 100</span></div>
        <div className="event-list">{data?.events?.length ? data.events.map(event => <div className="event" key={event.id}>
          <span>{date(event.timestamp)}</span><p>{event.message}{event.simulated ? ' (demo)' : ''}</p>
        </div>) : <p className="muted">Waiting for printer events…</p>}</div>
        <p className="muted">Commands and observed printer state/target changes. Very brief external transitions between polls may not appear.</p>
      </section>
    </section>

    <section className="panel incident-panel"><div className="panel-header"><h2><History size={18} /> Print issue history</h2>
      <button className="secondary-btn" onClick={refresh} disabled={busy}><RefreshCw size={15} /> Refresh</button></div>
      <p className="muted">{data?.incident_stats?.total ?? 0} recorded issues. History is retained after resume or cancel.</p>
      {data?.incidents?.length ? <div className="table-scroll"><table><thead><tr>
        {['Time', 'Print', 'Issue', 'Progress', 'Pause request', 'Alert', 'Resolution'].map(title => <th key={title}>{title}</th>)}
      </tr></thead><tbody>{data.incidents.map(incident => <tr key={incident.id}>
        <td>{date(incident.timestamp)}</td><td>{incident.file_name || 'Unknown'}{incident.mode === 'simulation' ? ' (demo)' : ''}</td>
        <td>{incident.failure_type}</td><td>{incident.print_progress == null ? '—' : `${incident.print_progress.toFixed(1)}%`}</td>
        <td>{incident.pause_success ? 'Accepted' : 'Failed'}</td><td>{incident.notification_sent ? 'Sent' : 'Not sent'}</td>
        <td>{incident.resolution?.replaceAll('_', ' ') || 'pending'}</td>
      </tr>)}</tbody></table></div> : <p className="empty-state">No print issues recorded.</p>}
    </section>
    {review && <ReviewDialog key={review} action={review} file={selectedFile} busy={busy} error={error} onClose={() => setReview(null)}
      onConfirm={() => command(`/printer/${review}`, { confirmed: true, ...(review === 'start' ? { path: selectedFile } : {}) })} />}
  </main></div>;
}

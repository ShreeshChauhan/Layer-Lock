import { useEffect, useRef, useState } from 'react';
import { Check, FileCode, Home, Pause, Play, Printer, RefreshCw, Upload, X, Trash2 } from 'lucide-react';
import { request } from './useDashboard';
import { stateClass } from './printerState';

const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
function sizeLabel(bytes) {
  if (bytes == null) return 'Size unavailable';
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${(bytes / 1024).toFixed(1)} KB`;
}

export default function PrinterControls({ printer, unavailable, busy, selectedFile, onSelect, onReview, onCommand }) {
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [search, setSearch] = useState('');
  const [deleting, setDeleting] = useState(false);
  const fileInput = useRef(null);
  const uploadInFlight = useRef(false);
  const selected = files.find(file => file.path === selectedFile);
  const paused = Boolean(printer?.paused);
  const active = Boolean(printer?.printing || paused);
  const canHome = !busy && !unavailable && !active && printer?.operational && printer?.state?.toLowerCase() === 'operational';
  const selectionLocked = busy || deleting || unavailable || active || printer?.state?.toLowerCase() !== 'operational';
  const maySelect = useRef(false);
  useEffect(() => { maySelect.current = !selectionLocked; }, [selectionLocked]);
  function fileInUse(file) {
    if ((!active && printer?.state?.toLowerCase() === 'operational') || printer?.file_origin === 'sdcard') return false;
    if (printer?.file_path) return file.path === printer.file_path;
    return !printer?.file || file.name === printer.file || file.path.split('/').pop() === printer.file;
  }
  const canPrint = !unavailable && !busy && !uploading && Boolean(selected) && printer?.state?.toLowerCase() === 'operational';

  useEffect(() => {
    let mounted = true;
    request('/printer/files').then(result => { if (mounted) setFiles(result.files); })
      .catch(err => { if (mounted) setError(err.message); })
      .finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, []);

  async function refreshFiles() {
    setLoading(true); setError('');
    try {
      const result = await request('/printer/files');
      setFiles(result.files);
      if (selectedFile && !result.files.some(file => file.path === selectedFile)) onSelect('');
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }

  async function uploadFile(event) {
    const file = event.target.files?.[0];
    event.target.value = ''; // Selecting the same local file again must still work.
    if (!file || uploadInFlight.current) return;
    setError(''); setMessage('');
    if (!/\.(gcode|gco|g)$/i.test(file.name)) { setError('Choose a sliced G-code file (.gcode, .gco, or .g).'); return; }
    if (!file.size) { setError('The selected file is empty.'); return; }
    if (file.size > MAX_UPLOAD_BYTES) { setError('Choose a G-code file smaller than 100 MB.'); return; }
    uploadInFlight.current = true;
    setUploading(true);
    try {
      const result = await request(`/printer/files/upload?filename=${encodeURIComponent(file.name)}`, {
        method: 'POST', body: file, timeoutMs: 150000,
      });
      setFiles(previous => [...previous.filter(item => item.path !== result.file.path), result.file]);
      if (maySelect.current) onSelect(result.file.path);
      setSearch('');
      setMessage(`Uploaded ${result.file.path}.`);
    } catch (err) { setError(err.message); }
    finally { uploadInFlight.current = false; setUploading(false); }
  }

  async function deleteFile(remove) {
    if (deleting) return;
    setDeleting(true); setError('');
    try {
      await request(`/printer/files?path=${encodeURIComponent(remove)}`, { method: 'DELETE' });
      setFiles(previous => previous.filter(file => file.path !== remove));
      if (selectedFile === remove) onSelect('');
      setMessage(`Removed ${remove}.`);
    } catch (err) { setError(err.message); }
    finally { setDeleting(false); }
  }

  const visibleFiles = files.filter(file => file.path.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => (b.date || 0) - (a.date || 0) || a.path.localeCompare(b.path));
  return <section className="panel printer-controls" aria-label="Printer controls">
    <div className="panel-header"><h2><Printer size={18} /> Printer controls</h2>
      <span className={`tag ${unavailable ? 'connection-down' : 'connection-up'}`}>{unavailable ? 'UNAVAILABLE' : 'CONNECTED'}</span></div>
    <dl className="printer-details">
      <div><dt>State</dt><dd className={stateClass(unavailable ? 'Unavailable' : printer?.state)}>{unavailable ? 'Unavailable' : printer?.state || 'Connecting'}</dd></div>
      <div><dt>Active file</dt><dd>{unavailable ? 'Unavailable' : printer?.file || 'None'}</dd></div>
      <div><dt>Selected file</dt><dd>{selected?.path || 'Select a file below'}</dd></div>
    </dl>
    <div className="controls print-actions">
      <button className="primary-btn" disabled={!canPrint} onClick={() => onReview('start')}><Play size={15} /> Print</button>
      <button className="secondary-btn" disabled={busy || unavailable || !active}
        onClick={() => paused ? onReview('resume') : onCommand('/printer/pause')}>
        {paused ? <Play size={15} /> : <Pause size={15} />}{paused ? 'Resume' : 'Pause'}</button>
      <button className="danger-btn" disabled={busy || unavailable || !active} onClick={() => onReview('cancel')}><X size={15} /> Cancel</button>
    </div>
    <div className="controls homing-controls" aria-label="Printer homing controls">
      <button type="button" className="secondary-btn" disabled={!canHome} onClick={() => onCommand('/printer/home/bed')}>
        <Home size={15} /> Home bed</button>
      <button type="button" className="secondary-btn" disabled={!canHome} onClick={() => onCommand('/printer/home/head')}>
        <Home size={15} /> Home head</button>
    </div>
    <p className="muted homing-note">Idle printer only. Clear the bed and home the bed before the head.
      Homing relies on working endstops; do not use while the reported grinding or homing fault persists.</p>
    <div className="files-heading"><h2><FileCode size={17} /> Uploaded files <span className="file-count">{files.length}</span></h2>
      <button type="button" className="secondary-btn" aria-label="Refresh uploaded files" disabled={loading || uploading}
        onClick={refreshFiles}><RefreshCw size={15} /></button></div>
    <div className="upload-controls">
      <input ref={fileInput} type="file" accept=".gcode,.gco,.g" hidden onChange={uploadFile} aria-label="Upload G-code file" />
      <button type="button" className="secondary-btn upload-btn" disabled={uploading || loading} onClick={() => fileInput.current.click()}>
        <Upload size={16} />{uploading ? 'Uploading…' : 'Upload G-code'}</button>
      <span className="muted">Sliced G-code · up to 100 MB</span>
    </div>
    {error && <p className="file-error" role="alert">{error}</p>}
    <p className="upload-status" role="status">{uploading ? 'Saving file to printer storage…' : message}</p>
    <input className="file-search" type="search" aria-label="Search uploaded files" placeholder="Search files…"
      value={search} onChange={event => setSearch(event.target.value)} />
    <div className="uploaded-files" aria-label="Uploaded G-code files" aria-busy={loading}>
      {loading ? <p className="muted">Loading uploaded files…</p> : visibleFiles.length ? visibleFiles.map(file =>
        <div className={`file-entry ${selectedFile === file.path ? 'selected' : ''}`} key={file.path}><button type="button" className="file-row"
          aria-pressed={selectedFile === file.path} disabled={selectionLocked} onClick={() => onSelect(file.path)}>
          <FileCode size={18} />
          <span className="file-info"><strong>{file.path}</strong><span>{sizeLabel(file.size)}
            {file.date > 0 ? ` · ${new Date(file.date * 1000).toLocaleDateString()}` : ''}</span></span>
          {selectedFile === file.path && <Check size={18} aria-label="Selected" />}
        </button><button className="danger-btn remove-file" aria-label={`Remove ${file.path}`}
          disabled={busy || deleting || uploading || unavailable || fileInUse(file)}
          title={fileInUse(file) ? 'The current print file cannot be removed' : `Remove ${file.path}`}
          onClick={() => deleteFile(file.path)}><Trash2 size={17} /></button></div>) : <p className="muted">{search ? 'No matching files.' : 'No uploaded files. Upload G-code to get started.'}</p>}
    </div>
    <p className="muted files-note">Files are saved on OctoPrint. Selecting or uploading a file does not start a print.</p>
  </section>;
}

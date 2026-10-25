import { useEffect, useRef, useState } from 'react';
import { Check, FileCode, Pause, Play, Printer, RefreshCw, Upload, X } from 'lucide-react';
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
  const [remove, setRemove] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const fileInput = useRef(null);
  const uploadInFlight = useRef(false);
  const selected = files.find(file => file.path === selectedFile);
  const paused = Boolean(printer?.paused);
  const active = Boolean(printer?.printing || paused);
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
      onSelect(result.file.path);
      setSearch('');
      setMessage(`Uploaded ${result.file.path}.`);
    } catch (err) { setError(err.message); }
    finally { uploadInFlight.current = false; setUploading(false); }
  }

  async function deleteFile() {
    if (deleting) return;
    setDeleting(true); setError('');
    try {
      await request(`/printer/files?path=${encodeURIComponent(remove)}&confirmed=true`, { method: 'DELETE' });
      setFiles(previous => previous.filter(file => file.path !== remove));
      if (selectedFile === remove) onSelect('');
      setMessage(`Removed ${remove}.`);
      setRemove(null);
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
    {remove && <div className="delete-review" role="group" aria-label="Confirm file removal">
      <p>Permanently remove <strong>{remove}</strong> from OctoPrint?</p>
      <button className="secondary-btn" disabled={deleting} onClick={() => setRemove(null)}>Keep file</button>
      <button className="danger-btn" disabled={deleting || busy || uploading || unavailable || printer?.state?.toLowerCase() !== 'operational'} onClick={deleteFile}>
        {deleting ? 'Removing…' : 'Confirm removal'}</button>
    </div>}
    <p className="upload-status" role="status">{uploading ? 'Saving file to printer storage…' : message}</p>
    <input className="file-search" type="search" aria-label="Search uploaded files" placeholder="Search files…"
      value={search} onChange={event => setSearch(event.target.value)} />
    <div className="uploaded-files" aria-label="Uploaded G-code files" aria-busy={loading}>
      {loading ? <p className="muted">Loading uploaded files…</p> : visibleFiles.length ? visibleFiles.map(file =>
        <div className="file-entry" key={file.path}><button type="button" className={`file-row ${selectedFile === file.path ? 'selected' : ''}`}
          aria-pressed={selectedFile === file.path} disabled={busy || deleting} onClick={() => onSelect(file.path)}>
          <span className="file-info"><strong>{file.path}</strong><span>{sizeLabel(file.size)}
            {file.date > 0 ? ` · ${new Date(file.date * 1000).toLocaleDateString()}` : ''}</span></span>
          {selectedFile === file.path ? <Check size={18} aria-label="Selected" /> : <FileCode size={18} />}
        </button><button className="danger-btn remove-file" aria-label={`Remove ${file.path}`}
          disabled={busy || deleting || uploading || unavailable || printer?.state?.toLowerCase() !== 'operational'}
          onClick={() => { setError(''); setRemove(file.path); }}><X size={16} /></button></div>) : <p className="muted">{search ? 'No matching files.' : 'No uploaded files. Upload G-code to get started.'}</p>}
    </div>
    <p className="muted files-note">Files are saved on OctoPrint. Selecting or uploading a file does not start a print.</p>
  </section>;
}

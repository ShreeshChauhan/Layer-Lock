import { useEffect, useState } from 'react';
import { Camera } from 'lucide-react';
import { API } from './api';

export default function CameraFeed() {
  const [frame, setFrame] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let stopped = false;
    let timer;
    let controller;
    let objectUrl;
    async function refresh() {
      const started = Date.now();
      controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 8000);
      try {
        const response = await fetch(`${API}/camera/snapshot`, {
          signal: controller.signal, cache: 'no-store',
        });
        if (!response.ok) {
          const detail = await response.json().catch(() => ({}));
          throw new Error(detail.detail || 'Camera unavailable');
        }
        const blob = await response.blob();
        if (stopped) return;
        if (objectUrl) URL.revokeObjectURL(objectUrl);
        objectUrl = URL.createObjectURL(blob);
        setFrame({ url: objectUrl, received: response.headers.get('X-Frame-Received-At') || new Date().toISOString() });
        setError('');
      } catch (err) {
        if (stopped) return;
        if (objectUrl) URL.revokeObjectURL(objectUrl);
        objectUrl = null;
        setFrame(null);
        setError(err.name === 'AbortError' ? 'Camera request timed out' : err.message);
      } finally {
        clearTimeout(timeout);
        // One request at a time; slow cameras never accumulate requests.
        if (!stopped) timer = setTimeout(refresh, Math.max(0, 3000 - (Date.now() - started)));
      }
    }
    refresh();
    return () => {
      stopped = true;
      clearTimeout(timer);
      controller?.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, []);

  return <>
    <div className="panel-header">
      <h2><Camera size={18} /> Optical Feed</h2>
      <span className="tag">{error ? 'UNAVAILABLE' : frame ? 'LIVE SNAPSHOTS' : 'CONNECTING'}</span>
    </div>
    {frame && !error ?
      <img className="camera-image" src={frame.url} alt="Latest printer camera snapshot"
        onError={() => setError('Camera image could not be displayed')} /> :
      <div className="camera-placeholder" role="status">
        <Camera size={55} />
        <h3>{error ? 'Camera unavailable' : 'Connecting to camera…'}</h3>
        <p>{error || 'Waiting for the first snapshot'}</p>
      </div>}
    <p className="camera-caption" aria-live="polite">
      {frame && !error ? `Received ${new Date(frame.received).toLocaleTimeString()} · ` : ''}
      Refreshes every 3 seconds · Raw image; detection runs separately
    </p>
  </>;
}

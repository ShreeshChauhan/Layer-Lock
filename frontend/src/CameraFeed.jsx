import { useEffect, useState } from 'react';
import { Camera } from 'lucide-react';
import { API } from './api';

export default function CameraFeed() {
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState(false);
  useEffect(() => {
    if (!error) return;
    const timer = setTimeout(() => { setError(false); setAttempt(value => value + 1); }, 3000);
    return () => clearTimeout(timer);
  }, [error]);
  return <>
    <div className="panel-header"><h2><Camera size={18} /> Live View</h2>
      <span className="tag">{error ? 'RECONNECTING' : 'LIVE STREAM'}</span></div>
    {!error ? <img key={attempt} className="camera-image" src={`${API}/camera/stream?attempt=${attempt}`}
      alt="Live printer camera stream" onError={() => setError(true)} /> :
      <div className="camera-placeholder" role="status"><Camera size={55} />
        <h3>Camera unavailable</h3><p>Reconnecting automatically...</p></div>}
    <p className="camera-caption">Continuous live video · Detection runs separately</p>
  </>;
}

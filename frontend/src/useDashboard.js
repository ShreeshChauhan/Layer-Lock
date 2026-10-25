import { useCallback, useEffect, useRef, useState } from 'react';
import { API } from './api';

export async function request(path, options = {}) {
  const { timeoutMs, ...fetchOptions } = options;
  const rawFile = typeof Blob !== 'undefined' && fetchOptions.body instanceof Blob;
  let response;
  try {
    response = await fetch(`${API}${path}`, {
      ...fetchOptions, signal: AbortSignal.timeout(timeoutMs ?? (options.method === 'POST' ? 30000 : 15000)),
      headers: { 'Content-Type': rawFile ? 'application/octet-stream' : 'application/json', ...options.headers },
    });
  } catch (error) {
    if (error.name === 'TimeoutError') throw new Error('Request timed out. Refresh the file list or printer state before trying again.', { cause: error });
    if (error instanceof TypeError) throw new Error('Cannot reach the app backend. Start both services with .\\start-dev.ps1, then try again.', { cause: error });
    throw error;
  }
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || (response.status >= 500
      ? 'The app backend is unavailable. Restart npm run dev in frontend, or run .\\start-dev.ps1. This page reconnects automatically.'
      : `Request failed (${response.status})`));
  }
  return response.json();
}

export default function useDashboard() {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const inFlight = useRef(null);
  const mounted = useRef(false);
  const refresh = useCallback(() => {
    if (inFlight.current) return inFlight.current;
    inFlight.current = request('/dashboard').then(result => {
      if (mounted.current) { setData(result); setError(''); }
    }).catch(err => {
      if (mounted.current) setError(err.message);
    }).finally(() => { inFlight.current = null; });
    return inFlight.current;
  }, []);
  useEffect(() => {
    mounted.current = true;
    let stopped = false;
    let timer;
    async function poll() {
      await refresh();
      if (!stopped) timer = setTimeout(poll, 3000);
    }
    poll();
    return () => { stopped = true; mounted.current = false; clearTimeout(timer); };
  }, [refresh]);
  return { data, error, refresh };
}

import { useEffect, useState } from 'react';
import { Activity, Flame, Gauge, Droplets, Zap, AlertTriangle } from 'lucide-react';

type Controls = { fuel: number; water: number; valve: number };
type Readings = { temperature_c: number; pressure_bar: number; power_kw: number; efficiency_pct: number; risk: string };
const initial: Controls = { fuel: 50, water: 50, valve: 50 };

export default function App() {
  const [controls, setControls] = useState<Controls>(initial);
  const [readings, setReadings] = useState<Readings | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    fetch('http://localhost:8000/simulate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(controls), signal: controller.signal })
      .then(async r => { if (!r.ok) throw new Error(`API returned ${r.status}`); return r.json(); })
      .then(data => { setReadings(data); setError(''); })
      .catch(e => { if (e.name !== 'AbortError') setError('Cannot reach backend. Start FastAPI on port 8000.'); });
    return () => controller.abort();
  }, [controls]);
  const change = (key: keyof Controls, value: number) => setControls(prev => ({ ...prev, [key]: value }));
  return <div className="app">
    <header><div className="brand"><span className="brand-mark">⚙</span><div><h1>STEAMFORGE</h1><p>INDUSTRIAL COMMAND CENTER</p></div></div><div className="status"><span className="pulse"/> {error ? 'OFFLINE' : 'SIMULATION ACTIVE'}</div></header>
    <main><div className="intro"><p className="eyebrow">FACTORY 01 / BOILER SYSTEM</p><h2>Factory Operations</h2><p>Adjust your machinery. Balance power output against operational risk.</p></div>
      {error && <div className="error">{error}</div>}
      <div className="metrics">
        <Metric icon={<Flame/>} label="Temperature" value={readings ? `${readings.temperature_c} °C` : '—'} />
        <Metric icon={<Gauge/>} label="Steam pressure" value={readings ? `${readings.pressure_bar} bar` : '—'} />
        <Metric icon={<Zap/>} label="Power output" value={readings ? `${readings.power_kw} kW` : '—'} />
        <Metric icon={<Activity/>} label="Efficiency" value={readings ? `${readings.efficiency_pct}%` : '—'} />
      </div>
      <div className="content"><section className="panel"><div className="panel-heading"><h3>Steam Network</h3><span>LIVE MODEL</span></div><div className="network"><div className="machine"><Flame/><b>BOILER</b><small>Heat generation</small></div><div className="pipe"><span>STEAM →</span></div><div className="machine"><Gauge/><b>VALVE</b><small>Pressure control</small></div><div className="pipe"><span>POWER →</span></div><div className="machine"><Zap/><b>TURBINE</b><small>Energy output</small></div></div><div className={`alert ${readings?.risk.toLowerCase() || ''}`}><AlertTriangle size={20}/><div><b>System status: {readings?.risk || 'CONNECTING'}</b><p>{readings?.risk === 'CRITICAL' ? 'Dangerous simulated pressure. Reduce fuel or open the valve.' : readings?.risk === 'WARNING' ? 'Elevated readings. Consider adjusting your controls.' : 'Operating within the game’s normal range.'}</p></div></div></section>
      <section className="panel"><div className="panel-heading"><h3>Control Console</h3><span>MANUAL</span></div>
        <Control icon={<Flame size={18}/>} label="Fuel input" value={controls.fuel} onChange={v=>change('fuel',v)}/>
        <Control icon={<Droplets size={18}/>} label="Water flow" value={controls.water} onChange={v=>change('water',v)}/>
        <Control icon={<Gauge size={18}/>} label="Valve opening" value={controls.valve} onChange={v=>change('valve',v)}/>
        <button onClick={()=>setControls(initial)}>Reset controls</button>
      </section></div><p className="footer">STEAMFORGE v0.1 • Educational simulation only — not for real equipment control.</p>
    </main></div>;
}
function Metric({icon,label,value}:{icon:React.ReactNode,label:string,value:string}) {return <div className="metric"><div className="metric-label">{icon}<span>{label}</span></div><strong>{value}</strong></div>}
function Control({icon,label,value,onChange}:{icon:React.ReactNode,label:string,value:number,onChange:(v:number)=>void}) {return <label className="control"><span>{icon}<b>{label}</b><em>{value}%</em></span><input type="range" min="0" max="100" value={value} onChange={e=>onChange(Number(e.target.value))}/></label>}

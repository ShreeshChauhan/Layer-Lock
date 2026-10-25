import { Activity, Thermometer } from 'lucide-react';
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

const series = [
  ['tool0_actual', 'Tool actual', '#edb35b', false],
  ['tool0_target', 'Tool target', '#edb35b', true],
  ['bed_actual', 'Bed actual', '#8dbec5', false],
  ['bed_target', 'Bed target', '#8dbec5', true],
];
export default function TemperatureChart({ history = [], simulated, unavailable }) {
  return <section className="panel chart-panel">
    <div className="panel-header"><h2><Thermometer size={18} /> Temperature history</h2>
      <span className="tag">{unavailable ? 'TELEMETRY UNAVAILABLE' : simulated ? 'DEMO TELEMETRY' : 'OCTOPRINT TELEMETRY'}</span></div>
    <div className="chart-container">
      {history.length ? <ResponsiveContainer width="100%" height="100%">
        <LineChart data={history} margin={{ right: 15, top: 10, bottom: 15 }}>
          <CartesianGrid stroke="var(--line)" strokeDasharray="3 3" />
          <XAxis dataKey="timestamp" tickFormatter={value => new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            minTickGap={60} stroke="var(--muted)" />
          <YAxis unit="°C" width={60} stroke="var(--muted)" />
          <Tooltip labelFormatter={value => new Date(value).toLocaleTimeString()}
            formatter={(value, name) => [value == null ? 'Unavailable' : `${value.toFixed(1)} °C`, name]}
            contentStyle={{ background: 'var(--iron)', border: '1px solid var(--brass)' }} />
          <Legend />
          {series.map(([key, name, color, target]) => <Line key={key} dataKey={key} name={name} stroke={color}
            strokeDasharray={target ? '6 4' : undefined} strokeWidth={target ? 1.5 : 2}
            dot={false} connectNulls={false} isAnimationActive={false} />)}
        </LineChart>
      </ResponsiveContainer> : <div className="empty-state"><Activity /> Waiting for temperature samples</div>}
    </div>
    <p className="muted">Actual temperatures are solid; targets are dashed. Up to 20 minutes, sampled by the backend.</p>
  </section>;
}

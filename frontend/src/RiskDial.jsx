// Presentation only: the backend remains the authority for risk and warnings.
export default function RiskDial({ value }) {
  const angle = -90 + Math.max(0, Math.min(100, Number(value) || 0)) * 1.8;
  return <svg className="risk-dial" viewBox="0 0 160 94" aria-hidden="true">
    <path className="dial-track" d="M16 80a64 64 0 0 1 128 0" />
    <path className="dial-alert" d="M117.6 28.2A64 64 0 0 1 144 80" />
    {Array.from({ length: 11 }, (_, i) =>
      <path key={i} className="dial-tick" d={`M80 17v${i % 5 === 0 ? 11 : 6}`}
        transform={`rotate(${-90 + i * 18} 80 80)`} />)}
    <text x="12" y="93">0</text><text x="74" y="42">50</text><text x="133" y="93">100</text>
    <g className="dial-needle" style={{ transform: `rotate(${angle}deg)` }}>
      <path d="M77 80 80 27 83 80z" />
    </g>
    <circle className="dial-hub" cx="80" cy="80" r="5" />
  </svg>;
}

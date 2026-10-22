from dataclasses import dataclass

@dataclass
class Controls:
    fuel: float = 50
    water: float = 50
    valve: float = 50

def simulate(c: Controls):
    # Educational game model, not engineering-grade thermodynamics.
    temperature = round(60 + 2.5 * c.fuel - 0.45 * c.water, 1)
    pressure = round(max(0, 0.055 * (temperature - 60) * (1 - 0.006 * c.valve)), 2)
    output = round(max(0, pressure * (0.5 + c.valve / 100) * 12), 1)
    efficiency = round(min(100, max(0, output / max(c.fuel * 1.7, 1) * 100)), 1)
    risk = 'CRITICAL' if pressure > 8 else 'WARNING' if pressure > 6 or temperature > 260 else 'NORMAL'
    return {'temperature_c': temperature, 'pressure_bar': pressure, 'power_kw': output, 'efficiency_pct': efficiency, 'risk': risk}

"""Build paired UM2+ parking hooks from explicitly verified machine coordinates.

No guessed defaults: this cannot be used to bypass a faulty endstop or lost steps.
Only single-tool, absolute-XYZ jobs streamed by OctoPrint are supported.
"""
import math
from jinja2 import Environment, StrictUndefined


def build_parking_scripts(config):
    for check in ('endstops_verified', 'positive_z_lowers_bed', 'absolute_xyz_host_prints'):
        if config.get(check) is not True:
            raise ValueError(f'Parking requires physical verification: {check}')

    def finite(value):
        if type(value) not in (float, int) or not math.isfinite(value):
            raise ValueError('Parking coordinates and limits must be finite numbers')
        return float(value)

    bounds = {}
    park = {}
    for axis in 'xyz':
        low, high = config['limits'][axis]
        low, high = finite(low), finite(high)
        target = finite(config['park'][axis])
        if not low < high or not low < target < high:
            raise ValueError(f'Park {axis.upper()} must be strictly inside verified travel limits')
        bounds[axis] = (low, high)
        park[axis] = target
    clearance = finite(config.get('clearance_mm', 5))
    if not 2 <= clearance <= 20:
        raise ValueError('Clearance must be between 2 and 20 mm')

    # Apply the SAME predicate on pause and resume: insufficient clearance causes
    # a stationary pause/resume, not an unmatched return or an unbounded lift.
    checks = ['p is defined']
    for axis in 'xyz':
        low, high = bounds[axis]
        checks.append(f'p.{axis} is defined and p.{axis} is number and {low} <= p.{axis} <= {high}')
    position_valid = ' and '.join(checks)
    checks += ['p.e is defined and p.e is number and -1000000000 < p.e < 1000000000',
               'p.f is defined and p.f is number and 0 < p.f < 1000000']
    valid = ' and '.join(checks)
    header = '{% set p = pause_position %}\n{% if ' + valid + ' %}\n'
    enough = '{% if p.z + ' + str(clearance) + ' <= ' + str(park['z']) + ' %}\n'
    bed = f"G1 Z{park['z']} F180\n"
    head = f"G1 X{park['x']} Y{park['y']} F1800\n"
    pause = ('; Verified UM2+ parking. No homing, extrusion, or motor release.\n' + header + enough +
             'M400\nG90\n' + bed + head + 'M400\n'
             '{% else %}\nM117 Park skipped: Z clearance\n{% endif %}\n'
             '{% else %}\nM117 Park skipped: no position\n{% endif %}\n')
    resume = ('; Restore XY while bed is down, then restore Z and feedrate.\n' + header + enough +
              'M400\nG90\n' + bed + 'G1 X{{ p.x }} Y{{ p.y }} F1800\n'
              'G1 Z{{ p.z }} F180\nG92 E{{ p.e }}\nG1 F{{ p.f }}\nM400\n'
              '{% endif %}\n{% else %}\n; Never resume from a park with missing return coordinates.\n@cancel\n{% endif %}\n')
    cancel = ('; Heaters/fan off even if position is unknown. No homing.\n'
              'M104 T0 S0\nM140 S0\nM106 S0\n'
              '{% set p = cancel_position %}\n{% if ' + position_valid + ' %}\n' + enough +
              'M400\nG90\n' + bed + head + 'M400\n{% endif %}\n{% endif %}\n')
    scripts = {'afterPrintPaused': pause, 'beforePrintResumed': resume, 'afterPrintCancelled': cancel}
    for script in scripts.values():
        Environment(undefined=StrictUndefined).parse(script)
    return scripts

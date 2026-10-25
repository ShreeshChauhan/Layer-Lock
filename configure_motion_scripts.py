"""Install conservative stationary OctoPrint scripts. No movement commands are sent.

Run with --apply while the printer is idle or offline. Backups contain scripts only, no keys.
This does not enforce firmware limits or remove moves embedded in uploaded G-code.
"""
import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from printer import printer, PRINTER_TYPE

ROOT = Path(__file__).resolve().parent
NAMES = ('afterPrintPaused', 'beforePrintResumed', 'afterPrintCancelled', 'afterPrintDone')


def can_configure(status):
    return (not status['printing'] and not status['paused'] and
            status['state'].lower() in ('operational', 'offline', 'offline after error'))


async def configure(apply=False, verified_um2_homing=False):
    if PRINTER_TYPE != 'octoprint':
        raise RuntimeError('Configure OctoPrint first')
    scripts = {name: (ROOT / 'pi-module' / 'gcode_scripts' / name).read_text() for name in NAMES}
    if verified_um2_homing:
        scripts['afterPrintCancelled'] = (ROOT / 'pi-module/gcode_scripts/ultimaker2plus/afterPrintCancelled').read_text()
    if not apply:
        print(json.dumps(scripts, indent=2))
        return
    status = await printer.get_status()
    if not can_configure(status):
        raise RuntimeError('Printer must be idle or offline; do not change pause/resume scripts mid-job')
    current = (await printer._octo('GET', '/api/settings')).json()['scripts']['gcode']
    backups = ROOT / 'local-backups'
    backups.mkdir(exist_ok=True)
    backup = backups / ('motion-scripts-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.json')
    backup.write_text(json.dumps({name: current.get(name, '') for name in NAMES}, indent=2))
    # Recheck just before writing; never send a job or movement command.
    if not can_configure(await printer.get_status()):
        raise RuntimeError('Printer state changed; no settings written')
    await printer._octo('POST', '/api/settings', json={'scripts': {'gcode': scripts}})
    saved = (await printer._octo('GET', '/api/settings')).json()['scripts']['gcode']
    if any(saved.get(name, '').strip() != script.strip() for name, script in scripts.items()):
        raise RuntimeError(f'Verification failed; inspect settings. Original scripts: {backup}')
    print(f'Installed and verified scripts (UM2+ cancel homing: {verified_um2_homing}). Backup: {backup}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--verified-um2-homing', action='store_true',
                        help='Use ONLY after physical verification of UM2+ bed/head homing and endstops')
    args = parser.parse_args()
    asyncio.run(configure(args.apply, args.verified_um2_homing))

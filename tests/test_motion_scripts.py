"""Ensure conservative hook scripts and sample footers cannot introduce travel."""
import unittest
from pathlib import Path
from tools.configure_motion_scripts import ROOT, NAMES, can_configure


class MotionScriptTests(unittest.TestCase):
    def test_optional_um2_cancel_homes_bed_before_head_without_fixed_coordinates(self):
        script = (ROOT / 'pi-module/gcode_scripts/ultimaker2plus/afterPrintCancelled').read_text()
        commands = [line for line in script.splitlines() if line and not line.startswith(';')]
        self.assertEqual(commands, ['M400', "{% snippet 'disable_hotends' %}",
                                   "{% snippet 'disable_bed' %}", 'M106 S0', 'G28 Z0', 'G28 X0 Y0'])
    def test_only_idle_or_offline_can_reconfigure(self):
        for state in ('Printing', 'Paused', 'Pausing', 'Cancelling', 'Unknown'):
            self.assertFalse(can_configure({'state': state, 'printing': False, 'paused': False}))
        for state in ('Operational', 'Offline', 'Offline after error'):
            self.assertTrue(can_configure({'state': state, 'printing': False, 'paused': False}))
            self.assertFalse(can_configure({'state': state, 'printing': False, 'paused': True}))
    def test_hooks_have_no_axis_extrusion_mode_or_motor_commands(self):
        for name in NAMES:
            lines = (ROOT / 'pi-module' / 'gcode_scripts' / name).read_text().splitlines()
            commands = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith(';')]
            allowed = {"{% snippet 'disable_hotends' %}", "{% snippet 'disable_bed' %}", 'M106 S0'}
            self.assertTrue(set(commands) <= allowed, name)

    def test_sample_footers_only_turn_off_heaters_and_fan(self):
        for path in Path('pi-module/print_tests').glob('*.gcode'):
            footer = path.read_text().split('; # # # # # # START Footer', 1)[1].split('; # # # # # # END Footer', 1)[0]
            commands = [line.strip() for line in footer.splitlines() if line.strip() and not line.lstrip().startswith(';')]
            self.assertEqual(commands, ['M104 S0', 'M140 S0', 'M106 S0'], str(path))

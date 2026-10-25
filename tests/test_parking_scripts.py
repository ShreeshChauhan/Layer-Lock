import copy
import math
import unittest

from jinja2 import Environment, StrictUndefined
from backend.parking_scripts import build_parking_scripts


class ParkingTests(unittest.TestCase):
    def setUp(self):
        # Synthetic verified geometry, not measured coordinates for the user's printer.
        self.config = {'endstops_verified': True, 'positive_z_lowers_bed': True,
                       'absolute_xyz_host_prints': True,
                       'limits': {axis: [0, 200] for axis in 'xyz'},
                       'park': {'x': 2, 'y': 190, 'z': 190}, 'clearance_mm': 5}
        self.position = dict(x=50, y=60, z=20, e=1234, f=2400)

    def render(self, name, position):
        template = Environment(undefined=StrictUndefined).from_string(build_parking_scripts(self.config)[name])
        context = {'pause_position': position, 'cancel_position': position}
        return [line.strip() for line in template.render(**context).splitlines()
                if line.strip() and not line.strip().startswith(';')]

    def test_pause_lowers_bed_before_head_and_resume_reverses_order(self):
        pause = self.render('afterPrintPaused', self.position)
        resume = self.render('beforePrintResumed', self.position)
        self.assertLess(pause.index('G1 Z190.0 F180'), pause.index('G1 X2.0 Y190.0 F1800'))
        self.assertLess(resume.index('G1 Z190.0 F180'), resume.index('G1 X50 Y60 F1800'))
        self.assertLess(resume.index('G1 X50 Y60 F1800'), resume.index('G1 Z20 F180'))
        self.assertIn('G92 E1234', resume)
        self.assertIn('G1 F2400', resume)
        self.assertFalse(any(line.startswith(('G28', 'G91', 'M84', 'M82', 'M83', 'G1 E')) for line in pause + resume))

    def test_tall_print_does_not_receive_an_unmatched_return(self):
        self.position['z'] = 188
        self.assertEqual(self.render('afterPrintPaused', self.position), ['M117 Park skipped: Z clearance'])
        self.assertEqual(self.render('beforePrintResumed', self.position), [])
        self.assertEqual(self.render('afterPrintCancelled', self.position), ['M104 T0 S0', 'M140 S0', 'M106 S0'])

    def test_missing_out_of_bounds_and_nonfinite_positions_never_move(self):
        for bad in ({}, {**self.position, 'x': None}, {**self.position, 'z': -1},
                    {**self.position, 'x': 201}, {**self.position, 'z': math.nan},
                    {**self.position, 'f': math.inf}):
            self.assertEqual(self.render('afterPrintPaused', bad), ['M117 Park skipped: no position'])
            self.assertEqual(self.render('beforePrintResumed', bad), ['@cancel'])

    def test_cancel_turns_off_heat_and_parks_in_clearance_order(self):
        commands = self.render('afterPrintCancelled', self.position)
        self.assertEqual(commands[:3], ['M104 T0 S0', 'M140 S0', 'M106 S0'])
        self.assertLess(commands.index('G1 Z190.0 F180'), commands.index('G1 X2.0 Y190.0 F1800'))
        self.assertNotIn('G28', '\n'.join(commands))

    def test_unverified_or_unsafe_configuration_rejected(self):
        for field in ('endstops_verified', 'positive_z_lowers_bed', 'absolute_xyz_host_prints'):
            config = copy.deepcopy(self.config)
            config[field] = False
            with self.assertRaises(ValueError):
                build_parking_scripts(config)
        for value in (None, 200, -1, math.nan, math.inf):
            config = copy.deepcopy(self.config)
            config['park']['z'] = value
            with self.assertRaises(ValueError):
                build_parking_scripts(config)

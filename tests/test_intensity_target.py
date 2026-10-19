"""Device-boundary validation only; no agreed exercise limits or real writes."""
import importlib.util
from decimal import Decimal
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("target_test", Path(__file__).parents[1] / "custom_components/ftms/intensity_target.py")
target = importlib.util.module_from_spec(spec)
spec.loader.exec_module(target)


class TargetTests(unittest.TestCase):
    # Entirely synthetic ranges, not the administrator's training policy.
    resistance = {"min_value": 1, "max_value": 10, "step": .5}
    policy = {"min_value": 2, "max_value": 4}

    def encode(self, value, machine=None, policy=None):
        return target.encode_bounded_target("target_resistance", value,
                                            self.resistance if machine is None else machine,
                                            self.policy if policy is None else policy)

    def test_resistance_and_power_use_the_vendor_wire_units(self):
        self.assertEqual(self.encode(2.5), b"\x04\x19\x00")
        self.assertEqual(target.encode_bounded_target("target_power", 100,
            {"min_value": 25, "max_value": 1000, "step": 1},
            {"min_value": 50, "max_value": 150}), b"\x05\x64\x00")

    def test_policy_bounds_are_not_replaced_with_device_maximum(self):
        for value in (1.5, 4.5, 10):
            with self.assertRaises(ValueError):
                self.encode(value)
        self.assertEqual(self.encode(2), b"\x04\x14\x00")
        self.assertEqual(self.encode(4), b"\x04\x28\x00")

    def test_no_rounding_to_a_different_machine_step(self):
        for value in (2.1, 2.499999999):
            with self.assertRaisesRegex(ValueError, "step"):
                self.encode(value)

    def test_high_precision_decimal_is_not_rounded_to_an_allowed_target(self):
        with self.assertRaises(ValueError):
            self.encode(Decimal("2.500000000000000000000000000001"))

    def test_missing_invalid_or_overbroad_policy_fails(self):
        for policy in ({}, {"min_value": 4, "max_value": 2},
                       {"min_value": 0, "max_value": 20}):
            with self.assertRaises(ValueError):
                self.encode(2, policy=policy)
        for step in (0, -1, float("nan")):
            with self.assertRaises(ValueError):
                self.encode(2, machine={"min_value": 1, "max_value": 10, "step": step})

    def test_nonfinite_boolean_and_text_targets_are_not_device_commands(self):
        for value in (True, "2", None, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                self.encode(value)

    def test_protocol_overflow_and_fractional_watts_fail_without_rounding(self):
        for value in (32768, 1.5):
            with self.assertRaises(ValueError):
                target.encode_bounded_target("target_power", value,
                    {"min_value": 0, "max_value": 50000, "step": .5},
                    {"min_value": 0, "max_value": 50000})
        with self.assertRaises(ValueError):
            target.encode_bounded_target("reset", 1, self.resistance, self.policy)

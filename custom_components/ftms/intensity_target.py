"""Pure target validation/encoding; no Bluetooth writes or enabled HA actions."""
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import struct


def _number(value):
    if type(value) not in (int, float, Decimal):
        raise ValueError("Expected an explicit finite numeric target/range")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Invalid numeric target/range") from exc
    if not result.is_finite():
        raise ValueError("Expected a finite target/range")
    return Fraction(result)


def encode_bounded_target(setting, target, machine_range, policy_range):
    """Require supplied machine and policy bounds; never clamp or round a target.

    Units/opcodes match the pinned vendor ControlPoint model: resistance is a
    signed 16-bit value in tenths; target power is signed 16-bit whole watts.
    This helper cannot establish policy approval, HR freshness or write safety.
    """
    if setting not in ("target_resistance", "target_power"):
        raise ValueError("Unsupported intensity setting")
    try:
        low, high, step = (_number(machine_range[k]) for k in ("min_value", "max_value", "step"))
        policy_low, policy_high = (_number(policy_range[k]) for k in ("min_value", "max_value"))
    except (KeyError, TypeError) as exc:
        raise ValueError("Explicit machine and policy ranges are required") from exc
    target = _number(target)
    if not (low <= policy_low <= policy_high <= high) or step <= 0:
        raise ValueError("Invalid or incompatible machine/policy ranges")
    if not policy_low <= target <= policy_high:
        raise ValueError("Target exceeds the supplied policy bounds")
    steps = (target - low) / step
    if steps.denominator != 1:
        raise ValueError("Target is off the advertised machine step")
    raw = target * (10 if setting == "target_resistance" else 1)
    if raw.denominator != 1 or not -32768 <= raw <= 32767:
        raise ValueError("Target is not exactly representable by FTMS")
    opcode = 0x04 if setting == "target_resistance" else 0x05
    return bytes((opcode,)) + struct.pack("<h", int(raw))

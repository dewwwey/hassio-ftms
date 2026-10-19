"""Serialized acknowledged FTMS procedures for Finish and target settings.

Target procedures are preparation only: callers must use the bounded encoder and
an explicitly armed, approved-policy/freshness gate. No target HA action exists.
"""
import asyncio
import logging
import math

CONTROL_POINT = "00002ad9-0000-1000-8000-00805f9b34fb"
_LOGGER = logging.getLogger(__name__)

class FinishRejected(Exception):
    """The machine rejected a procedure, or the local gate refused it."""

class ControlPointOwner:
    """One instance per coordinator, shared by Finish and any future target caller."""
    def __init__(self):
        self.lock = asyncio.Lock()

    async def finish(self, client, *, timeout=5, authorize=None):
        await self._execute(client, bytes((0x08, 0x01)), authorize=authorize, timeout=timeout)

    async def target(self, client, payload, *, authorize, timeout=5):
        """Prepared primitive; authorization must revalidate arming/policy/freshness.

        Payload must come from encode_bounded_target. This owner handles protocol
        serialization, not training limits, approval, ramp rates or HR validation.
        The synchronous gate is evaluated after the lock and before BOTH writes.
        """
        if type(payload) is not bytes or len(payload) != 3 or payload[0] not in (0x04, 0x05):
            raise ValueError("Expected one encoded resistance or power target")
        if not callable(authorize):
            raise ValueError("A live authorization gate is required")
        await self._execute(client, payload, authorize=authorize, timeout=timeout)

    async def _execute(self, client, payload, *, authorize=None, timeout=5):
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 10:
            raise ValueError("Timeout must be positive and at most ten seconds")
        async with self.lock:
            def check():
                if not client.is_connected:
                    raise FinishRejected("Bike is disconnected")
                if authorize is not None and authorize() is not True:
                    raise FinishRejected("Control authorization is no longer valid")
            check()
            characteristic = client.services.get_characteristic(CONTROL_POINT)
            if characteristic is None or "write" not in characteristic.properties:
                raise FinishRejected("Bike has no writable FTMS control point")
            pending = None
            expected = None

            def indication(characteristic, data):
                if (pending is not None and not pending.done() and len(data) >= 3
                        and data[0] == 0x80 and data[1] == expected):
                    pending.set_result(data[2])

            async def command(command_payload):
                nonlocal pending, expected
                check()
                expected = command_payload[0]
                pending = asyncio.get_running_loop().create_future()
                try:
                    try:
                        async with asyncio.timeout(timeout):
                            await client.write_gatt_char(characteristic, command_payload, response=True)
                            result = await pending
                    except TimeoutError as exc:
                        raise TimeoutError(f"FTMS opcode {expected:02x} acknowledgement timed out") from exc
                    if result != 0x01:
                        names = {2:"not supported", 3:"invalid parameter", 4:"operation failed", 5:"control not permitted"}
                        raise FinishRejected(f"FTMS opcode {expected:02x}: {names.get(result, 'unknown rejection')}")
                finally:
                    if pending is not None and not pending.done():
                        pending.cancel()

            subscribed = False
            try:
                # BlueZ may enable indications before start_notify finishes.
                # Attempt bounded cleanup even if that await times out/cancels.
                subscribed = True
                async with asyncio.timeout(timeout):
                    await client.start_notify(characteristic, indication)
                await command(bytes((0x00,)))
                await command(payload)
            finally:
                if subscribed and client.is_connected:
                    try:
                        async with asyncio.timeout(2):
                            await client.stop_notify(characteristic)
                    except Exception as exc:
                        _LOGGER.debug("Control indication cleanup failed: %s", type(exc).__name__)

async def finish_workout(client, *, timeout=5, owner=None, authorize=None):
    """Wait for matched successful indications; never disconnect to finish."""
    owner = owner if owner is not None else ControlPointOwner()
    await owner.finish(client, timeout=timeout, authorize=authorize)

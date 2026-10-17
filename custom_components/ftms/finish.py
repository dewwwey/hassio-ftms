"""The only allowed application write: request control, then stop the workout."""
import asyncio
import logging

CONTROL_POINT = "00002ad9-0000-1000-8000-00805f9b34fb"
_LOGGER = logging.getLogger(__name__)


class FinishRejected(Exception):
    """The machine explicitly rejected a finish procedure."""


async def finish_workout(client, *, timeout=5):
    """Wait for matched successful indications; never disconnect to finish."""
    if not client.is_connected:
        raise FinishRejected("Bike is disconnected")
    characteristic = client.services.get_characteristic(CONTROL_POINT)
    if characteristic is None or "write" not in characteristic.properties:
        raise FinishRejected("Bike has no writable FTMS control point")
    pending = None
    expected = None

    def indication(characteristic, data):
        _LOGGER.debug("Finish control-point indication: %s", bytes(data).hex())
        if (pending is not None and not pending.done() and len(data) >= 3
                and data[0] == 0x80 and data[1] == expected):
            pending.set_result(data[2])

    async def command(payload):
        nonlocal pending, expected
        expected = payload[0]
        pending = asyncio.get_running_loop().create_future()
        try:
            try:
                async with asyncio.timeout(timeout):
                    _LOGGER.debug("Finish writing opcode %02x", expected)
                    await client.write_gatt_char(characteristic, payload, response=True)
                    result = await pending
            except TimeoutError as exc:
                raise TimeoutError(f"FTMS opcode {expected:02x} acknowledgement timed out") from exc
            if result != 0x01:
                names = {2: "not supported", 3: "invalid parameter", 4: "operation failed", 5: "control not permitted"}
                raise FinishRejected(f"FTMS opcode {expected:02x}: {names.get(result, 'unknown rejection')}")
        finally:
            if pending is not None and not pending.done():
                pending.cancel()

    subscribed = False
    try:
        async with asyncio.timeout(timeout):
            await client.start_notify(characteristic, indication)
        subscribed = True
        await command(bytes((0x00,)))
        await command(bytes((0x08, 0x01)))
    finally:
        if subscribed and client.is_connected:
            try:
                async with asyncio.timeout(2):
                    await client.stop_notify(characteristic)
            except Exception as exc:
                # Command outcome must not be hidden by an indication cleanup error.
                _LOGGER.debug("Finish indication cleanup failed: %s", type(exc).__name__)

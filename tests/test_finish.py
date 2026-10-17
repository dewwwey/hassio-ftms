"""Finish is an acknowledged, bounded Stop procedure, not disconnection."""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).parents[1] / "custom_components" / "ftms"
spec = importlib.util.spec_from_file_location("finish_test", ROOT / "finish.py")
finish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(finish)


class Client:
    is_connected = True

    def __init__(self, results=(1, 1), wrong_first=False):
        self.characteristic = SimpleNamespace(properties=["write", "indicate"])
        self.services = SimpleNamespace(get_characteristic=lambda uuid: self.characteristic)
        self.results = iter(results)
        self.writes = []
        self.unsubscribed = False
        self.disconnected = False
        self.wrong_first = wrong_first

    async def start_notify(self, characteristic, callback):
        self.callback = callback

    async def stop_notify(self, characteristic):
        self.unsubscribed = True

    async def write_gatt_char(self, characteristic, payload, response):
        assert response is True
        self.writes.append(payload)
        result = next(self.results)
        if self.wrong_first:
            self.callback(characteristic, bytes((0x80, 0x05, 1)))
        if result is not None:
            self.callback(characteristic, bytes((0x80, payload[0], result)))


class FinishTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_request_control_and_stop_are_written(self):
        client = Client()
        await finish.finish_workout(client)
        self.assertEqual(client.writes, [b"\x00", b"\x08\x01"])
        self.assertTrue(client.is_connected)
        self.assertTrue(client.unsubscribed)

    async def test_rejected_request_control_never_sends_stop(self):
        client = Client(results=(5,))
        with self.assertRaises(finish.FinishRejected):
            await finish.finish_workout(client)
        self.assertEqual(client.writes, [b"\x00"])
        self.assertTrue(client.unsubscribed)

    async def test_rejected_stop_does_not_report_success(self):
        client = Client(results=(1, 4))
        with self.assertRaises(finish.FinishRejected):
            await finish.finish_workout(client)
        self.assertTrue(client.unsubscribed)

    async def test_timeout_is_bounded_and_cleans_subscription(self):
        client = Client(results=(None,))
        with self.assertRaisesRegex(TimeoutError, "opcode 00 acknowledgement timed out"):
            await finish.finish_workout(client, timeout=.01)
        self.assertEqual(client.writes, [b"\x00"])
        self.assertTrue(client.unsubscribed)

    async def test_stop_timeout_identifies_the_failed_stage(self):
        client = Client(results=(1, None))
        with self.assertRaisesRegex(TimeoutError, "opcode 08 acknowledgement timed out"):
            await finish.finish_workout(client, timeout=.01)
        self.assertEqual(client.writes, [b"\x00", b"\x08\x01"])
        self.assertTrue(client.unsubscribed)

    async def test_unrelated_response_does_not_match_current_command(self):
        client = Client(wrong_first=True)
        await finish.finish_workout(client)
        self.assertEqual(client.writes, [b"\x00", b"\x08\x01"])

    async def test_offline_does_not_connect_or_write(self):
        client = Client()
        client.is_connected = False
        with self.assertRaises(finish.FinishRejected):
            await finish.finish_workout(client)
        self.assertEqual(client.writes, [])

    async def test_no_control_point_fails_without_writes(self):
        client = Client()
        client.services.get_characteristic = lambda uuid: None
        with self.assertRaises(finish.FinishRejected):
            await finish.finish_workout(client)
        self.assertEqual(client.writes, [])

"""Shared transaction ownership and live authorization; no real Bluetooth calls."""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

spec=importlib.util.spec_from_file_location('control_owner_test',Path(__file__).parents[1]/'custom_components/ftms/finish.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class Client:
    is_connected=True
    def __init__(self):
        self.characteristic=SimpleNamespace(properties=['write','indicate'])
        self.services=SimpleNamespace(get_characteristic=lambda _:self.characteristic)
        self.writes=[]
        self.subscriptions=0
        self.max_subscriptions=0
        self.after_control=None
        self.results={}
    async def start_notify(self,char,callback):
        self.subscriptions+=1
        self.max_subscriptions=max(self.max_subscriptions,self.subscriptions)
        self.callback=callback
        await asyncio.sleep(0)
    async def stop_notify(self,char):
        self.subscriptions-=1
    async def write_gatt_char(self,char,payload,response):
        self.writes.append(payload)
        await asyncio.sleep(0)
        result=self.results.get(payload[0],1)
        if payload[0]==0 and self.after_control:
            self.after_control()
        if result is not None:
            self.callback(char,bytes((0x80,payload[0],result)))

class ControlOwnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_finish_and_target_share_one_subscription_and_transaction(self):
        owner=module.ControlPointOwner(); client=Client()
        await asyncio.gather(owner.target(client,b'\x04\x0a\x00',authorize=lambda:True),owner.finish(client))
        self.assertEqual(client.writes,[b'\x00',b'\x04\x0a\x00',b'\x00',b'\x08\x01'])
        self.assertEqual(client.max_subscriptions,1)
        self.assertEqual(client.subscriptions,0)
    async def test_revoked_gate_blocks_target_after_request_control(self):
        armed=True
        def revoke():
            nonlocal armed
            armed=False
        client=Client();client.after_control=revoke
        with self.assertRaises(module.FinishRejected):
            await module.ControlPointOwner().target(client,b'\x05\x64\x00',authorize=lambda:armed)
        self.assertEqual(client.writes,[b'\x00'])
        self.assertEqual(client.subscriptions,0)
    async def test_queued_target_rechecks_gate_after_lock_is_released(self):
        owner=module.ControlPointOwner();client=Client();armed=True
        await owner.lock.acquire()
        task=asyncio.create_task(owner.target(client,b'\x04\x0a\x00',authorize=lambda:armed))
        await asyncio.sleep(0)
        armed=False;owner.lock.release()
        with self.assertRaises(module.FinishRejected):
            await task
        self.assertEqual(client.writes,[])
    async def test_rejection_or_timeout_never_becomes_success_and_owner_is_reusable(self):
        owner=module.ControlPointOwner();client=Client()
        for result,expected in ((5,module.FinishRejected),(None,TimeoutError)):
            client.results={4:result}
            with self.assertRaises(expected):
                await owner.target(client,b'\x04\x0a\x00',authorize=lambda:True,timeout=.01)
            self.assertEqual(client.subscriptions,0)
        client.results={}
        await owner.finish(client)
    async def test_invalid_payload_gate_and_timeout_do_not_write(self):
        owner=module.ControlPointOwner();client=Client()
        for payload in (b'\x08\x01',b'\x04',b'\x07',bytearray(b'\x04\x0a\x00')):
            with self.assertRaises(ValueError):
                await owner.target(client,payload,authorize=lambda:True)
        for value in (0,11,True,float('inf'),float('nan')):
            with self.assertRaises(ValueError):
                await owner.finish(client,timeout=value)
        with self.assertRaises(module.FinishRejected):
            await owner.target(client,b'\x04\x0a\x00',authorize=lambda:False)
        self.assertEqual(client.writes,[])

    async def test_disconnect_after_control_blocks_target(self):
        client=Client()
        def disconnect():
            client.is_connected=False
        client.after_control=disconnect
        with self.assertRaises(module.FinishRejected):
            await module.ControlPointOwner().target(client,b'\x04\x0a\x00',authorize=lambda:True)
        self.assertEqual(client.writes,[b'\x00'])
    async def test_cancelled_procedure_cleans_subscription_and_releases_owner(self):
        owner=module.ControlPointOwner();client=Client();client.results={4:None}
        task=asyncio.create_task(owner.target(client,b'\x04\x0a\x00',authorize=lambda:True))
        async with asyncio.timeout(1):
            while len(client.writes)<2:
                await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(client.subscriptions,0)
        self.assertFalse(owner.lock.locked())
        await owner.finish(client)
    async def test_finish_rechecks_its_session_guard_before_stop(self):
        client=Client();current=True
        def change_session():
            nonlocal current
            current=False
        client.after_control=change_session
        with self.assertRaises(module.FinishRejected):
            await module.ControlPointOwner().finish(client,authorize=lambda:current)
        self.assertEqual(client.writes,[b'\x00'])

    async def test_cancel_or_timeout_during_subscription_attempts_cleanup(self):
        class SlowStart(Client):
            def __init__(self):
                super().__init__()
                self.started=asyncio.Event()
                self.release=asyncio.Event()
            async def start_notify(self,char,callback):
                await super().start_notify(char,callback)
                self.started.set()
                await self.release.wait()
        for cancel in (False,True):
            owner=module.ControlPointOwner();client=SlowStart()
            task=asyncio.create_task(owner.finish(client,timeout=.01 if not cancel else 1))
            await client.started.wait()
            if cancel:
                task.cancel()
            with self.assertRaises(asyncio.CancelledError if cancel else TimeoutError):
                await task
            self.assertEqual(client.subscriptions,0)
            self.assertFalse(owner.lock.locked())
            self.assertEqual(client.writes,[])
            client.release.set()
            await owner.finish(client)

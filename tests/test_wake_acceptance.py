import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('acceptance_sender', Path(__file__).parents[1]/'examples/shell/ftms_wake_acceptance.py')
sender = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sender)

class AcceptanceSenderTests(unittest.TestCase):
    event = {'kind':'activity_started','ts':100,'event_id':'a'*24,'session_id':'b'*24}
    sample = {'kind':'sample','ts':100,'metrics':{'cadence_instant':60}}
    def records(self,*records):
        return ''.join(json.dumps(r)+'\n' for r in records)
    def test_accepts_only_a_recent_matching_saved_event(self):
        self.assertEqual(sender.select_event(self.records(self.sample,self.event),'a'*24,101),self.event)
        for now in (99,701,float('nan')):
            with self.assertRaises(ValueError):
                sender.select_event(self.records(self.sample,self.event),'a'*24,now)
    def test_rejects_missing_or_later_activity_sample_and_stale_identity(self):
        for records in ((self.event,), (self.event,self.sample), (dict(self.sample,metrics={'cadence_instant':0}),self.event)):
            with self.assertRaises(ValueError):
                sender.select_event(self.records(*records),'a'*24,101)
        newer = dict(self.event,event_id='c'*24)
        with self.assertRaises(ValueError):
            sender.select_event(self.records(self.sample,self.event,newer),'a'*24,101)
        with self.assertRaises(ValueError):
            sender.select_event(self.records(self.sample,self.event),'bad-id',101)

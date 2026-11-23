"""Assigned-group completion stays distinct from the source's three-case run."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
from make_demo import write_snapshot
from wrf_data import scan_roots
import wrf_classroom as plot


class StudentScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.members = {}
        for hour in (0,3):
            relative = "01_CTRL/wrflite_d01_2023-06-22_%02d-00-00.nc" % hour
            path = self.root/relative
            write_snapshot(path, "full", 0, hour, 4)
            self.members[relative] = {"case":"01_CTRL", "time":"2023-06-22_%02d:00:00" % hour,
                                      "bytes":path.stat().st_size}
        source_members = deepcopy(self.members)
        for case in ("02_CTRL_NOISE", "03_CLEAN"):
            for relative, info in self.members.items():
                source_members[relative.replace("01_CTRL",case)] = dict(info,case=case)
        self.original = {"version":"1.0.0", "config_hash":"parent-config", "complete":True,
                         "planned_files":6, "files":source_members}
        original_bytes = (json.dumps(self.original,indent=2)+"\n").encode()
        provenance = self.root/"provenance"
        provenance.mkdir()
        (provenance/"source_manifest.json").write_bytes(original_bytes)
        self.selected = {"version":"1.0.0", "config_hash":"parent-config", "complete":True,
                         "planned_files":2, "files":self.members,
                         "classroom_scope":{
                             "kind":"selected_cases", "selected_cases":["01_CTRL"],
                             "parent_manifest_sha256":hashlib.sha256(original_bytes).hexdigest(),
                             "parent_manifest_file":"provenance/source_manifest.json",
                             "parent_complete":True, "parent_planned_files":6,
                             "parent_config_hash":"parent-config"}}
        self.write_selected()

    def tearDown(self):
        self.temp.cleanup()

    def write_selected(self):
        (self.root/"manifest.json").write_text(json.dumps(self.selected),encoding="utf-8")

    def test_one_group_complete_without_deferring_other_groups(self):
        records,warnings,status=scan_roots([self.root])
        self.assertEqual(len(records),2)
        self.assertEqual({record.case for record in records},{"01_CTRL"})
        self.assertEqual(status["deferred_files"],0)
        self.assertTrue(status["complete"])
        self.assertEqual(status["completion_scope"],"selected_cases")
        self.assertEqual(status["scope_cases"],["01_CTRL"])
        self.assertEqual(len(status["manifests"]),1)
        self.assertEqual(warnings,[])
        scope=status["manifests"][0]["classroom_scope"]
        self.assertEqual(scope["parent_planned_files"],6)
        original_path=self.root/scope["parent_manifest_file"]
        self.assertEqual(hashlib.sha256(original_path.read_bytes()).hexdigest(),scope["parent_manifest_sha256"])
        self.assertEqual(json.loads(original_path.read_text()),self.original)

    def test_shared_original_manifest_remains_incomplete_without_other_groups(self):
        (self.root/"manifest.json").write_text(json.dumps(self.original),encoding="utf-8")
        records,warnings,status=scan_roots([self.root])
        self.assertEqual(len(records),2)
        self.assertEqual(status["deferred_files"],4)
        self.assertFalse(status["complete"])
        self.assertEqual(status["completion_scope"],"manifest_dataset")
        self.assertEqual(status["scope_cases"],[])

    def test_missing_assigned_file_and_incomplete_parent_are_not_complete(self):
        missing=self.root/next(iter(self.members))
        missing.unlink()
        records,warnings,status=scan_roots([self.root])
        self.assertEqual(len(records),1)
        self.assertEqual(status["deferred_files"],1)
        self.assertFalse(status["complete"])
        self.selected["files"] = {k:v for k,v in self.members.items() if (self.root/k).exists()}
        self.selected["planned_files"] = 1
        self.selected["classroom_scope"]["parent_complete"] = False
        self.write_selected()
        records,warnings,status=scan_roots([self.root])
        self.assertEqual(len(records),1)
        self.assertEqual(status["deferred_files"],0)
        self.assertFalse(status["complete"])
        self.assertTrue(any("parent conversion completion" in warning for warning in warnings))

    def test_selected_gallery_names_its_scope(self):
        output=self.root/"output"
        status={"source_complete":True,"completion_scope":"selected_cases","scope_cases":["01_CTRL"],
                "processed_records":2,"errors":[],"warnings":[],"preview":False}
        plot.write_gallery(output,status,[],plot.load_config(None))
        page=(output/"index.html").read_text(encoding="utf-8")
        self.assertIn("Selected group data complete",page)
        self.assertIn("Groups: 01_CTRL",page)
        self.assertNotIn("Conversion complete;",page)


if __name__=="__main__":
    unittest.main()

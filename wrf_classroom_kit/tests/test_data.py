"""Numerical reader tests using tiny synthetic files, never production data."""
from pathlib import Path
from datetime import datetime
import json
import sys
import tempfile
import unittest

import numpy as np
from netCDF4 import Dataset

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT if (ROOT / "wrf_data.py").is_file() else ROOT / "wrf_classroom_kit"
sys.path.insert(0, str(KIT))
from wrf_data import (PRIMARY_FIELDS, VERTICAL_FIELDS, scan_roots, read_surface,
                      read_city_columns, rain_increment)


def fixture(path, mode="full", stamp="2023-06-22_00:00:00", omit=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    nz = 3 if mode == "full" else 1
    with Dataset(path, "w") as ds:
        for name, n in [("Time", 1), ("DateStrLen", 19), ("bottom_top", nz),
                        ("bottom_top_stag", nz + 1), ("south_north", 4), ("west_east", 4)]:
            ds.createDimension(name, n)
        ds.wrflite_vertical = mode
        ds.TITLE = "SYNTHETIC classroom test, not a forecast"
        ds.wrflite_interval_hours = 3
        ds.createVariable("Times", "S1", ("Time", "DateStrLen"))[:] = np.array([list(stamp)], dtype="S1")
        y, x = np.mgrid[:4, :4]
        for name, values, units in [("XLAT", 20+y, "degree_north"), ("XLONG", 75+x, "degree_east"),
                                    ("HGT", np.full((4,4), 100), "m"),
                                    ("COSALPHA", np.ones((4,4)), "1"), ("SINALPHA", np.zeros((4,4)), "1")]:
            v = ds.createVariable(name, "f4", ("Time", "south_north", "west_east"))
            v.units = units
            v[0] = values
        for number, name in enumerate(PRIMARY_FIELDS):
            if name in omit:
                continue
            dims = ("Time", "bottom_top", "south_north", "west_east") if name in VERTICAL_FIELDS else ("Time", "south_north", "west_east")
            v = ds.createVariable(name, "i2" if name == "Q2" else "f4", dims, fill_value=-9999)
            v.units = {"Q2":"kg kg-1", "T2":"K", "so2":"ppmv", "RAINC":"mm", "RAINNC":"mm"}.get(name,"ug m^-3")
            if name == "Q2":
                v.scale_factor = 0.001
                v.add_offset = 0.01
                v.set_auto_maskandscale(False)
                values = np.full((1,4,4), 2, dtype=np.int16)
                values[0,0,0] = -9999
                v[:] = values
            elif name in VERTICAL_FIELDS:
                v[:] = np.broadcast_to(np.arange(nz)[None,:,None,None] + number, (1,nz,4,4))
            else:
                v[:] = number + np.zeros((1,4,4))
        for name in ("P", "PB", "PH", "PHB"):
            stagger = name.startswith("PH")
            zdim = "bottom_top_stag" if stagger else "bottom_top"
            v = ds.createVariable(name, "f4", ("Time", zdim, "south_north", "west_east"))
            v.units = "m2 s-2" if stagger else "Pa"
            z = np.arange(nz+1 if stagger else nz)
            vals = (100 + z*200)*9.81 if name == "PHB" else (100000 - z*10000 if name == "PB" else np.zeros_like(z))
            v[:] = np.broadcast_to(vals[None,:,None,None], (1,len(z),4,4))


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_decodes_packed_and_missing_values(self):
        p = self.root/"01_CTRL"/"snapshot.nc"
        fixture(p)
        records, warnings, status = scan_roots([self.root])
        self.assertEqual(len(records), 1)
        self.assertIsNone(status["complete"])
        self.assertTrue(records[0].synthetic)
        result = read_surface(records[0])
        self.assertAlmostEqual(result["fields"]["Q2"][1,1], 0.012)
        self.assertTrue(np.ma.is_masked(result["fields"]["Q2"][0,0]))
        self.assertEqual(result["fields"]["PM2_5_DRY"].shape, (4,4))
        self.assertEqual(result["fields"]["PM2_5_DRY"][1,1], 14)
        self.assertEqual(records[0].time, datetime(2023,6,22))

    def test_manifest_ignores_unlisted_and_partial_files(self):
        p = self.root/"01_CTRL"/"ready.nc"
        fixture(p)
        q = self.root/"02_CTRL_NOISE"/"not_yet_listed.nc"
        fixture(q)
        manifest = {"complete": False, "planned_files": 2, "files": {
            "01_CTRL/ready.nc": {"case":"01_CTRL", "time":"2023-06-22_00:00:00", "bytes":p.stat().st_size}}}
        (self.root/"manifest.json").write_text(json.dumps(manifest))
        result, warnings, status = scan_roots([self.root])
        self.assertEqual([r.path for r in result], [p])
        self.assertFalse(status["complete"])
        manifest["files"]["02_CTRL_NOISE/not_yet_listed.nc"] = {"case":"02_CTRL_NOISE", "time":"2023-06-22_00:00:00", "bytes":q.stat().st_size + 5}
        manifest["complete"] = True
        (self.root/"manifest.json").write_text(json.dumps(manifest))
        result, warnings, status = scan_roots([self.root])
        self.assertEqual(len(result),1)
        self.assertEqual(status["deferred_files"],1)
        self.assertFalse(status["complete"])
        manifest["files"]["02_CTRL_NOISE/not_yet_listed.nc"]["bytes"] = q.stat().st_size
        (self.root/"manifest.json").write_text(json.dumps(manifest))
        result, warnings, status = scan_roots([self.root])
        self.assertEqual(len(result),2)
        self.assertTrue(status["complete"])

    def test_full_surface_and_duplicate(self):
        fixture(self.root/"full"/"01_CTRL"/"a.nc", "full")
        fixture(self.root/"surface"/"01_CTRL"/"a.nc", "surface")
        records, _, _ = scan_roots([self.root])
        self.assertEqual({r.mode for r in records}, {"surface","full"})
        fixture(self.root/"full"/"01_CTRL"/"duplicate.nc", "full")
        records, warnings, status = scan_roots([self.root])
        self.assertEqual(len(records),1)
        self.assertEqual(records[0].mode,"surface")
        self.assertEqual(status["duplicate_records"],2)

    def test_city_columns_true_height_and_outside(self):
        fixture(self.root/"01_CTRL"/"a.nc")
        r = scan_roots([self.root])[0][0]
        cities = [{"slug":"inside","name":"Inside","lat":21.1,"lon":76.1},
                  {"slug":"outside","name":"Outside","lat":29,"lon":76}]
        out = read_city_columns(r,cities)
        self.assertEqual(out["inside"]["row"],1)
        self.assertEqual(out["inside"]["col"],1)
        np.testing.assert_allclose(out["inside"]["height_agl"], [100,300,500], atol=1e-3)
        np.testing.assert_allclose(out["inside"]["pressure_hpa"], [1000,900,800])
        np.testing.assert_array_equal(out["inside"]["profiles"]["PM2_5_DRY"], [14,15,16])
        self.assertEqual(out["outside"]["status"], "outside_domain")
        self.assertEqual(out["outside"]["values"], {})

    def test_surface_keeps_one_layer_without_fake_profile(self):
        fixture(self.root/"01_CTRL"/"a.nc", "surface")
        r = scan_roots([self.root])[0][0]
        out = read_city_columns(r,[{"slug":"inside","lat":21,"lon":76}])["inside"]
        self.assertEqual(out["vertical_levels"],1)
        self.assertEqual(len(out["profiles"]["so2"]),1)
        self.assertNotIn("T2",out["profiles"])

    def test_rain_rates_bucket_and_reset(self):
        rate,q = rain_increment([0,2,5],[6,5,4],3)
        np.testing.assert_allclose(rate[:2],[2,1])
        self.assertTrue(rate.mask[2])
        self.assertEqual(q["negative_resets"],1)
        rate,q = rain_increment([90,20],[5,23],3,100,[0,1],[1,1])
        np.testing.assert_allclose(rate,[5,1])
        rate,q = rain_increment([90,20],[5,23],3,None,[0,1],[1,1])
        self.assertTrue(rate.mask[0])
        self.assertEqual(rate[1],1)
        self.assertEqual(q["unknown_bucket"],1)
        rate,q = rain_increment([0],[5],0)
        self.assertEqual(rate.count(),0)
        rate,q = rain_increment([0],[5],3,100)
        self.assertEqual(q["status"],"missing_counter")

    def test_manifest_traversal_rejected(self):
        fixture(self.root/"outside.nc")
        nested=self.root/"nested"
        nested.mkdir()
        (nested/"manifest.json").write_text(json.dumps({"complete":True,"planned_files":1,"files":{
            "../outside.nc":{"bytes":(self.root/"outside.nc").stat().st_size,"case":"01_CTRL"}}}))
        records,warnings,status=scan_roots([nested])
        self.assertEqual(records,[])
        self.assertEqual(status["deferred_files"],1)

    def test_generated_demo_preserves_both_modes_and_all_fields(self):
        from make_demo import create_demo
        output=self.root/"demo"
        summary=create_demo(output,steps=4,grid_size=6)
        self.assertEqual(summary["files"],24)
        records,warnings,status=scan_roots([output])
        self.assertEqual(len(records),24)
        self.assertTrue(status["complete"])
        self.assertFalse(warnings)
        self.assertTrue(all(r.synthetic for r in records))
        full=next(r for r in records if r.mode=="full" and r.case=="01_CTRL" and r.time.hour==0)
        surface=next(r for r in records if r.mode=="surface" and r.case=="01_CTRL" and r.time.hour==0)
        f,s=read_surface(full),read_surface(surface)
        self.assertEqual(set(f["fields"]),set(PRIMARY_FIELDS))
        for field in PRIMARY_FIELDS:
            np.testing.assert_allclose(f["fields"][field],s["fields"][field])
        city=read_city_columns(full,[{"slug":"delhi","lat":28.61,"lon":77.21}])["delhi"]
        self.assertEqual(len(city["height_agl"]),39)
        self.assertAlmostEqual(float(city["height_agl"][0]),25,places=2)
        self.assertTrue((np.diff(city["height_agl"])>0).all())
        with self.assertRaises(ValueError):
            create_demo(output,steps=4,grid_size=6)


if __name__ == "__main__":
    unittest.main()

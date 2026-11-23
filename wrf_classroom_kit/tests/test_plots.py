"""Independent scientific and incremental-workflow checks for the plot kit.

Uses synthetic NetCDF records. Map rendering is replaced by a tiny PNG only for
cache tests; the CLI smoke test exercises real maps, GIFs, tables and a gallery.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from datetime import datetime
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import numpy as np
from netCDF4 import Dataset
from PIL import Image

WORKSPACE = Path(__file__).resolve().parents[1]
KIT = WORKSPACE if (WORKSPACE / "wrf_data.py").is_file() else WORKSPACE / "wrf_classroom_kit"
sys.path.insert(0, str(KIT))

import wrf_classroom as plot
from wrf_data import scan_roots
from make_demo import write_snapshot


class PlotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = plot.load_config(None)
        self.cities = [
            {"name":"Delhi", "slug":"delhi", "rank":1, "population_2011":1,
             "lat":28.61, "lon":77.21},
            {"name":"Outside", "slug":"outside", "rank":2, "population_2011":1,
             "lat":50.0, "lon":120.0},
        ]

    def tearDown(self):
        self.tmp.cleanup()

    def snapshot(self, hour, mode="full"):
        path = self.root/"data"/"01_CTRL"/("snapshot_%02d.nc" % hour)
        write_snapshot(path, mode, 0, hour, 6)
        return path

    def record(self, hour):
        records = scan_roots([self.root/"data"])[0]
        return next(r for r in records if r.time.hour == hour)

    @staticmethod
    def tiny_map(record, payload, field, values, path, config, cities, note=""):
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (3,3), (20,40,60)).save(path, format="PNG")

    def test_native_unit_conversions_and_missing_values(self):
        np.testing.assert_allclose(plot.convert("so2", [0.001, 0.025], "ppmv"), [1,25])
        np.testing.assert_allclose(plot.convert("so2", [1,25], "ppbv"), [1,25])
        np.testing.assert_allclose(plot.convert("BC1", [2.5], "ug/kg-dryair"), [2.5])
        np.testing.assert_allclose(plot.convert("OC1", [4], "ug/kg-dryair"), [4])
        with self.assertRaises(ValueError):
            plot.convert("BC1", [2.5], "ug m^-3")
        with self.assertRaises(ValueError):
            plot.convert("so2", [1], "ug m^-3")
        with self.assertRaises(ValueError):
            plot.convert("PM2_5_DRY", [10], "")
        np.testing.assert_allclose(plot.convert("T2", [273.15, 303.15], "K"), [0,30], atol=1e-10)
        np.testing.assert_allclose(plot.convert("Q2", [0.01], "kg kg-1"), [10])
        np.testing.assert_allclose(plot.convert("PSFC", [100000], "Pa"), [1000])
        value = plot.convert("so2", np.ma.array([0.001,np.nan,0.005],mask=[False,False,True]), "ppmv")
        self.assertEqual(value.count(),1)
        self.assertEqual(float(value[0]),1)

    def test_seven_rain_colors_and_explicit_over_range(self):
        spec=self.config["fields"]["RAIN_RATE"]
        self.assertEqual(spec["range"],[0,15])
        self.assertEqual(len(spec["bins"]),8)
        self.assertEqual(len(spec["colors"]),7)
        cmap,norm=plot.color_style(spec)
        midpoints=(np.array(spec["bins"][:-1])+np.array(spec["bins"][1:]))/2
        self.assertEqual(len(set(map(tuple,cmap(norm(midpoints))))),7)
        self.assertFalse(norm.clip)
        self.assertFalse(np.allclose(cmap(norm(20.0)),cmap(norm(12.0))))

    def test_physical_height_interpolation_has_no_extrapolation(self):
        city={"height_agl":[25,100,200],"display_profiles":{"so2":[10,20,30]}}
        targets=np.array([0,25,50,100,200,201])
        values=plot.profile_on_heights(city,"so2",targets)
        self.assertTrue(np.isnan(values[0]))
        np.testing.assert_allclose(values[1:5],[10,10+25/75*10,20,30])
        self.assertTrue(np.isnan(values[-1]))
        city={"height_agl":[25,100,200,300],"display_profiles":{"so2":[10,None,30,40]}}
        values=plot.profile_on_heights(city,"so2",np.array([50,150,250]))
        self.assertTrue(np.isnan(values[:2]).all())
        self.assertEqual(values[2],35)
        self.assertTrue(np.isnan(plot.profile_on_heights({"display_profiles":{"so2":[1,2]}},"so2",targets)).all())

    def test_changed_simulation_or_grid_skips_rain_rate(self):
        previous={"lat":np.array([[10,10],[11,11]]),"lon":np.array([[70,71],[70,71]]),
                  "fields":{"RAINC":np.zeros((2,2)),"RAINNC":np.zeros((2,2))},
                  "units":{"RAINC":"mm","RAINNC":"mm"},"attrs":{"SIMULATION_START_DATE":"2023-06-22_00:00:00"},"counters":{}}
        current=deepcopy(previous)
        current["fields"]["RAINC"][:]=6
        current["fields"]["RAINNC"][:]=9
        rates,quality=plot.rain_products(previous,current,3,self.config)
        np.testing.assert_allclose(rates["RAIN_RATE"],5)
        current["attrs"]["SIMULATION_START_DATE"]="2023-06-23_00:00:00"
        rates,quality=plot.rain_products(previous,current,3,self.config)
        self.assertEqual(rates,{})
        self.assertIn("Simulation",quality["rain"])
        current["attrs"]=previous["attrs"]
        current["lat"]=current["lat"]+1
        rates,quality=plot.rain_products(previous,current,3,self.config)
        self.assertEqual(rates,{})
        self.assertIn("Grid",quality["rain"])

    def test_incremental_cache_reuses_and_recomputes_after_middle_arrival(self):
        p0=self.snapshot(0)
        self.snapshot(6)
        original_hash=hashlib.sha256(p0.read_bytes()).hexdigest()
        r0,r6=self.record(0),self.record(6)
        out=self.root/"plots"
        fields=["PM2_5_DRY","so2","RAIN_RATE"]
        with patch.object(plot,"plot_map",side_effect=self.tiny_map) as render:
            cache0,changed=plot.process_record(r0,None,None,out,self.config,self.cities,fields,"test-config")
            self.assertTrue(changed)
            self.assertIsNone(cache0["cities"]["delhi"]["display_values"]["RAIN_RATE"])
            outside=cache0["cities"]["outside"]
            self.assertEqual(outside["status"],"outside_domain")
            self.assertEqual(outside["profiles"],{})
            self.assertNotIn("PM2_5_DRY",outside["display_values"])
            cache6,changed=plot.process_record(r6,r0,cache0,out,self.config,self.cities,fields,"test-config")
            self.assertTrue(changed)
            self.assertEqual(cache6["cities"]["delhi"]["interval_hours"],6)
            first_rate=cache6["cities"]["delhi"]["display_values"]["RAIN_RATE"]
            calls=render.call_count
            repeated,changed=plot.process_record(r6,r0,cache0,out,self.config,self.cities,fields,"test-config")
            self.assertFalse(changed)
            self.assertEqual(render.call_count,calls)
            self.assertEqual(repeated["fingerprint"],cache6["fingerprint"])
            self.snapshot(3)
            r3=self.record(3)
            cache3,changed=plot.process_record(r3,r0,cache0,out,self.config,self.cities,fields,"test-config")
            self.assertTrue(changed)
            revised,changed=plot.process_record(r6,r3,cache3,out,self.config,self.cities,fields,"test-config")
            self.assertTrue(changed)
            self.assertNotEqual(revised["fingerprint"],cache6["fingerprint"])
            self.assertEqual(revised["cities"]["delhi"]["interval_hours"],3)
            self.assertNotAlmostEqual(revised["cities"]["delhi"]["display_values"]["RAIN_RATE"],first_rate)
            self.assertEqual(len(revised["cities"]["delhi"]["profiles"]["so2"]),39)
        self.assertEqual(hashlib.sha256(p0.read_bytes()).hexdigest(),original_hash)

    def test_city_rate_also_rejects_changed_simulation(self):
        self.snapshot(0)
        path=self.snapshot(3)
        r0,r3=self.record(0),self.record(3)
        first=plot.prepare_city_data(r0,self.cities,None,self.config)
        cached={"time":r0.time.isoformat(),"cities":first}
        with Dataset(path,"r+") as ds:
            ds.SIMULATION_START_DATE="2023-06-21_00:00:00"
        r3=self.record(3)
        second=plot.prepare_city_data(r3,self.cities,cached,self.config)
        self.assertIsNone(second["delhi"]["display_values"]["RAIN_RATE"])
        self.assertTrue(any("simulation start changed" in s for s in second["delhi"]["warnings"]))

    def test_recovered_previous_cache_repairs_city_rain_without_source_changes(self):
        self.snapshot(0)
        self.snapshot(3)
        r0,r3=self.record(0),self.record(3)
        out=self.root/"plots"
        fields=["RAIN_RATE"]
        with patch.object(plot,"plot_map",side_effect=self.tiny_map):
            # A previous input exists but its earlier processing pass failed.
            # Map rain can use the file; city rain has no previous city cache.
            incomplete,changed=plot.process_record(r3,r0,None,out,self.config,self.cities,fields,"test-config")
            self.assertTrue(changed)
            self.assertIsNone(incomplete["cities"]["delhi"]["display_values"]["RAIN_RATE"])
            previous,changed=plot.process_record(r0,None,None,out,self.config,self.cities,fields,"test-config")
            self.assertTrue(changed)
            repaired,changed=plot.process_record(r3,r0,previous,out,self.config,self.cities,fields,"test-config")
            self.assertTrue(changed)
            self.assertNotEqual(incomplete["fingerprint"],repaired["fingerprint"])
            self.assertIsNotNone(repaired["cities"]["delhi"]["display_values"]["RAIN_RATE"])
            self.assertGreater(repaired["cities"]["delhi"]["display_values"]["RAIN_RATE"],0)
            # Neither source signature changed; the repaired predecessor cache
            # itself must invalidate the dependent city calculation.
            self.assertEqual(self.record(0).signature,r0.signature)
            self.assertEqual(self.record(3).signature,r3.signature)

    def test_package_contains_only_current_artifact_inventory(self):
        out=self.root/"results"
        current_map=out/"maps"/"surface"/"01_CTRL"/"PM2_5_DRY.gif"
        current_map.parent.mkdir(parents=True)
        Image.new("RGB",(2,2),(120,40,20)).save(current_map,format="GIF")
        current_table=out/"tables"/"city_timeseries_surface.csv"
        current_table.parent.mkdir(parents=True)
        current_table.write_text("time,value\n2023-06-22T00:00:00,1\n",encoding="utf-8")
        stale_map=out/"maps"/"full"/"01_CTRL"/"PM2_5_DRY.gif"
        stale_map.parent.mkdir(parents=True)
        Image.new("RGB",(2,2),(20,30,40)).save(stale_map,format="GIF")
        stale_table=out/"tables"/"city_timeseries_full.csv"
        stale_table.write_text("stale product from an earlier selection\n",encoding="utf-8")
        (out/"index.html").write_text("<html>Current surface products</html>",encoding="utf-8")
        (out/"data_status.json").write_text('{"source_complete":true}',encoding="utf-8")
        (out/"effective_config.json").write_text('{}',encoding="utf-8")
        (out/".cache").mkdir()
        (out/".cache"/"state.json").write_text(json.dumps({"selection":"current", "artifacts":[str(current_map),str(current_table)]}),encoding="utf-8")
        archive=self.root/"shareable.zip"
        plot.package_results(out,archive)
        with zipfile.ZipFile(archive) as result:
            self.assertEqual(set(result.namelist()),{
                "index.html","data_status.json","effective_config.json",
                "maps/surface/01_CTRL/PM2_5_DRY.gif","tables/city_timeseries_surface.csv"})
        self.assertTrue(stale_map.exists())
        self.assertTrue(stale_table.exists())

    def test_gif_contains_distinct_frames_and_atomic_completion(self):
        frames=[]
        for i,color in enumerate(((255,0,0),(0,255,0),(0,0,255))):
            path=self.root/("frame_%d.png" % i)
            Image.new("RGB",(12,12),color).save(path)
            frames.append(path)
        output=self.root/"animation.gif"
        plot.make_gif(frames,output,300)
        with Image.open(output) as result:
            self.assertEqual(result.n_frames,3)
            self.assertEqual(result.info["duration"],300)
            self.assertEqual(result.info["loop"],0)
            result.seek(2)
            self.assertEqual(result.convert("RGB").getpixel((0,0)),(0,0,255))
        self.assertEqual(list(self.root.glob("*.part*")),[])

    def test_real_cli_smoke_creates_gif_tables_and_gallery(self):
        self.snapshot(0,mode="surface")
        cities=self.root/"cities.csv"
        cities.write_text("rank,name,slug,population_2011,lat,lon\n1,Delhi,delhi,1,28.61,77.21\n",encoding="utf-8")
        cfg=self.root/"config.json"
        cfg.write_text(json.dumps({"map_dpi":35}),encoding="utf-8")
        out=self.root/"result"
        run=subprocess.run([sys.executable,str(KIT/"wrf_classroom.py"),"run","--data",str(self.root/"data"),
                            "--output",str(out),"--cities",str(cities),"--config",str(cfg),
                            "--fields","WIND_SPEED","--max-frames","1"],
                           capture_output=True,text=True,timeout=60)
        self.assertEqual(run.returncode,0,run.stdout+"\n"+run.stderr)
        self.assertTrue((out/"maps"/"surface"/"01_CTRL"/"WIND_SPEED.gif").is_file())
        self.assertTrue((out/"tables"/"city_timeseries_surface.csv").is_file())
        self.assertTrue((out/"index.html").is_file())
        status=json.loads((out/"data_status.json").read_text())
        self.assertEqual(status["processed_records"],1)
        self.assertEqual(status["errors"],[])
        self.assertEqual(status["synthetic_records"],1)
        self.assertFalse((out/".wrf_classroom.lock").exists())


if __name__=="__main__":
    unittest.main()

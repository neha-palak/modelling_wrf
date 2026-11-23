#!/usr/bin/env python3
"""Create a small, explicitly SYNTHETIC WRF Lite classroom test dataset.

These values are mathematical illustrations, not a WRF simulation, historical
analysis, observation, air-quality assessment, or forecast. Do not distribute
these demo values as the actual Indian case. The output can exercise plotting,
installation, masks, physical height coordinates and incremental arrival before
the real HPC reduction finishes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path

import numpy as np
from netCDF4 import Dataset

from wrf_data import DEFAULT_CASES, PRIMARY_FIELDS, VERTICAL_FIELDS

START = datetime(2023, 6, 22)
UNITS = {
    "T2": "K", "Q2": "kg kg-1", "PSFC": "Pa", "U10": "m s-1", "V10": "m s-1",
    "TSK": "K", "PBLH": "m", "HFX": "W m-2", "LH": "W m-2", "SWDOWN": "W m-2",
    "GLW": "W m-2", "RAINC": "mm", "RAINNC": "mm", "GRDFLX": "W m-2",
    "PM2_5_DRY": "ug m^-3", "PM10": "ug m^-3", "TOT_DUST": "ug m^-3",
    "BC1": "ug/kg-dryair", "so2": "ppmv", "OC1": "ug/kg-dryair",
}


def _json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _gaussian(lat, lon, lat0, lon0, width):
    return np.exp(-((lat-lat0)**2 + ((lon-lon0)*0.92)**2) / (2*width**2))


def write_snapshot(path, mode, case_number, hours, grid_size):
    stamp = START + timedelta(hours=hours)
    lat, lon = np.meshgrid(np.linspace(10.0, 32.0, grid_size),
                           np.linspace(68.0, 91.0, grid_size), indexing="ij")
    terrain = (70 + 300*_gaussian(lat, lon, 18, 77, 5)
               + 1600*_gaussian(lat, lon, 33, 83, 2.5))
    zinterfaces = np.concatenate([[0.0], np.geomspace(50.0, 16000.0, 39)])
    zmid = (zinterfaces[:-1] + zinterfaces[1:]) / 2
    nz = 39 if mode == "full" else 1
    zinterfaces, zmid = zinterfaces[:nz+1], zmid[:nz]
    case_factor = [1.0, 1.06, 0.62][case_number]
    phase = hours / 24.0 * 2*np.pi
    wave = np.sin((lon-68)/5 + (lat-10)/6)
    fine = np.sin(lon*2.3) * np.cos(lat*1.8) if case_number == 1 else np.zeros_like(lat)
    pollution = (30 + 150*_gaussian(lat, lon, 28.6, 77.2, 2.5)
                 + 90*_gaussian(lat, lon, 22.6, 88.4, 1.8)
                 + 60*_gaussian(lat, lon, 19.1, 72.9, 1.5))
    plume = _gaussian(lat, lon, 23 + np.sin(phase), 80 + 2*np.cos(phase), 2)
    meteorology = {
        "T2": 298.15 + 6*np.sin((lat-10)/22*np.pi) + 2*np.sin(phase) + 0.1*case_number,
        "Q2": 0.012 + 0.006*_gaussian(lat, lon, 18, 82, 10) + 0.001*np.sin(phase),
        "PSFC": 100800*np.exp(-terrain/8500) + 250*wave,
        "U10": 4 + 6*np.sin((lat-10)/10 + phase) + 0.2*case_number,
        "V10": 3*np.cos((lon-68)/9 + phase) + 1,
        "TSK": 300.15 + 7*np.sin((lat-10)/22*np.pi) + 4*np.sin(phase),
        "PBLH": 600 + 900*(0.5 + 0.5*np.sin(phase)) + 250*wave,
        "HFX": 40 + 140*np.sin(phase) + 25*wave,
        "LH": 160 + 90*np.sin(phase) + 40*wave,
        "SWDOWN": np.full_like(lat, max(0, 850*np.sin(phase))),
        "GLW": 350 + 45*_gaussian(lat, lon, 18, 82, 10) + 10*wave,
        "GRDFLX": 20 + 45*np.sin(phase) + 8*wave,
        # Monotone accumulations with analytically positive local time rates.
        "RAINC": hours*(0.2 + 0.8*_gaussian(lat, lon, 19, 79, 3)) * (1 + 0.03*case_number),
        "RAINNC": (hours*(0.3 + 2*_gaussian(lat, lon, 23, 84, 3))
                   + 0.6*(1-np.cos(hours/8))) * (1 + 0.02*case_number),
    }
    z = zmid[:,None,None]
    transport = 45*plume[None,:,:] * np.exp(-((z-(1700+350*np.sin(phase)))/650)**2)
    chem = {
        "PM2_5_DRY": (pollution[None,:,:]*(1+0.08*np.sin(phase))*np.exp(-z/2200) + transport) * case_factor,
        "PM10": ((pollution[None,:,:]*1.6 + 70*_gaussian(lat,lon,28,72,3))*np.exp(-z/3000) + transport)*case_factor,
        "TOT_DUST": (20 + 220*_gaussian(lat,lon,28,72,3))[None,:,:]*np.exp(-z/3200)*case_factor,
        "BC1": (0.8 + pollution[None,:,:]/80)*np.exp(-z/1800)*case_factor + 0.05*fine,
        "so2": (0.002 + 0.025*_gaussian(lat,lon,23,85,2))[None,:,:]*np.exp(-z/2000)*case_factor,
        "OC1": (1.5 + pollution[None,:,:]/40)*np.exp(-z/2100)*case_factor + 0.08*fine,
    }
    # The intentionally perturbed experiment remains nonnegative for chemistry.
    chem = {name: np.maximum(value, 0) for name, value in chem.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    with Dataset(path, "w", format="NETCDF4") as ds:
        for name, length in (("Time", 1), ("DateStrLen", 19), ("south_north", grid_size),
                             ("west_east", grid_size), ("bottom_top", nz), ("bottom_top_stag", nz+1)):
            ds.createDimension(name, length)
        ds.setncatts({
            "TITLE": "SYNTHETIC CLASSROOM DEMONSTRATION — NOT WRF OUTPUT OR A FORECAST",
            "wrf_classroom_synthetic": 1,
            "wrflite_vertical": mode,
            "wrflite_version": "synthetic-demo-1.0.0",
            "wrflite_interval_hours": 3,
            "wrflite_primary_variables": ",".join(PRIMARY_FIELDS),
            "wrflite_time_semantics": "Synthetic example snapshots at three-hour intervals; rainfall is cumulative.",
            "wrflite_restart_compatible": "false",
            "START_DATE": START.strftime("%Y-%m-%d_%H:%M:%S"),
            "SIMULATION_START_DATE": START.strftime("%Y-%m-%d_%H:%M:%S"),
            "MAP_PROJ": 6,
            "MAP_PROJ_CHAR": "Synthetic regular latitude-longitude demonstration grid",
            "BOTTOM-TOP_GRID_DIMENSION": nz+1,
            "bucket_mm": -1.0,
        })
        t = ds.createVariable("Times", "S1", ("Time", "DateStrLen"))
        t[:] = np.array([list(stamp.strftime("%Y-%m-%d_%H:%M:%S"))], dtype="S1")
        xtime = ds.createVariable("XTIME", "f4", ("Time",))
        xtime.units = "minutes since 2023-06-22 00:00:00"
        xtime[:] = hours*60
        def write(name, data, units, vertical=False, interface=False):
            dims = ("Time", "bottom_top_stag" if interface else "bottom_top", "south_north", "west_east") if vertical else ("Time", "south_north", "west_east")
            var = ds.createVariable(name, "f4", dims, zlib=True, complevel=2, shuffle=True, fletcher32=True)
            var.units = units
            var.description = "SYNTHETIC demonstration values, not an actual model run"
            if name not in ("XLAT", "XLONG"):
                var.coordinates = "XLONG XLAT XTIME"
            var[0] = np.asarray(data, dtype=np.float32)
        for name, data, units in (("XLAT",lat,"degree_north"), ("XLONG",lon,"degree_east"),
                                  ("HGT",terrain,"m"), ("COSALPHA",np.ones_like(lat),"1"),
                                  ("SINALPHA",np.zeros_like(lat),"1")):
            write(name,data,units)
        for name in PRIMARY_FIELDS:
            write(name, chem[name] if name in chem else meteorology[name], UNITS[name], name in VERTICAL_FIELDS)
        interfaces = zinterfaces[:,None,None] + terrain[None,:,:]
        write("PHB",interfaces*9.81,"m2 s-2",True,True)
        write("PH",np.broadcast_to(20*np.sin(phase)*zinterfaces[:,None,None]/16000*9.81,
                                    interfaces.shape),"m2 s-2",True,True)
        pressure = meteorology["PSFC"][None,:,:]*np.exp(-z/8000)
        write("PB",pressure,"Pa",True)
        write("P",np.broadcast_to(100*np.sin(phase)*np.exp(-z/8000),pressure.shape),"Pa",True)


def create_demo(output, steps=4, grid_size=30):
    output = Path(output).expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory is not empty. Choose a new demo directory; nothing was overwritten: " + str(output))
    if not (2 <= steps <= 48):
        raise ValueError("--steps must be between 2 and 48")
    if not (4 <= grid_size <= 100):
        raise ValueError("--grid-size must be between 4 and 100")
    output.mkdir(parents=True, exist_ok=True)
    total_bytes = 0
    for mode in ("full", "surface"):
        manifest = {"version": "synthetic-demo-1.0.0", "synthetic": True,
                    "complete": True, "planned_files": steps*len(DEFAULT_CASES), "files": {}}
        root = output/mode
        for index in range(steps):
            stamp = START + timedelta(hours=index*3)
            for number, case in enumerate(DEFAULT_CASES):
                name = "wrflite_d01_" + stamp.strftime("%Y-%m-%d_%H-%M-%S") + ".nc"
                path = root/case/name
                write_snapshot(path, mode, number, index*3, grid_size)
                nbytes = path.stat().st_size
                total_bytes += nbytes
                manifest["files"][str(path.relative_to(root)).replace("\\","/")] = {
                    "case": case, "time": stamp.strftime("%Y-%m-%d_%H:%M:%S"), "bytes": nbytes,
                    "synthetic": True,
                }
        manifest["output_data_bytes"] = sum(v["bytes"] for v in manifest["files"].values())
        _json(root/"manifest.json",manifest)
    (output/"SYNTHETIC_DEMO_README.txt").write_text(
        "SYNTHETIC DEMONSTRATION DATA — NOT A MODEL FORECAST\n\n"
        "Every value was generated with mathematical functions for testing the classroom kit.\n"
        "The dates are labels only. This is not a simulation of observed June 2023 weather.\n"
        "Do not interpret these fields as real exposure, rain, wind or forecast values.\n"
        "Full: 39 mass levels / 40 interfaces. Surface: 1 mass level / 2 interfaces.\n"
        "Both modes retain the same lowest-layer values and all 14 surface fields.\n",
        encoding="utf-8")
    return {"output": str(output), "files": 2*steps*len(DEFAULT_CASES), "bytes": total_bytes,
            "steps": steps, "grid_shape": [grid_size,grid_size], "synthetic": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=4)
    parser.add_argument("--grid-size", type=int, default=30)
    args=parser.parse_args(argv)
    try:
        result=create_demo(args.output,args.steps,args.grid_size)
    except (ValueError,OSError,RuntimeError) as exc:
        parser.exit(2,str(exc)+"\n")
    print(json.dumps(result,indent=2))


if __name__ == "__main__":
    main()

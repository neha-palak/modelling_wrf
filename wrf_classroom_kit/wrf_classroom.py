#!/usr/bin/env python3
"""Incremental, offline-capable WRF Lite classroom graphics. See README.md.

Source NetCDF files are read-only. Output PNG/GIF/CSV/JSON files are replaced
atomically. One process may write to an output directory at a time.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.colors import BoundaryNorm, ListedColormap, Normalize
    from PIL import Image
    from wrf_data import PRIMARY_FIELDS, VERTICAL_FIELDS, scan_roots, read_surface, read_city_columns, rain_increment
except ImportError as exc:
    raise SystemExit("Missing plotting dependency: %s. Run the setup script first." % exc)

VERSION = "1.0.0"
HERE = Path(__file__).resolve().parent
DERIVED = ["WIND_SPEED", "RAINC_RATE", "RAINNC_RATE", "RAIN_RATE"]
CASE_COLORS = ["#137c98", "#e27d32", "#7b4da0", "#53852e", "#be506a"]
TIMEFMT = "%Y-%m-%dT%H:%M:%S"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                     "axes.titleweight": "semibold", "axes.spines.top": False,
                     "axes.spines.right": False, "savefig.facecolor": "white"})


def clean_json(value):
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, np.ma.MaskedArray):
        return clean_json(value.astype(float).filled(np.nan).tolist())
    if isinstance(value, np.ndarray):
        return clean_json(value.tolist())
    if isinstance(value, (list, tuple)):
        return [clean_json(x) for x in value]
    if isinstance(value, np.generic):
        return clean_json(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.strftime(TIMEFMT)
    return value


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part.%d" % os.getpid())
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def save_json(path, value):
    atomic_text(path, json.dumps(clean_json(value), indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def read_json(path, fallback=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def safe_token(text):
    import re
    result = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(text))
    if result in ("", ".", ".."):
        raise ValueError("Invalid output label: %r" % text)
    return result


def stamp(record):
    return record.time.strftime("%Y-%m-%d_%H-%M-%S")


def digest(value):
    return hashlib.sha256(json.dumps(clean_json(value), sort_keys=True).encode()).hexdigest()


def array(value):
    return np.ma.masked_invalid(np.asarray(value, dtype=float)) if not np.ma.isMaskedArray(value) else np.ma.masked_invalid(value.astype(float))


def scalar(value):
    result = array(value)
    return float(result) if result.size == 1 and not np.ma.getmaskarray(result).any() else None


def normalized_unit(unit):
    return str(unit).lower().replace("μ", "u").replace("µ", "u").replace("⁻", "-").replace("³", "3").replace("²", "2").replace("¹", "1").replace("**", "").replace("^", "").replace(" ", "").replace("_", "")


def convert(field, values, unit):
    """Convert only explicitly recognized units; never assume missing metadata."""
    data = array(values)
    u = normalized_unit(unit)
    if field in ("T2", "TSK"):
        if u in ("k", "kelvin"):
            return data - 273.15
        if u in ("degc", "celsius", "degreecelsius", "degreescelsius", "°c"):
            return data
    elif field == "Q2":
        if u in ("kgkg-1", "kg/kg", "kgkg-1dryair"):
            return data * 1000
        if u in ("gkg-1", "g/kg"):
            return data
    elif field == "PSFC":
        if u in ("pa", "pascal", "pascals"):
            return data / 100
        if u in ("hpa", "mb", "mbar"):
            return data
    elif field in ("U10", "V10"):
        if u in ("ms-1", "m/s", "msec-1"):
            return data
    elif field == "PBLH":
        if u in ("m", "meter", "meters", "metres"):
            return data
    elif field in ("HFX", "LH", "SWDOWN", "GLW", "GRDFLX"):
        if u in ("wm-2", "w/m2"):
            return data
    elif field in ("RAINC", "RAINNC"):
        if u in ("mm", "millimeters", "millimetres"):
            return data
    elif field in ("PM2_5_DRY", "PM10", "TOT_DUST"):
        if u in ("ugm-3", "ug/m3", "microgramsm-3"):
            return data
    elif field in ("BC1", "OC1"):
        if u in ("ug/kg-dryair", "ugkg-1dryair", "ug/kgdryair", "ugkg-dryair-1"):
            return data
    elif field == "so2":
        if u in ("ppmv", "ppm", "umolmol-1", "umol/mol"):
            return data * 1000
        if u in ("ppbv", "ppb", "nmolmol-1", "nmol/mol"):
            return data
    elif field in DERIVED:
        return data
    raise ValueError("%s: unsupported or missing units %r; no assumed conversion" % (field, unit))


def load_config(path):
    config = read_json(HERE / "config.json")
    if path and Path(path).resolve() != (HERE / "config.json").resolve():
        extra = read_json(path)
        if not isinstance(extra, dict):
            raise ValueError("Cannot read configuration: %s" % path)
        for key, value in extra.items():
            if key == "fields":
                for field, spec in value.items():
                    config["fields"].setdefault(field, {}).update(spec)
            else:
                config[key] = value
    for field, spec in config["fields"].items():
        lo, hi = spec["range"]
        if not lo < hi:
            raise ValueError("Invalid range for " + field)
        if "bins" in spec:
            bins = spec["bins"]
            if len(spec["colors"]) != len(bins) - 1 or any(b <= a for a, b in zip(bins, bins[1:])):
                raise ValueError("Each rainfall bin needs exactly one color: " + field)
    return config


def load_cities(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["lat"] = float(row["lat"])
        row["lon"] = float(row["lon"])
        row["rank"] = int(row["rank"])
        row["population_2011"] = int(row["population_2011"])
        row["slug"] = safe_token(row["slug"])
    if len({r["slug"] for r in rows}) != len(rows):
        raise ValueError("City slugs must be unique")
    return rows


def color_style(spec):
    if "bins" in spec:
        cmap = ListedColormap(spec["colors"])
        norm = BoundaryNorm(spec["bins"], cmap.N, clip=False)
    else:
        cmap = plt.get_cmap(spec["cmap"]).copy()
        norm = Normalize(*spec["range"], clip=False)
    cmap.set_bad("#e2e7eb")
    cmap.set_under("#64748b")
    cmap.set_over("#7a0470")
    return cmap, norm


def save_figure(fig, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part.%d" % os.getpid())
    try:
        fig.savefig(temporary, format="png", dpi=fig.dpi)
        os.replace(temporary, path)
    finally:
        plt.close(fig)
        temporary.unlink(missing_ok=True)


def make_gif(frame_paths, destination, duration):
    """Pillow needs decoded frames; one modest 880x810 sequence at a time."""
    if not frame_paths:
        return
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    temporary = destination.with_name(destination.name + ".part.%d" % os.getpid())
    try:
        for path in frame_paths:
            with Image.open(path) as source:
                frames.append(source.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT))
        frames[0].save(temporary, format="GIF", save_all=True, append_images=frames[1:],
                       duration=duration, loop=0, disposal=2, optimize=False)
        os.replace(temporary, destination)
    finally:
        for frame in frames:
            frame.close()
        temporary.unlink(missing_ok=True)


def plot_map(record, payload, field, values, path, config, cities, note=""):
    spec = config["fields"][field]
    cmap, norm = color_style(spec)
    data = array(values)
    lon, lat = array(payload["lon"]), array(payload["lat"])
    if np.ma.getmaskarray(lon).any() or np.ma.getmaskarray(lat).any():
        raise ValueError("Invalid map coordinates; refusing a misregistered map")
    fig, ax = plt.subplots(figsize=(8.8, 8.1), dpi=config["map_dpi"])
    fig.subplots_adjust(left=.10, right=.86, bottom=.20, top=.83)
    ax.set_facecolor("#edf2f6")
    mesh = ax.pcolormesh(lon, lat, data, shading="auto", cmap=cmap, norm=norm, rasterized=True)
    coast = read_json(HERE / "assets" / "coastline_india_region.json", {"lines": []})
    for line in coast["lines"]:
        points = np.asarray(line)
        ax.plot(points[:, 0], points[:, 1], color="#313d48", linewidth=.55)
    bx = np.concatenate([lon[0, :], lon[1:, -1], lon[-1, -2::-1], lon[-2:0:-1, 0], [lon[0, 0]]])
    by = np.concatenate([lat[0, :], lat[1:, -1], lat[-1, -2::-1], lat[-2:0:-1, 0], [lat[0, 0]]])
    ax.plot(bx, by, color="#445563", linewidth=.7, linestyle="--")
    if field == "WIND_SPEED" and payload.get("cosalpha") is not None and payload.get("sinalpha") is not None:
        try:
            u = convert("U10", payload["fields"]["U10"], payload["units"]["U10"])
            v = convert("V10", payload["fields"]["V10"], payload["units"]["V10"])
            cosine, sine = array(payload["cosalpha"]), array(payload["sinalpha"])
            east, north = u * cosine - v * sine, v * cosine + u * sine
            step = max(1, min(lon.shape) // 20)
            ax.quiver(lon[::step, ::step], lat[::step, ::step], east[::step, ::step], north[::step, ::step],
                      color="#243544", scale=260, width=.0022, alpha=.7)
            note += " | arrows: earth-relative"
        except ValueError:
            note += " | wind arrows unavailable"
    offsets = {"mumbai": (-22, -9), "pune": (6, -11), "surat": (5, -9), "ahmedabad": (-27, 6), "delhi": (5, 5),
               "bengaluru": (-45, 7), "chennai": (7, -6)}
    for city in cities:
        ax.scatter(city["lon"], city["lat"], s=17, color="white", edgecolors="#1f2937", linewidths=.6, zorder=5)
        dx, dy = offsets.get(city["slug"], (5, 5))
        ax.annotate(city["name"], (city["lon"], city["lat"]), xytext=(dx, dy), textcoords="offset points",
                    fontsize=7, color="#172e40", zorder=6,
                    bbox={"facecolor": "white", "edgecolor": "none", "alpha": .65, "pad": .4})
    xmin, xmax, ymin, ymax = config["map_extent"]
    ax.set(xlim=(xmin, xmax), ylim=(ymin, ymax), xlabel="Longitude (°E)", ylabel="Latitude (°N)")
    ax.set_aspect(1 / math.cos(math.radians((ymin + ymax) / 2)))
    ax.grid(alpha=.15, linewidth=.5)
    bar = fig.colorbar(mesh, ax=ax, pad=.025, shrink=.9, extend="both", fraction=.045)
    bar.set_label(spec["unit"])
    if "bins" in spec:
        bar.set_ticks(spec["bins"])
    when = record.time.strftime("%d %b %Y  %H:%M UTC")
    fig.text(.10, .94, spec["title"], fontsize=16, weight="bold", color="#173e51")
    fig.text(.10, .898, "%s  ·  %s  ·  %s" % (record.case, record.mode, when), fontsize=11)
    layer = "Lowest model layer; height varies" if field in VERTICAL_FIELDS else "Native surface diagnostic"
    if field.endswith("_RATE"):
        layer = "Mean over preceding interval; not an instantaneous hourly peak"
    fig.text(.10, .865, layer, fontsize=9, color="#51616b")
    finite = data.compressed()
    if finite.size:
        lo, hi = spec["range"]
        stats = "Grid min %.3g | max %.3g | below scale %.1f%% | above scale %.1f%%" % (
            finite.min(), finite.max(), 100 * np.mean(finite < lo), 100 * np.mean(finite > hi))
    else:
        stats = "No valid data for this field/interval"
    fig.text(.10, .105, stats, fontsize=8)
    fig.text(.10, .080, note[:155], fontsize=8, color="#5b6872")
    fig.text(.10, .052, "India view · dashed line: model coverage · missing cells: grey · fixed display scale", fontsize=8)
    fig.text(.10, .027, "Coastline: Natural Earth 110m; city points: documented reference locations", fontsize=7, color="#687986")
    if record.synthetic:
        fig.text(.53, .49, "SYNTHETIC DEMO", ha="center", va="center", rotation=30,
                 fontsize=30, color="#39495a", alpha=.22, weight="bold")
    save_figure(fig, path)


def same_grid(first, second):
    return all(np.shape(first[k]) == np.shape(second[k]) and np.allclose(first[k], second[k], rtol=0, atol=1e-6, equal_nan=False) for k in ("lat", "lon"))


def choose_bucket(config, previous, current):
    if config.get("bucket_mm") is not None:
        return float(config["bucket_mm"])
    values = []
    for attrs in (previous.get("attrs", {}), current.get("attrs", {})):
        for key in ("bucket_mm", "BUCKET_MM"):
            if key in attrs:
                try:
                    values.append(float(attrs[key]))
                except (TypeError, ValueError):
                    pass
    if values and any(v != values[0] for v in values):
        raise ValueError("Rain bucket size changed between files")
    return values[0] if values and values[0] > 0 else None


def rain_products(previous, current, hours, config):
    result, quality = {}, {}
    if not same_grid(previous, current):
        return {}, {"rain": "Grid moved/changed; rainfall differencing was skipped"}
    old_start = previous.get("attrs", {}).get("SIMULATION_START_DATE")
    new_start = current.get("attrs", {}).get("SIMULATION_START_DATE")
    if old_start and new_start and old_start != new_start:
        return {}, {"rain": "Simulation start changed; rainfall differencing was skipped"}
    bucket = choose_bucket(config, previous, current)
    for name in ("RAINC", "RAINNC"):
        if name not in previous["fields"] or name not in current["fields"]:
            continue
        old = convert(name, previous["fields"][name], previous["units"].get(name, ""))
        new = convert(name, current["fields"][name], current["units"].get(name, ""))
        counter = "I_" + name
        rate, info = rain_increment(old, new, hours, bucket,
                                    previous.get("counters", {}).get(counter), current.get("counters", {}).get(counter))
        result[name + "_RATE"] = rate
        quality[name + "_RATE"] = info
    if "RAINC_RATE" in result and "RAINNC_RATE" in result:
        result["RAIN_RATE"] = result["RAINC_RATE"] + result["RAINNC_RATE"]
    return result, quality


def prepare_city_data(record, cities, previous_cache, config):
    entries = read_city_columns(record, cities)
    for slug, city in entries.items():
        city["native_values"] = dict(city.get("values", {}))
        city["display_values"] = {}
        city["display_profiles"] = {}
        city["interval_hours"] = None
        city["rain_quality"] = {}
        for field, value in city.get("values", {}).items():
            try:
                city["display_values"][field] = scalar(convert(field, value, city["units"].get(field, "")))
                if field in city.get("profiles", {}):
                    city["display_profiles"][field] = convert(field, city["profiles"][field], city["units"].get(field, ""))
            except ValueError as exc:
                city["warnings"].append(str(exc))
        u, v = city["display_values"].get("U10"), city["display_values"].get("V10")
        city["display_values"]["WIND_SPEED"] = math.hypot(u, v) if u is not None and v is not None else None
        for name in ("RAINC_RATE", "RAINNC_RATE", "RAIN_RATE"):
            city["display_values"][name] = None
        old_city = previous_cache.get("cities", {}).get(slug) if previous_cache else None
        if not old_city or not city.get("inside") or not old_city.get("inside"):
            continue
        previous_time = datetime.fromisoformat(previous_cache["time"])
        hours = (record.time - previous_time).total_seconds() / 3600
        city["interval_hours"] = hours
        if any(abs(city[key] - old_city[key]) > 1e-6 for key in ("grid_lat", "grid_lon")):
            city["warnings"].append("Rain rates unavailable because the selected grid cell moved")
            continue
        old_start = old_city.get("attrs", {}).get("SIMULATION_START_DATE")
        new_start = city.get("attrs", {}).get("SIMULATION_START_DATE")
        if old_start and new_start and old_start != new_start:
            city["warnings"].append("Rain rates unavailable because the simulation start changed")
            continue
        try:
            bucket = choose_bucket(config, old_city, city)
            for name in ("RAINC", "RAINNC"):
                old = old_city.get("display_values", {}).get(name)
                new = city["display_values"].get(name)
                if old is None or new is None:
                    continue
                counter = "I_" + name
                rate, quality = rain_increment(old, new, hours, bucket,
                                               old_city.get("counters", {}).get(counter), city.get("counters", {}).get(counter))
                city["display_values"][name + "_RATE"] = scalar(rate)
                city["rain_quality"][name + "_RATE"] = quality
            a, b = city["display_values"]["RAINC_RATE"], city["display_values"]["RAINNC_RATE"]
            city["display_values"]["RAIN_RATE"] = a + b if a is not None and b is not None else None
        except ValueError as exc:
            city["warnings"].append(str(exc))
    return clean_json(entries)


def record_cache_path(out, record):
    return out / ".cache" / "records" / safe_token(record.mode) / safe_token(record.case) / (stamp(record) + ".json")


def process_record(record, previous_record, previous_cache, out, config, cities, fields, config_hash):
    required_fingerprint = digest([VERSION, config_hash, record.signature, previous_record.signature if previous_record else None,
                                   previous_cache.get("fingerprint") if previous_cache else None])
    cached_path = record_cache_path(out, record)
    cached = read_json(cached_path)
    if cached and cached.get("fingerprint") == required_fingerprint and all(Path(x).is_file() for x in cached.get("frames", {}).values()):
        return cached, False
    native_fields = list(dict.fromkeys([x for x in fields if x in PRIMARY_FIELDS] + ["U10", "V10", "RAINC", "RAINNC"]))
    payload = read_surface(record, native_fields)
    warnings = list(payload.get("warnings", []))
    maps, notes = {}, {}
    for field in fields:
        if field in payload["fields"]:
            try:
                maps[field] = convert(field, payload["fields"][field], payload["units"].get(field, ""))
            except ValueError as exc:
                warnings.append(str(exc))
    if "WIND_SPEED" in fields and all(x in payload["fields"] for x in ("U10", "V10")):
        try:
            maps["WIND_SPEED"] = np.ma.sqrt(convert("U10", payload["fields"]["U10"], payload["units"]["U10"])**2
                                           + convert("V10", payload["fields"]["V10"], payload["units"]["V10"])**2)
        except ValueError as exc:
            warnings.append(str(exc))
    rain_requested = [x for x in fields if x.endswith("_RATE")]
    if previous_record and rain_requested:
        try:
            previous = read_surface(previous_record, ["RAINC", "RAINNC"])
            hours = (record.time - previous_record.time).total_seconds() / 3600
            products, quality = rain_products(previous, payload, hours, config)
            for name, value in products.items():
                if name not in fields:
                    continue
                maps[name] = value
                notes[name] = "Preceding %.3g h; missing/reset/bucket-unknown cells remain missing" % hours
                if abs(hours - config["expected_interval_hours"]) > 1e-6:
                    notes[name] = "TIME GAP: preceding %.3g h average; no hourly peaks inferred" % hours
            for name, info in quality.items():
                if isinstance(info, str) or info.get("status") != "ok":
                    warnings.append("%s: %s" % (name, info))
        except (OSError, RuntimeError, ValueError) as exc:
            warnings.append("Rain-rate calculation deferred: %s" % exc)
    for name in rain_requested:
        if name not in maps:
            maps[name] = np.ma.masked_all(payload["lat"].shape)
            notes[name] = "Unavailable: no valid preceding completed accumulation pair"
    for name in ("RAINC", "RAINNC"):
        if name in fields:
            notes[name] = "Native stored accumulator (mm); see separate rain-rate product for mm/h"
    entries = prepare_city_data(record, cities, previous_cache, config)
    frames = {}
    for field in fields:
        if field not in maps:
            warnings.append("No map produced for " + field)
            continue
        frame = out / ".cache" / "maps" / safe_token(record.mode) / safe_token(record.case) / field / (stamp(record) + ".png")
        plot_map(record, payload, field, maps[field], frame, config, cities, notes.get(field, ""))
        frames[field] = str(frame.resolve())
    cached = {"fingerprint": required_fingerprint, "path": str(record.path), "case": record.case,
              "mode": record.mode, "time": record.time.strftime(TIMEFMT), "synthetic": record.synthetic,
              "frames": frames, "cities": entries, "warnings": warnings, "source_signature": record.signature}
    save_json(cached_path, cached)
    return cached, True


def write_city_tables(out, caches, config):
    import gzip
    modes = sorted({c["mode"] for c in caches})
    columns = ["time_utc", "case", "mode", "city", "status", "field", "native_value", "native_unit",
               "display_value", "display_unit", "requested_lat", "requested_lon", "grid_lat", "grid_lon",
               "distance_km", "lowest_height_agl_m", "lowest_pressure_hpa", "interval_hours", "synthetic"]
    profile_columns = ["time_utc", "case", "city", "field", "model_level_1based", "height_agl_m", "pressure_hpa",
                       "native_value", "native_unit", "display_value", "display_unit", "synthetic"]
    for mode in modes:
        destination = out / "tables" / ("city_timeseries_%s.csv" % safe_token(mode))
        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp = destination.with_name(destination.name + ".part")
        with tmp.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            for cache in caches:
                if cache["mode"] != mode:
                    continue
                for city in cache["cities"].values():
                    for field in list(PRIMARY_FIELDS) + DERIVED:
                        heights, pressures = city.get("height_agl"), city.get("pressure_hpa")
                        writer.writerow({"time_utc": cache["time"] + "Z", "case": cache["case"], "mode": mode,
                            "city": city["name"], "status": city["status"], "field": field,
                            "native_value": city.get("native_values", {}).get(field), "native_unit": city.get("units", {}).get(field, "derived"),
                            "display_value": city.get("display_values", {}).get(field), "display_unit": config["fields"][field]["unit"],
                            "requested_lat": city["lat"], "requested_lon": city["lon"], "grid_lat": city["grid_lat"], "grid_lon": city["grid_lon"],
                            "distance_km": city["distance_km"], "lowest_height_agl_m": heights[0] if heights else None,
                            "lowest_pressure_hpa": pressures[0] if pressures else None, "interval_hours": city.get("interval_hours"),
                            "synthetic": cache["synthetic"]})
        os.replace(tmp, destination)
        destination = out / "tables" / ("city_profiles_%s.csv.gz" % safe_token(mode))
        tmp = destination.with_name(destination.name + ".part")
        with gzip.open(tmp, "wt", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=profile_columns)
            writer.writeheader()
            for cache in caches:
                if cache["mode"] != mode:
                    continue
                for city in cache["cities"].values():
                    for field, values in city.get("profiles", {}).items():
                        displayed = city.get("display_profiles", {}).get(field, [])
                        for level, value in enumerate(values):
                            heights, pressures = city.get("height_agl"), city.get("pressure_hpa")
                            writer.writerow({"time_utc": cache["time"] + "Z", "case": cache["case"], "city": city["name"],
                                "field": field, "model_level_1based": level + 1,
                                "height_agl_m": heights[level] if heights and level < len(heights) else None,
                                "pressure_hpa": pressures[level] if pressures and level < len(pressures) else None,
                                "native_value": value, "native_unit": city["units"].get(field, ""),
                                "display_value": displayed[level] if level < len(displayed) else None,
                                "display_unit": config["fields"][field]["unit"], "synthetic": cache["synthetic"]})
        os.replace(tmp, destination)


def date_axis(ax):
    locator = mdates.AutoDateLocator(minticks=3, maxticks=5)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))


def separated_series(times, values, expected_hours):
    """Insert NaN across missing timestamps rather than drawing an invented line."""
    x, y = [], []
    for index, (when, value) in enumerate(zip(times, values)):
        if index and (when - times[index-1]).total_seconds() > expected_hours * 3600 * 1.01:
            x.append(times[index-1] + (when - times[index-1]) / 2)
            y.append(np.nan)
        x.append(when)
        y.append(np.nan if value is None else value)
    return x, y


def plot_timeseries(out, caches, cities, fields, config):
    outputs = []
    for mode in sorted({c["mode"] for c in caches}):
        subset = [c for c in caches if c["mode"] == mode]
        cases = sorted({c["case"] for c in subset})
        for field in fields:
            spec = config["fields"][field]
            all_values = [city.get("display_values", {}).get(field) for c in subset for city in c["cities"].values()]
            finite_values = [x for x in all_values if x is not None and math.isfinite(x)]
            series_lo = min([spec["range"][0]] + finite_values)
            series_hi = max([spec["range"][1]] + finite_values)
            span = max(series_hi - series_lo, 1)
            fig, axes = plt.subplots(5, 2, figsize=(13.5, 13.8), dpi=config["map_dpi"])
            fig.subplots_adjust(hspace=.43, wspace=.26, top=.88, bottom=.07, left=.08, right=.96)
            legend_handles = {}
            any_synthetic = any(c["synthetic"] for c in subset)
            for ax, city in zip(axes.ravel(), cities):
                available = False
                for idx, case in enumerate(cases):
                    records = sorted((c for c in subset if c["case"] == case), key=lambda c: c["time"])
                    times = [datetime.fromisoformat(c["time"]) for c in records]
                    samples = [c["cities"].get(city["slug"], {}) for c in records]
                    values = [s.get("display_values", {}).get(field) for s in samples]
                    if not any(v is not None for v in values):
                        continue
                    available = True
                    # Shared city axes expand beyond the map window when needed;
                    # numerical extremes remain visible rather than clipped.
                    xs, ys = separated_series(times, values, config["expected_interval_hours"])
                    handle, = ax.plot(xs, ys, "o-", ms=2.8, lw=1.25, label=case, color=CASE_COLORS[idx % len(CASE_COLORS)])
                    legend_handles[case] = handle
                ax.set_title("%d  %s" % (city["rank"], city["name"]), loc="left", fontsize=10)
                ax.set_ylabel(spec["unit"], fontsize=8)
                ax.tick_params(labelsize=8)
                ax.grid(alpha=.18)
                ax.set_ylim(series_lo - .025 * span, series_hi + .025 * span)
                date_axis(ax)
                if not available:
                    ax.text(.5, .5, "Outside model coverage / no valid data", ha="center", va="center", fontsize=8, transform=ax.transAxes)
            for ax in axes.ravel()[len(cities):]:
                ax.set_visible(False)
            fig.text(.08, .956, spec["title"] + " · city time series", fontsize=16, weight="bold", color="#173e51")
            fig.text(.08, .930, "%s subset · UTC · nearest grid cells to documented city points · unclipped numerical values" % mode, fontsize=9)
            if legend_handles:
                fig.legend(list(legend_handles.values()), list(legend_handles), loc="upper left", bbox_to_anchor=(.075, .920), ncol=max(1, len(cases)), frameon=False, fontsize=9)
            if any_synthetic:
                fig.text(.97, .96, "SYNTHETIC DEMO", ha="right", color="#aa3344", fontsize=10, weight="bold")
            footer = "City order: Census 2011 urban agglomerations and standalone cities; model grid-cell values, not observations."
            if field.endswith("_RATE"):
                footer += " Rates are preceding-interval means; first sample unavailable."
            fig.text(.08, .025, footer, fontsize=8)
            path = out / "city_timeseries" / safe_token(mode) / (field + ".png")
            save_figure(fig, path)
            outputs.append(path)
    return outputs


def profile_on_heights(city, field, targets):
    """Interpolate between adjacent valid model levels only; no extrapolation."""
    values = np.asarray(city.get("display_profiles", {}).get(field, []), dtype=float)
    heights = city.get("height_agl")
    output = np.full(len(targets), np.nan)
    if heights is None or len(values) != len(heights) or len(values) < 2:
        return output
    heights = np.asarray(heights, dtype=float)
    if np.any(np.diff(heights[np.isfinite(heights)]) <= 0):
        return output
    for index in range(len(heights) - 1):
        h0, h1 = heights[index:index+2]
        v0, v1 = values[index:index+2]
        if not all(math.isfinite(x) for x in (h0, h1, v0, v1)) or h1 <= h0:
            continue
        valid = (targets >= h0) & (targets <= h1)
        output[valid] = v0 + (v1 - v0) * (targets[valid] - h0) / (h1 - h0)
    return output


def vertical_matrix(records, city_slug, field, config, origin):
    heights = np.asarray(config["height_grid_m"], dtype=float)
    heights = heights[heights <= config["max_plot_height_m"]]
    times, columns = [], []
    last = None
    for record in sorted(records, key=lambda c: c["time"]):
        when = datetime.fromisoformat(record["time"])
        if last and (when - last).total_seconds() > config["expected_interval_hours"] * 3600 * 1.01:
            times.append(((last + (when-last)/2) - origin).total_seconds() / 3600)
            columns.append(np.full(len(heights), np.nan))
        times.append((when - origin).total_seconds() / 3600)
        columns.append(profile_on_heights(record["cities"].get(city_slug, {}), field, heights))
        last = when
    return np.asarray(times), heights / 1000, np.asarray(columns, dtype=float).T


def plot_vertical_cities(out, caches, cities, fields, config):
    records = [c for c in caches if c["mode"] == "full"]
    if not records:
        return []
    cases = sorted({c["case"] for c in records})
    origin = min(datetime.fromisoformat(c["time"]) for c in records)
    last = max(datetime.fromisoformat(c["time"]) for c in records)
    max_hour = max((last-origin).total_seconds()/3600, config["expected_interval_hours"])
    outputs = []
    for city in cities:
        for field in [f for f in fields if f in VERTICAL_FIELDS]:
            spec = config["fields"][field]
            cmap, norm = color_style(spec)
            profile_values = [v for c in records for v in c["cities"].get(city["slug"], {}).get("display_profiles", {}).get(field, []) if v is not None]
            zlo = min([spec["range"][0]] + profile_values)
            zhi = max([spec["range"][1]] + profile_values)
            single_case = len(cases) == 1
            text_left = .09 if single_case else .06
            fig = plt.figure(figsize=(max(11, 5 * len(cases)), 8.5), dpi=config["map_dpi"])
            fig.subplots_adjust(top=.82, bottom=.13, left=text_left,
                                right=.87 if single_case else .93, hspace=.40, wspace=.28)
            mesh = None
            for idx, case in enumerate(cases):
                selected = [c for c in records if c["case"] == case]
                x, y, z = vertical_matrix(selected, city["slug"], field, config, origin)
                ax = fig.add_subplot(2, len(cases), idx + 1)
                ax.set_title(case, loc="left", fontsize=11)
                ax.set(xlabel="Hours from first available UTC time", ylabel="Height above ground (km)",
                       xlim=(0, max_hour), ylim=(0, config["max_plot_height_m"]/1000))
                finite = np.isfinite(z)
                if finite.any():
                    mesh = ax.pcolormesh(x, y, np.ma.masked_invalid(z), shading="auto", cmap=cmap, norm=norm)
                else:
                    ax.text(.5, .5, "No physical-height profile available\n(outside domain / support fields missing)",
                            transform=ax.transAxes, ha="center", va="center", fontsize=9)
                ax.set_facecolor("#e2e7eb")
                ax3 = fig.add_subplot(2, len(cases), idx + 1 + len(cases), projection="3d")
                ax3.set(xlabel="Elapsed hours", ylabel="Height AGL (km)", zlabel=spec["unit"])
                ax3.set_xlim(0, max_hour)
                ax3.set_ylim(0, config["max_plot_height_m"]/1000)
                ax3.set_zlim(zlo, zhi)
                ax3.view_init(elev=27, azim=-132)
                if len(x) >= 2 and finite.any():
                    xx, yy = np.meshgrid(x, y)
                    ax3.plot_surface(xx, yy, z, cmap=cmap, norm=norm, linewidth=.15, antialiased=True,
                                     rstride=1, cstride=1, alpha=.96)
                else:
                    ax3.text2D(.03, .85, "3D time-height surface needs\nat least two valid times", transform=ax3.transAxes, fontsize=9)
                ax3.tick_params(labelsize=7)
            fig.text(text_left, .945, "%s · %s" % (city["name"], spec["title"]), fontsize=17, color="#173e51", weight="bold")
            fig.text(text_left, .902, "Top: time–height concentration  |  Bottom: 3D time–height–concentration surface", fontsize=10)
            fig.text(text_left, .865, "Origin: %s UTC · height from PH + PHB and terrain · linear vertical interpolation; no extrapolation" % origin.strftime("%d %b %Y %H:%M"), fontsize=9)
            if mesh is not None:
                color_ax = fig.add_axes([.91 if single_case else .95, .52, .016 if single_case else .014, .28])
                fig.colorbar(mesh, cax=color_ax, extend="both", label=spec["unit"])
            fig.text(text_left, .055, "Nearest model grid cell, not a city-wide mean. Full native model levels are retained in the compressed profile CSV.", fontsize=9)
            fig.text(text_left, .030, "Grey/missing: absent data, missing time interval, below the lowest level, or above available levels.", fontsize=8)
            if any(c["synthetic"] for c in records):
                fig.text(.98, .965, "SYNTHETIC DEMO", ha="right", fontsize=10, color="#aa3344", weight="bold")
            path = out / "city_vertical" / city["slug"] / (field + ".png")
            save_figure(fig, path)
            outputs.append(path)
    return outputs


def write_gallery(out, status, artifacts, config):
    groups = defaultdict(list)
    for path in sorted(set(Path(p) for p in artifacts)):
        if path.is_file():
            relative = path.relative_to(out).as_posix()
            groups[relative.split("/")[0]].append(relative)
    summary = ("Conversion complete; all selected ready records processed." if status.get("source_complete") is True and not status.get("errors") and not status.get("preview")
               else "Partial/live dataset: figures show the completed records currently available.")
    if status.get("completion_scope") == "selected_cases":
        summary = ("Selected group data complete; all selected ready records processed."
                   if status.get("source_complete") is True and not status.get("errors") and not status.get("preview")
                   else "Selected group dataset is partial or previewed; figures show the completed records currently available.")
        if status.get("scope_cases"):
            summary += " Groups: " + ", ".join(status["scope_cases"]) + "."
    if status.get("source_complete") is None:
        summary = "Available files processed. Overall conversion completion is unknown without a manifest."
    sections = []
    headings = {"maps": "India-wide animations", "city_timeseries": "City time series", "city_vertical": "City time–height and 3D plots",
                "profile_animations": "Animated vertical profiles", "tables": "Downloadable numerical tables"}
    for group, paths in groups.items():
        cards = []
        for rel in paths:
            safe = html.escape(rel, quote=True)
            preview = '<img src="%s" loading="lazy" alt="%s">' % (safe, safe) if rel.lower().endswith((".png", ".gif")) else ""
            cards.append('<article><a href="%s">%s<strong>%s</strong></a></article>' % (safe, preview, safe))
        sections.append('<section><h2>%s (%d)</h2><div class="grid">%s</div></section>' % (headings.get(group, group), len(paths), "".join(cards)))
    warnings = status.get("warnings", []) + status.get("errors", [])
    warning_html = "" if not warnings else '<details><summary>Data notes (%d)</summary><ul>%s</ul></details>' % (len(warnings), "".join("<li>%s</li>" % html.escape(str(w)) for w in warnings[:100]))
    text = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>WRF India Classroom Results</title><style>
body{font:16px/1.5 system-ui,sans-serif;background:#eef3f6;color:#203947;margin:0}header,main{max-width:1280px;margin:auto;padding:28px}header{background:#173e51;color:white;border-radius:0 0 18px 18px}h1{margin:0;font-size:30px}h2{font-size:22px;margin-top:34px}.meta{opacity:.85}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}article{background:white;border-radius:12px;padding:12px;box-shadow:0 3px 14px #173e5110}article img{width:100%;height:290px;object-fit:contain}a{color:#176d8c;overflow-wrap:anywhere;text-decoration:none}strong{display:block;font-size:13px;padding:8px}details{padding:16px;background:white;border-radius:10px}li{overflow-wrap:anywhere}.note{background:#fff;padding:18px;border-radius:12px}.pill{display:inline-block;background:#ffffff22;padding:4px 12px;border-radius:20px}</style>
<header><h1>WRF India · Classroom results</h1><p>''' + html.escape(summary) + '''</p><p class="pill">''' + str(status.get("processed_records", 0)) + ''' snapshots processed</p><p class="meta">UTC simulation times · fixed map legends · source NetCDF files unchanged</p></header><main>
<p class="note">All 20 primary fields have surface products. Six aerosol/chemistry fields also support vertical products when full levels and physical-height support are present. BC1/OC1 retain µg/kg dry-air units. SO₂ is displayed in ppbv. Rain-rate maps are interval means, not hourly maxima. Model grid cells are not city-wide averages or observations. Any synthetic test output is visibly marked.</p>
<p>Reload this page after another processing pass. GIFs loop automatically. Right-click an image to save it; numerical tables retain unclipped values.</p>
''' + warning_html + "".join(sections) + '</main></html>'
    atomic_text(out / "index.html", text)


def process_available(args, config, cities):
    out = Path(args.output).expanduser().resolve()
    records, warnings, discovery = scan_roots([Path(p) for p in args.data], config)
    groups = defaultdict(list)
    for record in records:
        groups[(record.mode, record.case)].append(record)
    chosen = []
    for values in groups.values():
        values.sort(key=lambda r: r.time)
        chosen.extend(values[:args.max_frames] if args.max_frames else values)
    fields = args.fields.split(",") if args.fields else list(PRIMARY_FIELDS) + DERIVED
    fields = list(dict.fromkeys(f.strip() for f in fields if f.strip()))
    unknown = set(fields) - set(PRIMARY_FIELDS) - set(DERIVED)
    if unknown:
        raise ValueError("Unknown fields: " + ", ".join(sorted(unknown)))
    code_identity = hashlib.sha256(Path(__file__).read_bytes() + (HERE / "wrf_data.py").read_bytes()).hexdigest()
    config_hash = digest([config, cities, fields, code_identity])
    selection = digest([config_hash, [(r.mode, r.case, r.time.isoformat(), r.signature) for r in chosen]])
    previous_state = read_json(out / ".cache" / "state.json", {})
    caches, errors = [], []
    changed = False
    previous_by_group = {}
    cache_by_group = {}
    for idx, record in enumerate(chosen):
        key = (record.mode, record.case)
        old_record = previous_by_group.get(key)
        old_cache = cache_by_group.get(key)
        try:
            cache, updated = process_record(record, old_record, old_cache, out, config, cities, fields, config_hash)
            caches.append(cache)
            changed = changed or updated
            cache_by_group[key] = cache
            warnings.extend("%s/%s %s: %s" % (record.mode, record.case, stamp(record), w) for w in cache.get("warnings", []))
            if updated:
                print("Rendered %d/%d: %s / %s / %s" % (idx+1, len(chosen), record.mode, record.case, stamp(record)), flush=True)
        except (OSError, RuntimeError, ValueError, KeyError, IndexError) as exc:
            errors.append("%s: %s" % (record.path.name, exc))
            print("Deferred: %s: %s" % (record.path.name, exc), file=sys.stderr, flush=True)
            cache_by_group[key] = None
        previous_by_group[key] = record
    rebuild = (changed or selection != previous_state.get("selection") or not (out / "index.html").exists()
               or any(not Path(p).is_file() for p in previous_state.get("artifacts", [])))
    artifacts = []
    if caches and rebuild:
        map_groups = defaultdict(list)
        for cache in caches:
            for field, frame in cache["frames"].items():
                map_groups[(cache["mode"], cache["case"], field)].append((cache["time"], frame))
        for (mode, case, field), frames in sorted(map_groups.items()):
            destination = out / "maps" / safe_token(mode) / safe_token(case) / (field + ".gif")
            make_gif([f for _, f in sorted(frames)], destination, config["gif_frame_ms"])
            artifacts.append(destination)
        print("Updating city tables and comparison figures...", flush=True)
        write_city_tables(out, caches, config)
        artifacts += plot_timeseries(out, caches, cities, fields, config)
        artifacts += plot_vertical_cities(out, caches, cities, fields, config)
        artifacts += plot_profile_gifs(out, caches, cities, fields, config)
        for mode in sorted({c["mode"] for c in caches}):
            artifacts += [out / "tables" / ("city_timeseries_%s.csv" % safe_token(mode)),
                          out / "tables" / ("city_profiles_%s.csv.gz" % safe_token(mode))]
        save_json(out / ".cache" / "state.json", {"selection": selection, "artifacts": [str(p) for p in artifacts]})
    elif caches:
        artifacts = [Path(p) for p in previous_state.get("artifacts", [])]
    else:
        save_json(out / ".cache" / "state.json", {"selection": selection, "artifacts": []})
    for cache in caches:
        for city in cache["cities"].values():
            warnings.extend("%s %s: %s" % (cache["case"], city["name"], w) for w in city.get("warnings", []))
    status = {"version": VERSION, "updated_utc": datetime.now(timezone.utc).isoformat(),
              "source_complete": discovery["complete"], "processed_records": len(caches),
              "completion_scope": discovery.get("completion_scope", "manifest_dataset"),
              "scope_cases": discovery.get("scope_cases", []),
              "available_records": len(records), "selected_records": len(chosen),
              "preview": len(chosen) < len(records), "fields": fields,
              "errors": errors, "warnings": list(dict.fromkeys(warnings)), "discovery": discovery,
              "synthetic_records": sum(bool(c["synthetic"]) for c in caches),
              "vertical_products": "Physical-height plots require full levels plus PH, PHB, HGT; native level data remain in profile CSV.",
              "rain_semantics": "Actual elapsed interval means, first interval unavailable, resets/unknown buckets masked.",
              "city_basis": "Census 2011 final urban agglomerations and standalone cities; representative points, nearest model cells."}
    save_json(out / "data_status.json", status)
    save_json(out / "effective_config.json", config)
    write_gallery(out, status, artifacts, config)
    print("Ready: %d/%d selected snapshots. Open %s" % (len(caches), len(chosen), out / "index.html"), flush=True)
    return status, selection


def inspect_data(args, config, cities):
    records, warnings, status = scan_roots([Path(p) for p in args.data], config)
    samples = {}
    for record in records:
        samples.setdefault((record.mode, record.case), record)
    report = {"status": status, "warnings": warnings, "samples": []}
    for (mode, case), record in sorted(samples.items()):
        payload = read_surface(record)
        columns = read_city_columns(record, cities)
        report["samples"].append({"mode": mode, "case": case, "first_time_utc": record.time,
            "grid_shape": payload["lat"].shape, "available_fields": list(payload["fields"]),
            "missing_fields": sorted(set(PRIMARY_FIELDS) - set(payload["fields"])), "units": payload["units"],
            "synthetic": record.synthetic, "city_coverage": [{"name": x["name"], "status": x["status"],
                "distance_km": x["distance_km"], "levels": x["vertical_levels"],
                "height_available": x["height_agl"] is not None} for x in columns.values()]})
    print(json.dumps(clean_json(report), indent=2, ensure_ascii=False))
    return 0 if records else 1


class OutputLock:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / ".wrf_classroom.lock"
        self.owned = False

    def __enter__(self):
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            with self.path.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps({"pid": os.getpid(), "started_utc": datetime.now(timezone.utc).isoformat()}))
            self.owned = True
        except FileExistsError as exc:
            raise ValueError("An output lock exists: %s. Use a different output folder, or remove the stale lock only after confirming its process has stopped." % self.path) from exc
        return self

    def __exit__(self, *args):
        if self.owned:
            self.path.unlink(missing_ok=True)


def package_results(output, archive):
    import zipfile
    root, destination = Path(output).resolve(), Path(archive).resolve()
    if not (root / "index.html").is_file():
        raise ValueError("No results index exists in " + str(root))
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.name + ".part")
    state = read_json(root / ".cache" / "state.json")
    if not state:
        raise ValueError("Current result inventory is missing; rerun the plotting command before packaging")
    inventory = [Path(p) for p in state["artifacts"]] + [root / "index.html", root / "data_status.json", root / "effective_config.json"]
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=4) as bundle:
        for path in sorted(set(inventory)):
            if not path.is_file() or path == temp or path == destination:
                continue
            if not path.resolve().is_relative_to(root):
                raise ValueError("Result path is outside its output directory: " + str(path))
            relative = path.relative_to(root)
            if any(p.startswith(".") for p in relative.parts):
                continue
            if path.name.endswith(".part") or ".part." in path.name:
                continue
            bundle.write(path, arcname=relative.as_posix())
    os.replace(temp, destination)
    print("Saved shareable results: %s (%.1f MiB)" % (destination, destination.stat().st_size/2**20))


def parser():
    result = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = result.add_subparsers(dest="command", required=True)
    for command in ("inspect", "run", "watch"):
        item = sub.add_parser(command)
        item.add_argument("--data", nargs="+", required=True, help="Full or surface dataset root(s), containing experiment folders and manifest.json")
        item.add_argument("--output", default="classroom_output", help="Graphics/results directory")
        item.add_argument("--config", type=Path, help="Optional JSON overrides of config.json")
        item.add_argument("--cities", type=Path, default=HERE/"cities.csv")
        item.add_argument("--fields", help="Comma-separated subset; default all20 + windspeed +3rainrates")
        item.add_argument("--max-frames", type=int, help="Preview: first N timestamps per experiment/mode")
        if command == "watch":
            item.add_argument("--poll-seconds", type=float, default=60)
            item.add_argument("--idle-minutes", type=float, default=30, help="Stop after this long with no new completed files; rerun to resume")
    package = sub.add_parser("package")
    package.add_argument("--output", required=True)
    package.add_argument("--archive", required=True)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "package":
            package_results(args.output, args.archive)
            return 0
        if args.max_frames is not None and args.max_frames < 1:
            raise ValueError("--max-frames must be positive")
        config, cities = load_config(args.config), load_cities(args.cities)
        if not 1 <= len(cities) <= 10:
            raise ValueError("The supplied panel layout supports1–10 cities")
        if args.command == "inspect":
            return inspect_data(args, config, cities)
        if args.command == "watch" and (args.poll_seconds < 1 or args.idle_minutes <= 0):
            raise ValueError("Use positive idle minutes and a poll interval of at least one second")
        with OutputLock(Path(args.output).expanduser().resolve()):
            last_selection, last_change = None, time.monotonic()
            while True:
                status, selection = process_available(args, config, cities)
                if args.command == "run":
                    return 1 if status["errors"] or not status["processed_records"] else 0
                if selection != last_selection:
                    last_change = time.monotonic()
                    last_selection = selection
                if status["source_complete"] is True and not status["errors"]:
                    if status.get("completion_scope") == "selected_cases":
                        print("Selected group data are complete and every selected record was processed.")
                    else:
                        print("Source manifest is complete and every selected record was processed.")
                    return 0
                if (time.monotonic() - last_change) / 60 >= args.idle_minutes:
                    print("Idle limit reached. Partial results saved; rerun watch to continue.")
                    return 0
                print("Waiting for newly completed files (Ctrl+C stops safely)...", flush=True)
                time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        print("\nStopped. Completed figures are saved; rerun to resume.")
        return 130
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2


def plot_profile_gifs(out, caches, cities, fields, config):
    """Each GIF compares available experiments at the same actual timestamp."""
    records = [c for c in caches if c["mode"] == "full"]
    if not records:
        return []
    cases = sorted({c["case"] for c in records})
    lookup = {(c["case"], c["time"]): c for c in records}
    shared = sorted(set.intersection(*(set(c["time"] for c in records if c["case"] == case) for case in cases)))
    outputs = []
    for field in [f for f in fields if f in VERTICAL_FIELDS]:
        spec = config["fields"][field]
        all_values = [v for c in records for city in c["cities"].values() for v in city.get("display_profiles", {}).get(field, []) if v is not None]
        lo, hi = min([spec["range"][0]] + all_values), max([spec["range"][1]] + all_values)
        frames = []
        for time_text in shared:
            fig, axes = plt.subplots(2, 5, figsize=(15, 7.8), dpi=config["map_dpi"])
            fig.subplots_adjust(left=.06, right=.98, bottom=.12, top=.81, hspace=.38, wspace=.33)
            handles = {}
            for ax, city in zip(axes.ravel(), cities):
                used = False
                for idx, case in enumerate(cases):
                    entry = lookup[(case, time_text)]["cities"].get(city["slug"], {})
                    values, heights = entry.get("display_profiles", {}).get(field, []), entry.get("height_agl")
                    if heights is None or len(values) != len(heights) or len(values) < 2:
                        continue
                    values, heights = np.asarray(values, dtype=float), np.asarray(heights, dtype=float)/1000
                    h, = ax.plot(values, heights, lw=1.7, color=CASE_COLORS[idx % len(CASE_COLORS)], label=case)
                    handles[case] = h
                    used = True
                ax.set_title("%d %s" % (city["rank"], city["name"]), loc="left", fontsize=10)
                ax.set(xlim=(lo, hi), ylim=(0, config["max_plot_height_m"]/1000), xlabel=spec["unit"], ylabel="Height AGL (km)")
                ax.tick_params(labelsize=8)
                ax.grid(alpha=.2)
                if not used:
                    ax.text(.5, .5, "No physical-height\nprofile", transform=ax.transAxes, ha="center", fontsize=9)
            for ax in axes.ravel()[len(cities):]:
                ax.set_visible(False)
            fig.text(.06, .95, spec["title"] + " · vertical profiles", fontsize=17, weight="bold", color="#173e51")
            fig.text(.06, .91, time_text.replace("T", " ") + " UTC · full subset · paired timestamps across available experiments", fontsize=10)
            if handles:
                fig.legend(list(handles.values()), list(handles), loc="upper left", bbox_to_anchor=(.055, .891), ncol=len(cases), frameon=False)
            fig.text(.06, .035, "Native model-level profiles; no profiles manufactured for the 14 surface diagnostics. City points use nearest in-domain cells.", fontsize=9)
            if any(lookup[(case, time_text)]["synthetic"] for case in cases):
                fig.text(.98, .95, "SYNTHETIC DEMO", ha="right", color="#aa3344", fontsize=10, weight="bold")
            frame = out / ".cache" / "profiles" / field / (time_text.replace(":", "-") + ".png")
            save_figure(fig, frame)
            frames.append(frame)
        destination = out / "profile_animations" / (field + ".gif")
        make_gif(frames, destination, config["gif_frame_ms"])
        if frames:
            outputs.append(destination)
    return outputs


if __name__ == "__main__":
    raise SystemExit(main())

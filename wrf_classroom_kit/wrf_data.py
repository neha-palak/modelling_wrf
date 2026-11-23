"""Read completed WRF Lite snapshots without inventing missing information.

All returned field values retain the source units. netCDF4 decodes packed data,
fill values and masks; only the vertical coordinate helpers perform physical
conversions. A surface snapshot still has one atmospheric layer, not a profile.
Times are WRF simulation times, conventionally UTC, represented by naive UTC
datetime objects. No source is opened for writing.

Public API: scan_roots, read_surface, read_city_columns, rain_increment.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
import re

import numpy as np
from netCDF4 import Dataset
from matplotlib.path import Path as PolygonPath

PRIMARY_FIELDS = [
    "T2", "Q2", "PSFC", "U10", "V10", "TSK", "PBLH", "HFX", "LH",
    "SWDOWN", "GLW", "RAINC", "RAINNC", "GRDFLX", "PM2_5_DRY", "PM10",
    "TOT_DUST", "BC1", "so2", "OC1",
]
VERTICAL_FIELDS = ["PM2_5_DRY", "PM10", "TOT_DUST", "BC1", "so2", "OC1"]
DEFAULT_CASES = ["01_CTRL", "02_CTRL_NOISE", "03_CLEAN"]
TIME_FORMAT = "%Y-%m-%d_%H:%M:%S"
GRAVITY = 9.81  # WRF users' guide geopotential-height convention, m s-2.


@dataclass(frozen=True)
class Record:
    path: Path
    case: str
    mode: str
    time: datetime
    size: int
    signature: str
    synthetic: bool = False
    time_index: int = 0


class DataError(ValueError):
    """An input cannot be interpreted without an unsupported assumption."""


def _json_value(value):
    if isinstance(value, np.ndarray):
        return [_json_value(x) for x in value.tolist()]
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def parse_time(text):
    text = str(text).strip("\x00 ").replace("_", "T")
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DataError("Invalid WRF Times value: %r" % text) from exc
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(timezone.utc).replace(tzinfo=None)
    return stamp


def _times(ds):
    if "Times" not in ds.variables:
        raise DataError("Times variable is missing; filenames are not used as scientific timestamps.")
    var = ds.variables["Times"]
    var.set_auto_chartostring(False)
    raw = var[:]
    if raw.ndim == 1 and raw.dtype.kind in "SU" and "DateStrLen" in var.dimensions:
        raw = raw[None, :]
    result = []
    for row in raw:
        a = np.asarray(row)
        if a.dtype.kind == "S":
            value = a.tobytes().decode("ascii")
        elif a.dtype.kind == "U":
            value = "".join(a.reshape(-1).tolist())
        else:
            value = str(row)
        result.append(parse_time(value))
    if not result:
        raise DataError("Times contains no records.")
    return result


def _numeric(var, index):
    # Keep netCDF4 automatic decoding ON, including _Unsigned and scale/offset.
    value = np.ma.asarray(var[index], dtype=np.float64)
    return np.ma.masked_invalid(value)


def _plane(var, time_index, lowest=True):
    indices, remaining = [], []
    for dim, length in zip(var.dimensions, var.shape):
        if dim == "Time":
            indices.append(time_index)
        elif dim in ("bottom_top", "bottom_top_stag") and lowest:
            indices.append(0)
        elif dim in ("south_north", "west_east"):
            indices.append(slice(None))
            remaining.append(dim)
        elif length == 1:
            indices.append(0)
        else:
            raise DataError("Unsupported map dimension %s on %s" % (dim, var.name))
    data = _numeric(var, tuple(indices))
    if remaining == ["west_east", "south_north"]:
        data = data.T
    elif remaining != ["south_north", "west_east"]:
        raise DataError("%s is not a mass-grid map: %s" % (var.name, var.dimensions))
    return data


def _column(var, time_index, row, col):
    indices, remaining = [], []
    for dim, length in zip(var.dimensions, var.shape):
        if dim == "Time":
            indices.append(time_index)
        elif dim == "south_north":
            indices.append(row)
        elif dim == "west_east":
            indices.append(col)
        elif dim in ("bottom_top", "bottom_top_stag"):
            indices.append(slice(None))
            remaining.append(dim)
        elif length == 1:
            indices.append(0)
        else:
            raise DataError("Unsupported column dimension %s on %s" % (dim, var.name))
    if len(remaining) > 1:
        raise DataError("Multiple vertical dimensions on " + var.name)
    return _numeric(var, tuple(indices))


def _attrs(ds):
    names = ["DX", "DY", "MAP_PROJ", "MAP_PROJ_CHAR", "TRUELAT1", "TRUELAT2",
             "STAND_LON", "CEN_LAT", "CEN_LON", "wrflite_vertical",
             "wrflite_interval_hours", "wrflite_config_hash", "TITLE",
             "SIMULATION_START_DATE", "START_DATE", "bucket_mm", "BUCKET_MM",
             "wrf_classroom_synthetic", "classroom_synthetic"]
    return {name: _json_value(ds.getncattr(name)) for name in names if name in ds.ncattrs()}


def _mode(ds):
    value = str(getattr(ds, "wrflite_vertical", "")).lower()
    if value in ("full", "surface"):
        return value
    return "full" if "bottom_top" in ds.dimensions and len(ds.dimensions["bottom_top"]) > 1 else "surface"


def _case(path, metadata=None):
    if metadata and isinstance(metadata.get("case"), str):
        case = metadata["case"]
    else:
        case = next((part for part in reversed(path.parts) if part in DEFAULT_CASES), path.parent.name)
    if case in ("", ".", "..") or "/" in case or "\\" in case:
        raise DataError("Invalid experiment name: %r" % case)
    return case


def _synthetic(ds):
    return ("SYNTHETIC" in str(getattr(ds, "TITLE", "")).upper()
            or str(getattr(ds, "classroom_synthetic", "")).lower() in ("1", "true", "yes")
            or str(getattr(ds, "wrf_classroom_synthetic", "")).lower() in ("1", "true", "yes"))


def _read_records(path, metadata=None):
    before = path.stat()
    if metadata is not None and int(metadata.get("bytes", -1)) != before.st_size:
        raise DataError("file size does not yet match the conversion manifest")
    with Dataset(path, "r") as ds:
        if "XLAT" not in ds.variables or "XLONG" not in ds.variables:
            raise DataError("XLAT/XLONG coordinates are missing")
        times = _times(ds)
        if metadata and metadata.get("time"):
            if len(times) != 1 or times[0] != parse_time(metadata["time"]):
                raise DataError("Times does not match the conversion manifest")
        mode, synthetic = _mode(ds), _synthetic(ds)
        config_hash = str(getattr(ds, "wrflite_config_hash", ""))
        payload_hash = str(getattr(ds, "wrflite_payload_sha256", ""))
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise DataError("file changed while its header was being read")
    case = _case(path, metadata)
    identity = "%s|%s|%s|%s|%s" % (path.resolve(), before.st_size, before.st_mtime_ns, config_hash, payload_hash)
    return [Record(path, case, mode, stamp, before.st_size,
                   hashlib.sha256((identity + "|" + str(i)).encode()).hexdigest(), synthetic, i)
            for i, stamp in enumerate(times)]


def _safe_member(root, relative):
    if not isinstance(relative, str) or "\\" in relative:
        raise DataError("Invalid manifest filename")
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise DataError("Manifest filename escapes its data directory") from exc
    if path.suffix.lower() != ".nc" or ".part" in path.name or ".tmp" in path.name:
        raise DataError("Manifest entry is not a completed .nc file")
    return path


def scan_roots(roots, config=None):
    """Discover ready records, prioritizing the converter's atomic manifest.

    Returns (records, warnings, status). Both full and surface roots may be
    supplied. Manifest-listed file sizes must agree. Duplicate case/mode/time
    records are excluded and reported, never silently chosen. Standalone .nc
    files are accepted but completion is unknown; use atomic .part->.nc copies.
    The source manifest's complete flag alone does not mean the local copy is
    complete. No recursive directory symlinks are followed by Path.rglob.
    """
    config = config or {}
    warnings, records, manifests, visited = [], [], [], set()
    deferred = 0
    standalone = 0
    covered_roots = []
    input_roots = []
    for raw in roots:
        root = Path(raw).expanduser().resolve()
        if root not in input_roots:
            input_roots.append(root)
    for root in input_roots:
        if not root.exists():
            warnings.append("Waiting for data directory: " + str(root))
            deferred += 1
            continue
        if root.is_file():
            candidates = []
        else:
            candidates = sorted(root.rglob("manifest.json"))
        for manifest_path in candidates:
            manifest_path = manifest_path.resolve()
            if manifest_path in visited:
                continue
            visited.add(manifest_path)
            covered_roots.append(manifest_path.parent)
            entry = {"path": str(manifest_path), "complete": False, "planned_files": 0,
                     "listed_files": 0, "local_ready_files": 0}
            manifests.append(entry)
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                members = manifest.get("files", {})
                if not isinstance(members, dict):
                    raise DataError("manifest files must be a mapping")
                entry.update(complete=bool(manifest.get("complete", False)),
                             planned_files=int(manifest.get("planned_files", len(members))),
                             listed_files=len(members))
                scope = manifest.get("classroom_scope")
                if isinstance(scope, dict) and scope.get("kind") == "selected_cases":
                    selected = scope.get("selected_cases", [])
                    if (not isinstance(selected, list) or not selected
                            or not all(isinstance(case, str) and case for case in selected)
                            or len(set(selected)) != len(selected)):
                        raise DataError("Selected-group manifest needs a unique nonempty selected_cases list")
                    if any(not isinstance(meta, dict) or meta.get("case") not in selected
                           for meta in members.values()):
                        raise DataError("Selected-group manifest contains an unselected experiment")
                    entry["classroom_scope"] = scope
                    entry["selected_cases"] = list(selected)
                    # Completion describes the assigned groups, not a locally
                    # reconstructed three-experiment conversion. A partial or
                    # unverified parent cannot establish completed conversion.
                    if scope.get("parent_complete") is not True:
                        entry["complete"] = False
                        warnings.append("Selected-group manifest does not establish parent conversion completion: "
                                        + str(manifest_path))
                for relative, meta in members.items():
                    try:
                        if not isinstance(meta, dict):
                            raise DataError("invalid record metadata")
                        path = _safe_member(manifest_path.parent, relative)
                        if path in visited:
                            continue
                        # Mark only after a successful read: overlapping partial
                        # manifests must not hide an otherwise ready file.
                        items = _read_records(path, meta)
                        records.extend(items)
                        visited.add(path)
                        entry["local_ready_files"] += 1
                    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
                        deferred += 1
                        warnings.append("Waiting/skipping %s: %s" % (relative, exc))
            except (OSError, RuntimeError, ValueError, TypeError) as exc:
                deferred += 1
                warnings.append("Cannot yet read %s: %s" % (manifest_path, exc))

    # A root can include several datasets, each with its own manifest. Files
    # outside every manifest subtree are standalone completed snapshots.
    for root in input_roots:
        if not root.exists():
            continue
        paths = [root] if root.is_file() else sorted(root.rglob("*.nc"))
        for path in paths:
            path = path.resolve()
            if path in visited or ".part" in path.name or ".tmp" in path.name:
                continue
            if any(path.is_relative_to(parent) for parent in covered_roots):
                # Never race an atomic converter by reading an unlisted file.
                continue
            if path.suffix.lower() != ".nc":
                continue
            try:
                records.extend(_read_records(path))
                visited.add(path)
                standalone += 1
            except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
                deferred += 1
                warnings.append("Waiting/skipping %s: %s" % (path, exc))
    if standalone:
        warnings.append("Standalone NetCDF files have no conversion manifest. Supply only completed files; "
                        "copy to .part and rename to .nc after transfer. Overall conversion completion is unknown.")
    groups = {}
    for record in records:
        groups.setdefault((record.case, record.mode, record.time), []).append(record)
    result = []
    duplicates = 0
    for key, values in groups.items():
        if len(values) > 1:
            duplicates += len(values)
            warnings.append("Ambiguous duplicate case/mode/time %s; all %d copies excluded. Select one dataset root."
                            % (key, len(values)))
        else:
            result.append(values[0])
    result.sort(key=lambda x: (x.mode, x.case, x.time, str(x.path)))
    complete = (all(m["complete"] and m["local_ready_files"] == m["listed_files"]
                    and m["listed_files"] == m["planned_files"] for m in manifests)
                and not deferred and not duplicates) if manifests and not standalone else None
    scope_cases = sorted({case for manifest in manifests for case in manifest.get("selected_cases", [])})
    return result, warnings, {"ready_files": len({r.path for r in result}), "ready_records": len(result),
                              "deferred_files": deferred, "duplicate_records": duplicates,
                              "standalone_files": standalone, "manifests": manifests,
                              "complete": complete,
                              "completion_scope": "selected_cases" if scope_cases else "manifest_dataset",
                              "scope_cases": scope_cases}


def read_surface(record, fields=None):
    """Read mass-grid maps in source units; 3D fields use the lowest model layer.

    Missing requested fields are omitted with warnings rather than invented.
    Returned data are masked floating arrays. Also supplies unmodified bucket
    counters, rotation coefficients and source attributes for diagnostics.
    """
    fields = PRIMARY_FIELDS if fields is None else fields
    values, units, dimensions, warnings = {}, {}, {}, []
    with Dataset(record.path, "r") as ds:
        lat = _plane(ds.variables["XLAT"], record.time_index)
        lon = _plane(ds.variables["XLONG"], record.time_index)
        for name in fields:
            if name not in ds.variables:
                warnings.append("Missing field " + name)
                continue
            var = ds.variables[name]
            try:
                value = _plane(var, record.time_index)
                if value.shape != lat.shape:
                    raise DataError("Map shape does not match coordinates")
                values[name] = value
                units[name] = str(getattr(var, "units", ""))
                dimensions[name] = tuple(var.dimensions)
            except (DataError, RuntimeError) as exc:
                warnings.append("%s: %s" % (name, exc))
        def optional(name):
            return _plane(ds.variables[name], record.time_index) if name in ds.variables else None
        return {"lat": lat, "lon": lon, "fields": values, "units": units,
                "field_dimensions": dimensions, "attrs": _attrs(ds),
                "counters": {name: optional(name) for name in ("I_RAINC", "I_RAINNC") if name in ds.variables},
                "terrain": optional("HGT"), "cosalpha": optional("COSALPHA"),
                "sinalpha": optional("SINALPHA"), "warnings": warnings}


def _boundary(lat, lon):
    if min(lat.shape) < 2:
        raise DataError("A city cannot be placed inside a grid with fewer than two rows or columns")
    ys = np.ma.concatenate([lat[0, :], lat[1:, -1], lat[-1, -2::-1], lat[-2:0:-1, 0]])
    xs = np.ma.concatenate([lon[0, :], lon[1:, -1], lon[-1, -2::-1], lon[-2:0:-1, 0]])
    if np.ma.getmaskarray(ys).any() or np.ma.getmaskarray(xs).any():
        raise DataError("Grid boundary contains missing coordinates; city coverage cannot be verified")
    center = float(np.ma.median(lon))
    xs = center + (np.asarray(xs) - center + 180.0) % 360.0 - 180.0
    vertices = np.column_stack([xs, np.asarray(ys)])
    # Explicit closing vertex; matplotlib Path(closed=True) otherwise discards
    # the final supplied vertex when it is used as the CLOSEPOLY placeholder.
    vertices = np.vstack([vertices, vertices[0]])
    return PolygonPath(vertices, closed=True), center


def _distance_km(lat, lon, city_lat, city_lon):
    lat1, lat2 = np.radians(lat), math.radians(city_lat)
    dlat = lat1 - lat2
    dlon = np.radians((lon - city_lon + 180.0) % 360.0 - 180.0)
    a = np.sin(dlat / 2.0)**2 + np.cos(lat1) * math.cos(lat2) * np.sin(dlon / 2.0)**2
    return 6371.0088 * 2.0 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _scalar(value):
    value = np.ma.asarray(value).reshape(-1)
    if not len(value) or np.ma.is_masked(value[0]):
        return None
    number = float(value[0])
    return number if math.isfinite(number) else None


def _unit_key(var):
    return str(getattr(var, "units", "")).lower().replace(" ", "").replace("^", "").replace("**", "")


def read_city_columns(record, cities):
    """Read nearest mass-grid cell inside the model perimeter for each city.

    cities: dictionaries with slug (optional), name, lat and lon. Grid-cell
    values are model samples, not observations or city-wide averages. Physical
    height uses interface geopotential -> mass-level midpoint -> height above
    terrain. P+PB is returned in hPa only when both source units are Pa.
    """
    result = {}
    with Dataset(record.path, "r") as ds:
        lat = _plane(ds.variables["XLAT"], record.time_index)
        lon = _plane(ds.variables["XLONG"], record.time_index)
        boundary, center = _boundary(lat, lon)
        attrs = _attrs(ds)
        for city in cities:
            name = str(city.get("name", city.get("city", city.get("slug", "city"))))
            slug = str(city.get("slug", re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")))
            city_lat = float(city.get("lat", city.get("latitude")))
            city_lon = float(city.get("lon", city.get("longitude")))
            shifted_lon = center + (city_lon - center + 180.0) % 360.0 - 180.0
            inside = bool(boundary.contains_point((shifted_lon, city_lat), radius=1e-9))
            entry = {"name": name, "slug": slug, "lat": city_lat, "lon": city_lon,
                     "status": "ready" if inside else "outside_domain", "inside": inside,
                     "row": None, "col": None, "grid_lat": None, "grid_lon": None,
                     "distance_km": None, "values": {}, "profiles": {}, "units": {},
                     "height_agl": None, "pressure_hpa": None, "counters": {},
                     "attrs": attrs, "warnings": [], "vertical_levels": 0}
            result[slug] = entry
            if not inside:
                entry["warnings"].append("City center is outside the grid-center perimeter; no nearest-edge value substituted.")
                continue
            distance = np.ma.masked_invalid(_distance_km(lat, lon, city_lat, city_lon))
            distance.mask = np.ma.getmaskarray(distance) | np.ma.getmaskarray(lat) | np.ma.getmaskarray(lon)
            if distance.count() == 0:
                entry["status"] = "missing_coordinates"
                entry["inside"] = False
                continue
            row, col = np.unravel_index(int(distance.argmin()), distance.shape)
            entry.update(row=int(row), col=int(col), grid_lat=float(lat[row, col]),
                         grid_lon=float(lon[row, col]), distance_km=float(distance[row, col]))
            for field in PRIMARY_FIELDS:
                if field not in ds.variables:
                    entry["warnings"].append("Missing field " + field)
                    continue
                var = ds.variables[field]
                data = _column(var, record.time_index, row, col)
                entry["units"][field] = str(getattr(var, "units", ""))
                entry["values"][field] = _scalar(data)
                if "bottom_top" in var.dimensions:
                    profile = np.ma.asarray(data).reshape(-1)
                    entry["profiles"][field] = profile
                    entry["vertical_levels"] = max(entry["vertical_levels"], len(profile))
            for name in ("I_RAINC", "I_RAINNC"):
                if name in ds.variables:
                    entry["counters"][name] = _scalar(_column(ds.variables[name], record.time_index, row, col))
            if all(n in ds.variables for n in ("PH", "PHB", "HGT")):
                units_ok = all(_unit_key(ds.variables[n]) in ("m2s-2", "m2/s2") for n in ("PH", "PHB"))
                units_ok = units_ok and _unit_key(ds.variables["HGT"]) in ("m", "meter", "meters", "metre", "metres")
                if units_ok:
                    interfaces = (_column(ds.variables["PH"], record.time_index, row, col)
                                  + _column(ds.variables["PHB"], record.time_index, row, col)) / GRAVITY
                    terrain = _column(ds.variables["HGT"], record.time_index, row, col)
                    if interfaces.ndim == 1 and len(interfaces) >= 2:
                        entry["height_agl"] = (interfaces[:-1] + interfaces[1:]) / 2.0 - terrain
                        if entry["vertical_levels"] and len(entry["height_agl"]) != entry["vertical_levels"]:
                            entry["warnings"].append("Height/profile level counts disagree; height unavailable.")
                            entry["height_agl"] = None
                else:
                    entry["warnings"].append("Unexpected geopotential/terrain units; physical height unavailable.")
            else:
                entry["warnings"].append("PH, PHB or HGT missing; use model-level index, not invented heights.")
            if all(n in ds.variables for n in ("P", "PB")):
                if all(_unit_key(ds.variables[n]) in ("pa", "pascal", "pascals") for n in ("P", "PB")):
                    entry["pressure_hpa"] = (_column(ds.variables["P"], record.time_index, row, col)
                                             + _column(ds.variables["PB"], record.time_index, row, col)) / 100.0
                else:
                    entry["warnings"].append("Unexpected P/PB units; pressure unavailable.")
    return result


def rain_increment(prev, cur, hours, bucket_mm=None, prev_counters=None, cur_counters=None):
    """Return interval-average rain rate and a quality summary.

    Inputs are accumulated millimetres for one component, or a properly
    reconstructed total. Supply corresponding bucket counters separately when
    present. An unknown bucket increment, counter reset, accumulation
    reset or nonpositive time interval invalidates the affected value; never
    interpret a reset as dry weather. This does not reconstruct hourly peaks.
    """
    previous = np.ma.masked_invalid(np.ma.asarray(prev, dtype=np.float64))
    current = np.ma.masked_invalid(np.ma.asarray(cur, dtype=np.float64))
    if previous.shape != current.shape:
        raise DataError("Rain arrays have different shapes")
    shape = current.shape
    quality = {"hours": float(hours), "negative_resets": 0, "unknown_bucket": 0,
               "counter_resets": 0, "invalid_values": 0, "status": "ok"}
    if not math.isfinite(float(hours)) or hours <= 0:
        quality.update(status="invalid_interval", invalid_values=int(current.size))
        return np.ma.masked_all(shape, dtype=np.float64), quality
    bad = np.ma.getmaskarray(previous) | np.ma.getmaskarray(current)
    delta = np.ma.filled(current, np.nan) - np.ma.filled(previous, np.nan)
    counter_given = prev_counters is not None or cur_counters is not None
    if not counter_given and bucket_mm is not None and float(bucket_mm) > 0:
        quality.update(status="missing_counter", invalid_values=int(current.size))
        return np.ma.masked_all(shape, dtype=np.float64), quality
    if counter_given:
        if prev_counters is None or cur_counters is None:
            quality.update(status="missing_counter", invalid_values=int(current.size))
            return np.ma.masked_all(shape, dtype=np.float64), quality
        pc = np.ma.masked_invalid(np.ma.asarray(prev_counters, dtype=np.float64))
        cc = np.ma.masked_invalid(np.ma.asarray(cur_counters, dtype=np.float64))
        if pc.shape != shape or cc.shape != shape:
            raise DataError("Rain counter shape does not match accumulated rain")
        pcv, ccv = np.ma.filled(pc, np.nan), np.ma.filled(cc, np.nan)
        bad |= np.ma.getmaskarray(pc) | np.ma.getmaskarray(cc)
        invalid_counter = (pcv < 0) | (ccv < 0) | (pcv != np.floor(pcv)) | (ccv != np.floor(ccv))
        bad |= invalid_counter
        resets = ccv < pcv
        quality["counter_resets"] = int(np.count_nonzero(resets))
        bad |= resets
        if bucket_mm is not None and math.isfinite(float(bucket_mm)) and float(bucket_mm) > 0:
            delta += float(bucket_mm) * (ccv - pcv)
        else:
            # Unchanged positive counters cancel exactly; their unknown bucket
            # size is unnecessary for a difference. Changed counters do not.
            unknown = ccv != pcv
            quality["unknown_bucket"] = int(np.count_nonzero(unknown & ~bad))
            bad |= unknown
    # Tiny arithmetic differences from storage precision are tolerated only at
    # a fixed 1e-5 mm scale; ordinary negative increments stay invalid.
    resets = delta < -1e-5
    quality["negative_resets"] = int(np.count_nonzero(resets & ~bad))
    bad |= resets | ~np.isfinite(delta)
    tiny = (delta < 0) & (delta >= -1e-5)
    delta = np.where(tiny, 0.0, delta)
    result = np.ma.array(delta / float(hours), mask=bad)
    quality["invalid_values"] = int(np.count_nonzero(bad))
    if quality["invalid_values"]:
        quality["status"] = "partly_invalid" if result.count() else "invalid"
    return result, quality

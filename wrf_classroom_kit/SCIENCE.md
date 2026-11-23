# How to interpret the classroom figures

This kit visualizes selected WRF-Chem output. Its input files remain the scientific record; figures summarize that record. The instructor's inspected files begin on **22 June 2023**, so these are historical simulation results, not today's forecast. Always use the actual NetCDF timestamps and configured time convention when interpreting plots.

Primary references and population/coordinate provenance are in [SOURCES.md](SOURCES.md). The variable units and array shapes below come from the instructor's posted NetCDF inspection. Check actual metadata whenever using a different simulation.

## Twenty retained fields

There are **14 surface fields and 6 atmospheric fields**. All twenty can produce horizontal maps and city time series. Only the six atmospheric fields can provide vertical profiles when the input retains multiple levels. Support variables such as latitude, longitude, terrain, pressure and geopotential are additional metadata/arrays; they are not counted among the twenty teaching fields.

| Field | Meaning | Observed native units | Plot units | Default display range |
|---|---|---|---|---|
| `T2` | Air temperature at 2 m | K | degrees C | -10 to 50 |
| `Q2` | Water-vapor mixing ratio at 2 m | kg kg-1 | g kg-1 | 0 to 25 |
| `PSFC` | Surface pressure | Pa | hPa | 450 to 1050 |
| `U10` | 10 m grid-relative x wind component | m s-1 | m s-1 | -25 to 25 |
| `V10` | 10 m grid-relative y wind component | m s-1 | m s-1 | -25 to 25 |
| `TSK` | Surface skin temperature | K | degrees C | -10 to 65 |
| `PBLH` | Diagnosed boundary-layer height | m | m | 0 to 4000 |
| `HFX` | Surface sensible heat flux | W m-2 | W m-2 | -100 to 500 |
| `LH` | Surface latent heat flux | W m-2 | W m-2 | -100 to 600 |
| `SWDOWN` | Downward surface shortwave radiation | W m-2 | W m-2 | 0 to 1100 |
| `GLW` | Downward surface longwave radiation | W m-2 | W m-2 | 150 to 550 |
| `RAINC` | Accumulated parameterized-convective precipitation | mm | mm | 0 to 200 |
| `RAINNC` | Accumulated grid-scale precipitation | mm | mm | 0 to 300 |
| `GRDFLX` | Ground heat flux | W m-2 | W m-2 | -200 to 200 |
| `PM2_5_DRY` | Dry PM2.5 mass concentration | ug m^-3 | micrograms m-3 | 0 to 400 |
| `PM10` | PM10 mass concentration | ug m^-3 | micrograms m-3 | 0 to 600 |
| `TOT_DUST` | Total dust mass concentration diagnostic | ug m^-3 | micrograms m-3 | 0 to 500 |
| `BC1` | Retained black-carbon component | ug/kg-dryair | micrograms kg-1 dry air | 0 to 30 |
| `so2` | Sulfur-dioxide volume mixing ratio | ppmv | ppbv | 0 to 50 |
| `OC1` | Retained organic-carbon component | ug/kg-dryair | micrograms kg-1 dry air | 0 to 50 |

The final six rows have a vertical atmospheric dimension in the full source files. The source inspection reported 39 mass levels, but the software reads the actual level count rather than assuming every input has 39.

### Units and component meaning

- Temperature: degrees C = K - 273.15. Mixing ratio `Q2`: g/kg = 1000 times kg/kg. Pressure: hPa = Pa / 100. These transformations require compatible source units.
- `Q2` is **not relative humidity**. Surface pressure is **not mean sea-level pressure**, which is especially relevant over the Himalayas.
- `so2`: ppbv = 1000 times ppmv. For example, 0.002 ppmv is 2 ppbv. This is a volume mixing ratio conversion; it does not make a mass concentration in micrograms/m3.
- `BC1` and `OC1` remain in micrograms per kilogram of dry air. They must not be presented as micrograms/m3. Such a conversion needs compatible dry-air density, which this kit does not assume. The selected variables are individual chemistry components, not total black carbon or total organic carbon. Availability of `BC2`/`OC2` in an original file does not mean they are present in the reduced product.
- PM2.5, PM10 and total dust diagnostics overlap in composition/size classes; do not add them together as independent pollutant masses.
- Flux signs follow the native WRF conventions. Preserve positive and negative values; consult the source land-surface scheme before constructing a surface energy budget from these fields.

## Surface files versus full vertical files

In both modes the native `T2`, `Q2`, `U10` and `V10` retain their diagnostic heights and meanings. A surface map of a vertically resolved pollutant uses the **lowest model mass layer**. Its height varies with terrain and the vertical grid; it is not automatically a concentration at exactly 2 m or 10 m.

The **full** subset can retain all available levels for `PM2_5_DRY`, `PM10`, `TOT_DUST`, `BC1`, `so2` and `OC1`. These permit city-column profiles and time-height/three-dimensional visualizations. The fourteen surface fields have no atmospheric vertical profile in this dataset. Drawing a three-dimensional surface of one of those fields would only change presentation, not create vertical information.

The **surface** subset keeps one mass layer of each atmospheric field. One layer cannot recover a vertical column, elevated plume, column total or atmospheric cross-section. Use the full product for those exercises. A visible level dimension of length one does not make a meaningful multi-level vertical profile.

### Height and pressure

When `PH`, `PHB` and `HGT` exist with compatible units, physical mass-level height above model terrain is computed as follows:

```text
interface_geopotential_height_m = (PH + PHB) / 9.81
mass_height_m = 0.5 * (interface_height[k] + interface_height[k+1])
height_above_ground_m = mass_height_m - HGT
```

`PH` and `PHB` are on staggered vertical interfaces; one needs two bounding interfaces for every mass layer. The gravitational acceleration here is **9.81 m/s2**, following the WRF guide convention. A figure labeled km AGL divides the result by 1000. AGL means above **model terrain**, whose resolution differs from a street-level altitude.

When `P` and `PB` are both present in Pa, full pressure is `(P + PB) / 100` hPa. `P` by itself is a perturbation, not the total pressure. If the necessary height support is missing or incompatible, the honest alternative is **model-level index**, not an invented height axis. Keeping support fields in the full conversion enables physical-coordinate plots, but their presence is checked rather than assumed.

## Precipitation: accumulations and interval-average rates

`RAINC` and `RAINNC` are accumulated fields. Their native maps are useful but are not hourly intensity maps. Additional derived products show each component's rate and their combined rate:

```text
total_accumulation = RAINC + RAINNC
interval_average_rate_mm_per_hour =
    (accumulation_at_end - accumulation_at_start) / elapsed_hours
```

With regularly spaced three-hour input, this is the **average rate over the preceding three hours**. Dividing by three does not reveal actual hourly or sub-hourly peaks. The first available snapshot has no preceding interval in the supplied record and therefore has no derived rate. Across a missing timestamp, the elapsed interval must remain explicit; do not silently describe a six-hour average as three-hour rain.

Accumulation resets and missing data require quality flags/masking, not replacement by zero. If the simulation uses WRF precipitation buckets, reconstruct changes using `I_RAINC`/`I_RAINNC` and the correct `bucket_mm` when available. An unknown bucket increment cannot be guessed. A restart can also invalidate differences even if filenames are consecutive. Keep an eye on quality warnings and the source simulation history.

The rate legend has **seven intervals** with these eight boundaries:

```text
0, 0.1, 0.5, 1, 2, 5, 10, 15 mm/hour
```

The intervals are chosen for readable teaching plots. They are not IMD daily-rainfall classifications. Values above 15 need a visible over-range indication rather than silent clipping. Native `RAINC` and `RAINNC` retain their accumulated-mm displays separately.

## Wind interpretation

The derived 10 m wind-speed magnitude is `sqrt(U10**2 + V10**2)` and has a default 0-25 m/s display range. The magnitude is unchanged by a horizontal coordinate rotation. Native component plots remain **grid-relative** unless an explicitly documented earth-coordinate rotation is performed using compatible `COSALPHA` and `SINALPHA`. Do not call raw grid components eastward/northward winds simply because the map is drawn in longitude/latitude.

The chosen range does not define a severe-weather category. IMD's cyclone categories use maximum sustained three-minute surface winds: severe starts at 48 knots (about 24.7 m/s) and very severe at 64 knots (about 32.9 m/s). A model snapshot also has a different sampling/averaging meaning. Keep over-range indicators for winds above 25 m/s.

## Fixed legends, AQI, and comparisons

The display ranges are fixed teaching defaults shared across cases and timestamps so that changing colors do not merely reflect autoscaling. They are **not validated Indian climatological limits, safety thresholds, or guaranteed bounds**. Season, terrain, chemistry and unusual events can put values outside them. Count/show over-range values and retain the numerical values in CSV exports. A color limit must not alter stored concentrations.

The PM2.5 legend is a concentration legend, **not CPCB AQI**. CPCB's PM2.5 sub-index uses a 24-hour average and data completeness criteria; three-hour model snapshots at the lowest model layer are not an official air-quality observation. `so2` ppbv is likewise not a regulatory SO2 mass-concentration index. This kit does not diagnose exposure or compliance.

Compare experiments only at matching timestamps and compatible grids/points. An experiment difference at a time that exists in only one case is not meaningful. Sparse snapshots represent samples, not a continuous record or validated diurnal average.

## City selection and geographic coverage

`cities.csv` selects the ten largest **urban agglomerations and standalone cities from Census 2011 Table A-04(I)**. Jaipur is the standalone municipal-corporation entry; the other nine are urban agglomerations. The population figures are not estimates for 2026.

The coordinates are explicit representative points: nine IMD reference-station positions and the Surat district government's published city location. They are not urban-area centroids or population-weighted pollution locations. Read the actual selected grid position and distance alongside a city time series. One grid cell can cover many neighborhoods, and a coastal cell can include sea. The source model resolution and land mask determine that representativeness; the plotting kit cannot create street-scale information.

An India-region plot uses the input domain and geographic plotting extent. A dataset that does not cover a city cannot supply its forecast. Do not stretch the data to cover all India or substitute another distant grid point without a clear warning.

The bundled Natural Earth coastline is a coarse public-domain context layer. No administrative borders are drawn. The plotted rectangle can include neighboring countries and ocean; it is not a national-boundary mask.

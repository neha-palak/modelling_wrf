# Sources and provenance

Prepared 18 November 2026. This kit uses the instructor's reported NetCDF headers, official population tables, and primary scientific documentation. Plot ranges are teaching choices; no source below establishes them as validated national climatological limits.

## The supplied simulations

The instructor inspected sample history files in `01_CTRL`, `02_CTRL_NOISE`, and `03_CLEAN` under `/storage/neha.palak_ug2023/wrfchem/MSA_CANDIDATE_V1/134061.master`. The reported first timestamp is **2023-06-22 00:00:00**, with 41 discovered files per case, a 399 by 399 horizontal grid, and 39 atmospheric mass levels in the original three-dimensional fields. These facts come from the user's inspection output; they are not an independent inspection of the HPC by the kit authors. File count alone does not prove the full time schedule.

The observed units in SCIENCE.md reproduce those headers. In particular, `BC1` and `OC1` are `ug/kg-dryair`, `so2` is `ppmv`, and `PM2_5_DRY`, `PM10`, and `TOT_DUST` are `ug m^-3`. The sample inventory originally found `o3`, `no2`, and `co` absent; the revised twenty-field selection uses `TOT_DUST`, `BC1`, and `OC1` instead. No absent species is reconstructed or filled with zeros.

## Population ranking and geographical sampling points

1. **Office of the Registrar General & Census Commissioner, India: Census 2011, A-04(I), final Class I towns and urban agglomerations.**
   - [Official catalog](https://censusindia.gov.in/nada/index.php/catalog/42876/study-description)
   - [Official CLASS_I.xlsx](https://censusindia.gov.in/nada/index.php/catalog/42876/download/46544/CLASS_I.xlsx)
   - The workbook was read directly. `cities.csv` uses the 2011 `Persons` entries for top-level ranks 1 through 10, not their constituent municipalities. Jaipur is the standalone `M.Corp.` entry; the other nine are `U.A.` entries. The final workbook gives Ahmadabad U.A. **6,357,693**. The displayed modern names Mumbai, Bengaluru, and Ahmedabad are mapped to the original unit names in a separate column.
2. **Census of India official website.** [Census website](https://www.censusindia.gov.in/census.website/en). At preparation, the site describes the forthcoming Census 2027 population enumeration and labels its population finder Census 2011. The kit's ranking is therefore explicitly a **2011 ranking**, not a current population estimate.
3. **India Meteorological Department, Daily Normals of Global and Diffuse Radiation, 1991-2020.** [Official PDF](https://imdpune.gov.in/library/Radiation_Normals_1991-2020.pdf), printed page **ii**, station-location table. Nine reference points in `cities.csv` use this table's degrees and minutes, converted to decimal degrees. Bengaluru is specifically **BENGALURU ARU: 12 degrees 58 minutes N, 77 degrees 38 minutes E**, rather than the differently named Bangalore point in older publications. These are published station reference positions, not asserted urban centroids or current instrument coordinates. Decimal precision reflects conversion, not measured position accuracy.
4. **Surat District, Government of Gujarat.** [How to Reach: Location](https://surat.nic.in/how-to-reach/). The published city reference point is **21.170240 N, 72.831062 E**. Its population prose is not used for the ranking.

Population units select the cities. The geographic points select model grid cells. These two purposes are different: a sample at one reference point is not an average over the census urban agglomeration.

## WRF fields, vertical coordinates, and chemistry

5. **NCAR / WRF: WRF Output Variables.** [Official variable documentation](https://www2.mmm.ucar.edu/wrf/site/users_guide/output_variables.html). This supplies background definitions for the surface meteorological fields, accumulated rainfall, and pressure/geopotential support arrays. Actual input-file attributes remain the authority for this dataset's units and dimensions.
6. **NCAR / WRF User's Guide: Special WRF Output Variables.** [Official guide, Chapter 5](https://www2.mmm.ucar.edu/wrf/users/docs/user_guide_V3/user_guide_V3.1/users_guide_chap5.htm). The relevant stable definitions are total geopotential `PH + PHB`, geopotential height `(PH + PHB) / 9.81`, and total pressure `P + PB`. The kit's mass-level height is the midpoint of adjacent interface heights; subtracting `HGT` expresses height above model terrain. This historical guide is cited for those equations, not for installation instructions or current software compatibility.
7. **WRF developers: chemistry registry and GOCART implementation.** [registry.var_chem](https://github.com/wrf-model/WRF/blob/master/Registry/registry.var_chem) and [module_gocart_aerosols.F](https://github.com/wrf-model/WRF/blob/master/chem/module_gocart_aerosols.F). These are background references for chemistry component conventions. A registry label is not evidence that all of its species were written by this specific simulation. `BC1` and `OC1` are retained component variables; neither represents total black/organic carbon by itself. The source run's chemistry configuration and NetCDF metadata should be checked before extending that interpretation.

## Concentration and rainfall legends

8. **Central Pollution Control Board: About National Air Quality Index.** [Official CPCB document](https://www.cpcb.nic.in/displaypdf.php?id=bmF0aW9uYWwtYWlyLXF1YWxpdHktaW5kZXgvQWJvdXRfQVFJLnBkZg). Its PM2.5 concentration breakpoints are 0-30, 31-60, 61-90, 91-120, 121-250, and 250+ micrograms per cubic metre. The kit does **not** apply these AQI category labels to model snapshots.
9. **CPCB: AQI calculation explanation.** [Official monitoring report](https://cpcb.nic.in/displaypdf.php?id=bWFudWFsLW1vbml0b3JpbmcvQVFJX05BTVBfUmVwX1NlcHRlbWJlcjIwMTYucGRm). PM2.5 uses a 24-hour average; the stated minimum is 16 hours of available data for a sub-index. Overall AQI requires at least three pollutants including PM2.5 or PM10. This supports the distinction between the kit's modeled concentrations and regulatory AQI.
10. **IMD, RSMC New Delhi: Frequently Asked Questions on Tropical Cyclones.** [Official FAQ](https://rsmcnewdelhi.imd.gov.in/images/pdf/faq.pdf). Cyclone classification uses maximum sustained three-minute surface winds. Its severe category starts at 48 knots and its very severe category at 64 knots. The kit's 0-25 m/s wind display is a plotting choice, not a cyclone category definition.
11. **IMD: rainfall terminology.** [Official Ahmedabad bulletin terminology](https://mausam.imd.gov.in/ahmedabad/mcdata/state.pdf). Familiar heavy-rainfall labels in this table concern **24-hour accumulated rainfall**. The kit instead plots interval-average rates computed from accumulated model rainfall; its seven color bins are explicitly chosen visualization intervals.

## Coastline asset

12. **Natural Earth 1:110m coastline.** [Official dataset description](https://www.naturalearthdata.com/downloads/110m-physical-vectors/110m-coastline/) and [terms of use](https://www.naturalearthdata.com/about/terms-of-use/). The source data are public domain.
   - Upstream geometry: [Natural Earth vector repository, ne_110m_coastline.geojson](https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_coastline.geojson).
   - The kit bundles a regional coastline subset in `assets/coastline_india_region.json`, so plotting does not need an online map download.
   - It supplies geographical context only. Administrative and international borders are not part of this asset. A rectangular India-region map can include neighboring land and ocean; it is not an India-only political-boundary mask.

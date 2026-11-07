# Dock & Yard Appointment Scheduling: synthetic data generator

Schedules inbound/outbound appointments against **dock, yard, labor, vehicle and time-window** constraints, simulates the day-of execution, injects **labelled** edge cases, and ships a separate ground truth. 100% synthetic (no external data, no PII). Python 3.9+, standard library only (`pytest` for tests).

## Run
```bash
pip install -r requirements.txt
python -m dock_scheduling.generate --out data/full --repro        # 10 facilities, 100 docks, 20,000 appts, 60 days, seed 20261022
python -m dock_scheduling.generate --facilities 2 --appts 1000 --days 14 --out data/starter   # same generator, smaller scale
python -m pytest -q                                                # tests
```
Scale parameters: `--seed --facilities --docks --appts --days --start --carriers --anom-rate`.

## Workflow implemented (`dock_scheduling/generate.py`)
1. **Master data**: Facility, Dock (direction, reefer/hazmat capability, capacity 1), YardSlot (STANDARD/REEFER/HAZMAT), Carrier, Vehicle, HandlingRequirement, Carrier-Facility bridge (N:M).
2. **Capacity calendars**: A/B labor shifts per facility-day (headcount, ~3% cancelled + 2 forced per facility); dock/yard/vehicle occupancy in 15-min slots.
3. **Requests**: peaked demand (morning/afternoon peaks, weekday-heavy), shipment pallets/weight, service duration = `ceil((base + per_pallet*pallets)/15)*15`.
4. **Allocation** (first-come-first-served within a 4 h window): a slot is granted only if dock is free and compatible (direction, reefer, hazmat), labor headcount covers the whole window, a compatible yard slot is free from 30 min before arrival, and an approved carrier's compatible vehicle is free. Otherwise the request is **REJECTED** (`REJECTED_NO_CAPACITY` exception).
5. **Execution simulation**: append-only events `SCHEDULED > CHECK_IN > SERVICE_START > SERVICE_END > DEPARTED` (or `NO_SHOW`); no-shows (3%), early/late arrivals, congestion wait driven by facility-hour load. Appointment `status` is **derived** from the last event.
6. **Injected edge cases** (60 each; overlap = 60 injected + 60 counterparts): overlapping appointments exceed dock capacity; incompatible load assigned; check-in before appointment date; labor shift not available; no-show not recorded. Labels go **only** to `ground_truth.csv/json`.
7. **Exceptions** carry cause codes. Operational ones come from the simulation; rule-based ones come from the rule engine (`validate.detect`) run over the data, not from the labels.

IDs: `FAC-001`, `DOCK-FAC-001-001`, `APPT-2026-000001`, `SHP-2026-000001`, `CHECK-APPT-2026-000001-01` (zero-padded, immutable; appointment IDs follow request-creation order so anomalies are not identifiable by ID).

## Outputs (`data/full/`)
`<entity>.csv`, `dataset.json`, `schema.sql`, `seed.sql` (schema + data, FK-checked in SQLite), `ground_truth.csv/json`, `DATA_DICTIONARY.md` (types, required, allowed values, units, uniqueness, FKs, cardinality), `validation_summary.json`, `metrics.json` (utilization, wait time, no-show/rejection rate, exceptions by cause), `manifest.json` (seed, parameters, command, row counts, SHA-256, source statement), `reproducibility_report.json`.

## Validation (66 checks, all passing)
PK uniqueness, FK integrity, required fields and enums, ID formats, date ordering, derived-value reconciliation (service minutes, status), lifecycle transitions, timeline monotonicity, duplicate events, conditional shipment fields, parent/child consistency, and **rule engine == ground truth** for each of the five anomaly types (exact match, so the baseline has zero unlabelled violations).

## Reproducibility
Fixed seed 20261022; `--repro` regenerates twice and compares row counts + SHA-256 of every output file (verified identical, also under different `PYTHONHASHSEED`).

## Notes / assumptions
- Event volume is ~93.5k (not exactly 100k) because rejected (~5.7%) and no-show requests have shorter lifecycles; this is reported in `manifest.json`.
- Moved/injected appointments keep their original yard slot and vehicle; vehicle double-booking is enforced for baseline allocation only.
- Metrics include injected anomalies; baseline-only metrics can be derived by excluding `ground_truth.csv` IDs.

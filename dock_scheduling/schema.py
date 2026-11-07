"""Single source of truth: data dictionary, enums, DDL. Field = (name, type, required Y/N, rule[, 'parent.col'])."""
import re
T, I, R = 'TEXT', 'INTEGER', 'REAL'
ST = 'enum:ACTIVE|INACTIVE'
SCHEMA = {
 'facility': (['facility_id'], [
  ('facility_id', T, 'Y', 'FAC-NNN; unique; immutable'), ('name', T, 'Y', 'display name'), ('city', T, 'Y', 'free text'),
  ('timezone', T, 'Y', 'IANA tz name'), ('open_time', T, 'Y', 'HH:MM local; < close_time'), ('close_time', T, 'Y', 'HH:MM local'),
  ('effective_from', T, 'Y', 'ISO date; <= first appointment date'), ('status', T, 'Y', ST)]),
 'dock': (['dock_id'], [
  ('dock_id', T, 'Y', 'DOCK-<facility_id>-NNN; unique'), ('facility_id', T, 'Y', 'parent facility', 'facility.facility_id'),
  ('dock_type', T, 'Y', 'enum:INBOUND|OUTBOUND|BOTH; direction handled'), ('supports_reefer', I, 'Y', 'enum:0|1; 1 = refrigerated-capable'),
  ('supports_hazmat', I, 'Y', 'enum:0|1; 1 = hazmat-capable'), ('max_concurrent_trucks', I, 'Y', 'trucks; fixed 1 (capacity rule)'),
  ('effective_from', T, 'Y', 'ISO date'), ('status', T, 'Y', ST)]),
 'yard_slot': (['yard_slot_id'], [
  ('yard_slot_id', T, 'Y', 'YARD-<facility_id>-NNN; unique'), ('facility_id', T, 'Y', 'parent facility', 'facility.facility_id'),
  ('slot_type', T, 'Y', 'enum:STANDARD|REEFER|HAZMAT'), ('status', T, 'Y', ST)]),
 'carrier': (['carrier_id'], [
  ('carrier_id', T, 'Y', 'CAR-NNN; unique'), ('name', T, 'Y', 'free text'), ('scac_code', T, 'Y', '[U] carrier code'),
  ('effective_from', T, 'Y', 'ISO date'), ('status', T, 'Y', ST)]),
 'carrier_facility': (['carrier_id', 'facility_id', 'effective_from'], [
  ('carrier_id', T, 'Y', 'bridge N:M carrier<->facility', 'carrier.carrier_id'), ('facility_id', T, 'Y', 'bridge N:M', 'facility.facility_id'),
  ('effective_from', T, 'Y', 'ISO date approval start'), ('effective_to', T, 'N', 'ISO date; null = open-ended')]),
 'vehicle': (['vehicle_id'], [
  ('vehicle_id', T, 'Y', 'VEH-NNNN; unique'), ('carrier_id', T, 'Y', 'owning carrier', 'carrier.carrier_id'),
  ('vehicle_type', T, 'Y', 'enum:DRY_VAN|REEFER_TRAILER'), ('hazmat_certified', I, 'Y', 'enum:0|1'),
  ('plate_no', T, 'Y', 'synthetic plate'), ('capacity_pallets', I, 'Y', 'pallets'), ('status', T, 'Y', ST)]),
 'handling_requirement': (['requirement_id'], [
  ('requirement_id', T, 'Y', 'HR-NNN; unique'), ('requirement_code', T, 'Y', '[U] enum:DRY|REEFER|HAZMAT'),
  ('base_service_min', I, 'Y', 'minutes fixed service time'), ('per_pallet_min', R, 'Y', 'minutes per pallet'),
  ('labor_required', I, 'Y', 'workers held for the whole service window'), ('needs_reefer_dock', I, 'Y', 'enum:0|1'),
  ('needs_hazmat_dock', I, 'Y', 'enum:0|1'), ('yard_slot_type', T, 'Y', 'enum:STANDARD|REEFER|HAZMAT')]),
 'appointment': (['appointment_id'], [
  ('appointment_id', T, 'Y', 'APPT-2026-NNNNNN; unique; numbered by request creation time'),
  ('facility_id', T, 'Y', 'facility', 'facility.facility_id'), ('dock_id', T, 'N', 'null when REJECTED; dock must belong to facility', 'dock.dock_id'),
  ('yard_slot_id', T, 'N', 'null when REJECTED', 'yard_slot.yard_slot_id'), ('carrier_id', T, 'Y', 'must be approved at facility', 'carrier.carrier_id'),
  ('vehicle_id', T, 'N', 'null when REJECTED; must belong to carrier', 'vehicle.vehicle_id'), ('direction', T, 'Y', 'enum:INBOUND|OUTBOUND'),
  ('requested_start', T, 'Y', 'ISO datetime; start of 4h request window'), ('requested_end', T, 'Y', 'ISO datetime; > requested_start'),
  ('scheduled_start', T, 'N', 'ISO datetime within facility hours; null when REJECTED'), ('scheduled_end', T, 'N', 'start + planned_service_min'),
  ('planned_service_min', I, 'Y', 'minutes = ceil((base+per_pallet*pallets)/15)*15 (derived)'), ('created_ts', T, 'Y', 'ISO datetime; < scheduled_start'),
  ('status', T, 'Y', 'enum:SCHEDULED|COMPLETED|NO_SHOW|REJECTED; derived from last event')]),
 'shipment': (['shipment_id'], [
  ('shipment_id', T, 'Y', 'SHP-2026-NNNNNN; unique'), ('appointment_id', T, 'Y', '[U] 1:1 with appointment', 'appointment.appointment_id'),
  ('requirement_id', T, 'Y', 'handling requirement', 'handling_requirement.requirement_id'), ('pallets', I, 'Y', 'pallets 4..26'),
  ('weight_kg', I, 'Y', 'kg > 0'), ('temperature_setpoint_c', I, 'N', 'deg C; required iff REEFER'), ('hazmat_class', T, 'N', 'UN class; required iff HAZMAT')]),
 'labor_shift': (['shift_id'], [
  ('shift_id', T, 'Y', 'SHIFT-<facility_id>-YYYYMMDD-<A|B>; unique'), ('facility_id', T, 'Y', 'facility', 'facility.facility_id'),
  ('shift_date', T, 'Y', 'ISO date'), ('shift_code', T, 'Y', 'enum:A|B'), ('start_time', T, 'Y', 'HH:MM'), ('end_time', T, 'Y', 'HH:MM'),
  ('headcount', I, 'Y', 'workers; 0 iff CANCELLED'), ('status', T, 'Y', 'enum:ACTIVE|CANCELLED')]),
 'check_in_event': (['event_id'], [
  ('event_id', T, 'Y', 'CHECK-<appointment_id>-NN; unique; append-only history'), ('appointment_id', T, 'Y', 'appointment', 'appointment.appointment_id'),
  ('event_seq', I, 'Y', '1..n contiguous per appointment'),
  ('event_type', T, 'Y', 'enum:SCHEDULED|CHECK_IN|SERVICE_START|SERVICE_END|DEPARTED|NO_SHOW|REJECTED'), ('event_ts', T, 'Y', 'ISO datetime; non-decreasing in event_seq')]),
 'exception_record': (['exception_id'], [
  ('exception_id', T, 'Y', 'EXC-2026-NNNNNN; unique'), ('appointment_id', T, 'Y', 'appointment', 'appointment.appointment_id'),
  ('cause_code', T, 'Y', 'enum:NO_SHOW|EARLY_ARRIVAL|LATE_ARRIVAL|CONGESTION_DELAY|REJECTED_NO_CAPACITY|OVERLAP_CAPACITY|INCOMPATIBLE_LOAD|CHECKIN_BEFORE_DATE|LABOR_UNAVAILABLE|NOSHOW_UNRECORDED'),
  ('severity', T, 'Y', 'enum:INFO|WARN|CRITICAL'), ('detected_by', T, 'Y', 'enum:SIMULATION|RULE_ENGINE'),
  ('detected_ts', T, 'Y', 'ISO datetime'), ('details', T, 'Y', 'human-readable cause')]),
}
GT_COLS = ['anomaly_id', 'issue_type', 'entity', 'entity_id', 'related_entity_id', 'role', 'rule_violated', 'expected_decision']

def enums(rule):
    m = re.search(r'enum:([A-Za-z0-9_|]+)', rule)
    return m.group(1).split('|') if m else None

def ddl():
    out = []
    for t, (pk, fs) in SCHEMA.items():
        cols, fks = [], []
        for f in fs:
            n, ty, req, rule = f[:4]
            c = f'  {n} {ty}' + (' NOT NULL' if req == 'Y' else '') + (' UNIQUE' if '[U]' in rule else '')
            e = enums(rule)
            if e: c += f" CHECK({n} IN ({','.join(repr(x) if ty == T else x for x in e)}))"
            cols.append(c)
            if len(f) > 4:
                a, b = f[4].split('.'); fks.append(f'  FOREIGN KEY({n}) REFERENCES {a}({b})')
        out.append(f"CREATE TABLE {t} (\n" + ',\n'.join(cols + [f"  PRIMARY KEY({','.join(pk)})"] + fks) + '\n);')
    return '\n'.join(out) + '\n'

CARD = """# Data dictionary
Generated from `dock_scheduling/schema.py`. All timestamps are ISO-8601 local time (naive). Units: minutes, pallets, kg, deg C.

## Relationships and cardinality
| Parent | Child | Cardinality | Optional? | Notes |
|---|---|---|---|---|
| facility | dock / yard_slot / labor_shift | 1:N | no | dock and yard IDs embed the facility ID |
| carrier | vehicle | 1:N | no | |
| carrier <-> facility | carrier_facility (bridge) | N:M | no | effective-dated approval; appointments only for approved pairs |
| facility, carrier | appointment | 1:N | no | |
| dock, yard_slot, vehicle | appointment | 1:N | yes (null when REJECTED) | dock capacity 1; no overlap in valid data |
| appointment | shipment | 1:1 | no | shipment carries the handling requirement |
| handling_requirement | shipment | 1:N | no | |
| appointment | check_in_event | 1:N | no | append-only; state changes never overwrite history |
| appointment | exception_record | 1:N | yes | every exception has a cause code |

Lifecycle states (appointment.status, derived from last event): SCHEDULED -> COMPLETED | NO_SHOW; REJECTED (terminal at creation).
Event order: SCHEDULED, CHECK_IN, SERVICE_START, SERVICE_END, DEPARTED (or SCHEDULED, NO_SHOW).
`[U]` in a rule = unique constraint besides the primary key.
"""

def dictionary_md():
    s = CARD
    for t, (pk, fs) in SCHEMA.items():
        s += f"\n## {t}  (PK: {', '.join(pk)})\n| Field | Type | Required | Rule / allowed values / units | FK |\n|---|---|---|---|---|\n"
        for f in fs:
            s += f"| {f[0]} | {f[1]} | {f[2]} | {f[3].replace('|', ' / ')} | {f[4] if len(f) > 4 else ''} |\n"
    return s

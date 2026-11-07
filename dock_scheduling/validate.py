"""Business rules (shared with the generator), rule-engine detectors and the validation suite."""
import math, re
from datetime import datetime
from .schema import SCHEMA, enums

ISSUES = ['OVERLAP_CAPACITY', 'INCOMPATIBLE_LOAD', 'CHECKIN_BEFORE_DATE', 'LABOR_UNAVAILABLE', 'NOSHOW_UNRECORDED']
DESC = {'OVERLAP_CAPACITY': 'Appointments overlap on a dock with capacity 1',
        'INCOMPATIBLE_LOAD': 'Load requirement incompatible with assigned dock, vehicle or direction',
        'CHECKIN_BEFORE_DATE': 'CHECK_IN recorded before the appointment date',
        'LABOR_UNAVAILABLE': 'No active labor shift covers the appointment start',
        'NOSHOW_UNRECORDED': 'Appointment never progressed past SCHEDULED and no NO_SHOW was recorded'}
DECISION = {'OVERLAP_CAPACITY': 'RESCHEDULE_ONE_APPOINTMENT', 'INCOMPATIBLE_LOAD': 'REASSIGN_TO_COMPATIBLE_DOCK',
            'CHECKIN_BEFORE_DATE': 'HOLD_IN_YARD_OR_REJECT_CHECKIN', 'LABOR_UNAVAILABLE': 'RESCHEDULE_TO_STAFFED_SHIFT',
            'NOSHOW_UNRECORDED': 'RECORD_NO_SHOW_EVENT'}

def dock_ok(d, direction, code):
    return d['dock_type'] in (direction, 'BOTH') and (code != 'REEFER' or d['supports_reefer'] == 1) and (code != 'HAZMAT' or d['supports_hazmat'] == 1)

def veh_ok(v, code):
    return {'DRY': v['vehicle_type'] == 'DRY_VAN', 'REEFER': v['vehicle_type'] == 'REEFER_TRAILER', 'HAZMAT': v['hazmat_certified'] == 1}[code]

def detect(T):
    dock = {d['dock_id']: d for d in T['dock']}; veh = {v['vehicle_id']: v for v in T['vehicle']}
    code = {r['requirement_id']: r['requirement_code'] for r in T['handling_requirement']}
    ship = {s['appointment_id']: s for s in T['shipment']}
    shifts = {(s['facility_id'], s['shift_date'], s['shift_code']): s for s in T['labor_shift']}
    out = {k: set() for k in ISSUES}
    by = {}
    for a in T['appointment']:
        if a['dock_id']: by.setdefault(a['dock_id'], []).append(a)
    for lst in by.values():
        lst.sort(key=lambda a: (a['scheduled_start'], a['appointment_id'])); active = []
        for a in lst:
            active = [x for x in active if x['scheduled_end'] > a['scheduled_start']]
            if active: out['OVERLAP_CAPACITY'].update([a['appointment_id']] + [x['appointment_id'] for x in active])
            active.append(a)
    for a in T['appointment']:
        if not a['dock_id']: continue
        c = code[ship[a['appointment_id']]['requirement_id']]
        if not dock_ok(dock[a['dock_id']], a['direction'], c) or (a['vehicle_id'] and not veh_ok(veh[a['vehicle_id']], c)):
            out['INCOMPATIBLE_LOAD'].add(a['appointment_id'])
        sh = shifts.get((a['facility_id'], a['scheduled_start'][:10], 'A' if a['scheduled_start'][11:13] < '14' else 'B'))
        if not sh or sh['status'] != 'ACTIVE' or sh['headcount'] == 0: out['LABOR_UNAVAILABLE'].add(a['appointment_id'])
    start = {a['appointment_id']: a['scheduled_start'] for a in T['appointment']}; last = {}
    for e in sorted(T['check_in_event'], key=lambda e: (e['appointment_id'], e['event_seq'])):
        last[e['appointment_id']] = e['event_type']
        if e['event_type'] == 'CHECK_IN' and e['event_ts'][:10] < start[e['appointment_id']][:10]: out['CHECKIN_BEFORE_DATE'].add(e['appointment_id'])
    out['NOSHOW_UNRECORDED'] = {k for k, v in last.items() if v == 'SCHEDULED'}
    return {k: sorted(v) for k, v in out.items()}

IDS = {'facility': r'FAC-\d{3}', 'dock': r'DOCK-FAC-\d{3}-\d{3}', 'yard_slot': r'YARD-FAC-\d{3}-\d{3}', 'carrier': r'CAR-\d{3}',
       'vehicle': r'VEH-\d{4}', 'handling_requirement': r'HR-\d{3}', 'appointment': r'APPT-2026-\d{6}', 'shipment': r'SHP-2026-\d{6}',
       'labor_shift': r'SHIFT-FAC-\d{3}-\d{8}-[AB]', 'check_in_event': r'CHECK-APPT-2026-\d{6}-\d{2}', 'exception_record': r'EXC-2026-\d{6}'}
OKSEQ = [('SCHEDULED', 'CHECK_IN', 'SERVICE_START', 'SERVICE_END', 'DEPARTED'), ('SCHEDULED', 'NO_SHOW'), ('SCHEDULED',), ('REJECTED',)]
STATUS = {'SCHEDULED': 'SCHEDULED', 'DEPARTED': 'COMPLETED', 'NO_SHOW': 'NO_SHOW', 'REJECTED': 'REJECTED'}

def run_all(T, G):
    R = []
    def chk(name, bad): R.append(dict(check=name, violations=len(bad), passed=not bad, examples=[str(x) for x in bad[:3]]))
    for t, (pk, fs) in SCHEMA.items():
        seen, dup, bad, badid = set(), [], [], []
        for r in T[t]:
            k = tuple(r[c] for c in pk)
            if k in seen: dup.append(k)
            seen.add(k)
            for f in fs:
                v = r[f[0]]
                if f[2] == 'Y' and v is None: bad.append((t, f[0], 'missing'))
                e = enums(f[3])
                if e and v is not None and str(v) not in e: bad.append((t, f[0], v))
            if t in IDS and not re.fullmatch(IDS[t], r[pk[0]]): badid.append(r[pk[0]])
        chk(f'pk_unique:{t}', dup); chk(f'required_and_enum:{t}', bad); chk(f'id_format:{t}', badid)
        for f in fs:
            if len(f) > 4:
                pt, pc = f[4].split('.'); ok = {r[pc] for r in T[pt]}
                chk(f'fk:{t}.{f[0]}->{f[4]}', [r[f[0]] for r in T[t] if r[f[0]] is not None and r[f[0]] not in ok])
    ship = {s['appointment_id']: s for s in T['shipment']}; rq = {r['requirement_id']: r for r in T['handling_requirement']}
    dk = {d['dock_id']: d for d in T['dock']}; vh = {v['vehicle_id']: v for v in T['vehicle']}
    appr = {(c['carrier_id'], c['facility_id']) for c in T['carrier_facility']}
    dt = datetime.fromisoformat
    bt, ba, bj, bs = [], [], [], []
    for a in T['appointment']:
        s = ship[a['appointment_id']]; q = rq[s['requirement_id']]
        if a['requested_end'] <= a['requested_start']: bt.append(a['appointment_id'])
        if a['planned_service_min'] != math.ceil((q['base_service_min'] + q['per_pallet_min'] * s['pallets']) / 15) * 15: ba.append(a['appointment_id'])
        if a['scheduled_start']:
            if a['created_ts'] >= a['scheduled_start'] or (dt(a['scheduled_end']) - dt(a['scheduled_start'])).total_seconds() / 60 != a['planned_service_min']: bt.append(a['appointment_id'])
        c = q['requirement_code']
        if (c == 'REEFER') != (s['temperature_setpoint_c'] is not None) or (c == 'HAZMAT') != (s['hazmat_class'] is not None) or s['weight_kg'] <= 0: bs.append(s['shipment_id'])
        if (a['carrier_id'], a['facility_id']) not in appr or (a['dock_id'] and dk[a['dock_id']]['facility_id'] != a['facility_id']) or (a['vehicle_id'] and vh[a['vehicle_id']]['carrier_id'] != a['carrier_id']): bj.append(a['appointment_id'])
    chk('date_ordering', bt); chk('derived_planned_minutes', ba); chk('shipment_conditional_fields', bs); chk('parent_child_consistency', bj)
    chk('labor_headcount_vs_status', [s['shift_id'] for s in T['labor_shift'] if (s['headcount'] == 0) != (s['status'] == 'CANCELLED')])
    evs = {}
    for e in T['check_in_event']: evs.setdefault(e['appointment_id'], []).append(e)
    bl, bst, bts, bdup = [], [], [], []
    for a in T['appointment']:
        es = sorted(evs.get(a['appointment_id'], []), key=lambda e: e['event_seq']); ty = tuple(e['event_type'] for e in es)
        if ty not in OKSEQ or [e['event_seq'] for e in es] != list(range(1, len(es) + 1)) or any(e['event_id'] != f"CHECK-{a['appointment_id']}-{e['event_seq']:02d}" for e in es): bl.append(a['appointment_id'])
        if es and STATUS[ty[-1]] != a['status']: bst.append(a['appointment_id'])
        if any(es[i]['event_ts'] > es[i + 1]['event_ts'] for i in range(len(es) - 1)): bts.append(a['appointment_id'])
        if len(set(ty)) != len(ty): bdup.append(a['appointment_id'])
    chk('lifecycle_transitions', bl); chk('status_reconciles_with_last_event', bst); chk('event_timeline_valid', bts); chk('duplicate_events', bdup)
    det = detect(T); truth = {}
    for g in G: truth.setdefault(g['issue_type'], set()).add(g['entity_id'])
    for t in ISSUES: chk(f'rule_engine_matches_ground_truth:{t}', sorted(set(det[t]) ^ truth.get(t, set())))
    chk('exceptions_cover_rule_engine', sorted({(a, t) for t in ISSUES for a in det[t]} - {(e['appointment_id'], e['cause_code']) for e in T['exception_record']}))
    return dict(passed=all(c['passed'] for c in R), checks_run=len(R), checks=R, row_counts={t: len(v) for t, v in T.items()},
                ground_truth_counts={t: len(truth.get(t, ())) for t in ISSUES})

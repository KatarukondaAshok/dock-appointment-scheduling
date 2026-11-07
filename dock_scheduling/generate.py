"""Deterministic synthetic generator: inbound/outbound dock-yard appointment scheduling.
Run: python -m dock_scheduling.generate --out data/full --repro"""
import argparse, csv, hashlib, json, math, os, random, sqlite3, tempfile
from datetime import date, datetime, timedelta
from .schema import SCHEMA, GT_COLS, ddl, dictionary_md
from . import validate as V

SLOT, DAY, OPEN, CLOSE = 15, 96, 24, 88          # 15-min slots; facility open 06:00-22:00
CITIES = ['Bengaluru', 'Mumbai', 'Delhi', 'Chennai', 'Hyderabad', 'Pune', 'Kolkata', 'Ahmedabad', 'Jaipur', 'Kochi']
REQS = [('HR-001', 'DRY', 30, 1.0, 2, 0, 0, 'STANDARD'), ('HR-002', 'REEFER', 45, 1.5, 3, 1, 0, 'REEFER'), ('HR-003', 'HAZMAT', 60, 2.0, 3, 0, 1, 'HAZMAT')]
FINAL = {'SCHEDULED': 'SCHEDULED', 'DEPARTED': 'COMPLETED', 'NO_SHOW': 'NO_SHOW', 'REJECTED': 'REJECTED'}

def build(seed=20261022, facilities=10, docks=10, appts=20000, days=60, start='2026-08-03', carriers=30, anom_rate=0.003):
    rng = random.Random(seed)
    d0 = date.fromisoformat(start); base = datetime(d0.year, d0.month, d0.day); N = days * DAY
    iso = lambda dt: dt.isoformat(timespec='seconds')
    sl = lambda s: base + timedelta(minutes=SLOT * s)
    T = {k: [] for k in SCHEMA}; eff = (d0 - timedelta(days=365)).isoformat()
    # ---- Step 2a: master data
    for i in range(1, facilities + 1):
        c = CITIES[(i - 1) % len(CITIES)]
        T['facility'].append(dict(facility_id=f'FAC-{i:03d}', name=f'DC {c}', city=c, timezone='Asia/Kolkata', open_time='06:00', close_time='22:00', effective_from=eff, status='ACTIVE'))
    fids = [f['facility_id'] for f in T['facility']]
    for fid in fids:
        for k in range(docks):
            m = k % 10
            T['dock'].append(dict(dock_id=f'DOCK-{fid}-{k + 1:03d}', facility_id=fid, dock_type='INBOUND' if m < 4 else 'OUTBOUND' if m < 8 else 'BOTH',
                                  supports_reefer=int(m in (0, 1, 4, 5, 8)), supports_hazmat=int(m in (2, 6, 9)), max_concurrent_trucks=1, effective_from=eff, status='ACTIVE'))
        for k in range(12):
            T['yard_slot'].append(dict(yard_slot_id=f'YARD-{fid}-{k + 1:03d}', facility_id=fid, slot_type='STANDARD' if k < 8 else 'REEFER' if k < 10 else 'HAZMAT', status='ACTIVE'))
    for c in range(1, carriers + 1):
        cid = f'CAR-{c:03d}'
        T['carrier'].append(dict(carrier_id=cid, name=f'Carrier {c:03d} Logistics', scac_code=f'C{c:03d}', effective_from=eff, status='ACTIVE'))
        for fid in sorted(set(rng.sample(fids, min(6, len(fids))) + [fids[(c - 1) % len(fids)]])):
            T['carrier_facility'].append(dict(carrier_id=cid, facility_id=fid, effective_from=eff, effective_to=None))
        for k in range(10):
            n = len(T['vehicle']) + 1
            T['vehicle'].append(dict(vehicle_id=f'VEH-{n:04d}', carrier_id=cid, vehicle_type='REEFER_TRAILER' if k in (2, 4, 7, 9) else 'DRY_VAN', hazmat_certified=int(k in (1, 6)),
                                     plate_no=f'KA{rng.randint(1, 60):02d}{chr(65 + rng.randrange(26))}{chr(65 + rng.randrange(26))}{rng.randint(1000, 9999)}', capacity_pallets=26, status='ACTIVE'))
    for r in REQS:
        T['handling_requirement'].append(dict(requirement_id=r[0], requirement_code=r[1], base_service_min=r[2], per_pallet_min=r[3], labor_required=r[4], needs_reefer_dock=r[5], needs_hazmat_dock=r[6], yard_slot_type=r[7]))
    RQ = {r[1]: r for r in REQS}
    # ---- Step 2b: labor/dock capacity calendars (2 forced + ~3% random cancelled shifts)
    cap = {f: [0] * N for f in fids}; used = {f: [0] * N for f in fids}; cancelled = {f: [] for f in fids}
    for fid in fids:
        for d in range(days):
            dd = d0 + timedelta(days=d)
            for code, (a, b) in (('A', (24, 56)), ('B', (56, 88))):
                canc = rng.random() < 0.03 or (d, code) in ((days // 2, 'A'), (days // 3, 'B'))
                hc = 0 if canc else rng.randint(int(1.4 * docks), int(2.4 * docks))
                T['labor_shift'].append(dict(shift_id=f'SHIFT-{fid}-{dd:%Y%m%d}-{code}', facility_id=fid, shift_date=dd.isoformat(), shift_code=code,
                                             start_time='06:00' if code == 'A' else '14:00', end_time='14:00' if code == 'A' else '22:00', headcount=hc, status='CANCELLED' if canc else 'ACTIVE'))
                for x in range(d * DAY + a, d * DAY + b): cap[fid][x] = hc
                if canc: cancelled[fid].append((d * DAY + a, d * DAY + b))
    # ---- Step 2c: carrier appointment requests (peaked demand), first-come-first-served allocation
    appr = {f: [] for f in fids}
    for r in T['carrier_facility']: appr[r['facility_id']].append(r['carrier_id'])
    veh = {}
    for v in T['vehicle']: veh.setdefault(v['carrier_id'], []).append(v)
    dayw = [(1, 1, 1, 1, 1, .5, .2)[(d0 + timedelta(days=d)).weekday()] for d in range(days)]
    hourw = [1, 3, 6, 6, 5, 3, 2, 3, 4, 4, 3, 2, 1.5, 1, .5]
    fw = [rng.uniform(.8, 1.2) for _ in fids]; reqs = []
    for i in range(appts):
        fid = rng.choices(fids, fw)[0]; d = rng.choices(range(days), dayw)[0]
        s0 = d * DAY + (6 + rng.choices(range(15), hourw)[0]) * 4 + rng.randrange(4)
        u = rng.random(); code = 'DRY' if u < .76 else 'REEFER' if u < .94 else 'HAZMAT'
        pal = rng.randint(8, 26) if code == 'REEFER' else rng.randint(4, 26); q = RQ[code]
        reqs.append(dict(key=i, fid=fid, cid=rng.choice(appr[fid]), code=code, dir='INBOUND' if rng.random() < .55 else 'OUTBOUND', pal=pal, kg=pal * rng.randint(300, 900),
                         s0=s0, cr=s0 - rng.randint(2 * DAY, 10 * DAY), n=math.ceil((q[2] + q[3] * pal) / 15) * 15 // SLOT, dock=None, yard=None, veh=None, s=None, mark=None))
    reqs.sort(key=lambda r: (r['cr'], r['key']))
    dock_by = {f: [d for d in T['dock'] if d['facility_id'] == f] for f in fids}; yard_by = {f: [y for y in T['yard_slot'] if y['facility_id'] == f] for f in fids}
    DK = {d['dock_id']: d for d in T['dock']}
    bd = {d['dock_id']: {} for d in T['dock']}; by_ = {y['yard_slot_id']: set() for y in T['yard_slot']}; bv = {v['vehicle_id']: set() for v in T['vehicle']}
    free = lambda b, lo, hi: not any(x in b for x in range(lo, hi))
    for r in reqs:
        ds = [d for d in dock_by[r['fid']] if V.dock_ok(d, r['dir'], r['code'])]; rng.shuffle(ds)
        ys = [y for y in yard_by[r['fid']] if y['slot_type'] == RQ[r['code']][7]]; vs = [v for v in veh[r['cid']] if V.veh_ok(v, r['code'])]
        lab, n = RQ[r['code']][4], r['n']
        for s in range(r['s0'], r['s0'] + 17):                      # 4h request window
            o = s % DAY
            if o < OPEN or o + n > CLOSE or s + n > N: continue
            if any(used[r['fid']][x] + lab > cap[r['fid']][x] for x in range(s, s + n)): continue
            v = next((v for v in vs if free(bv[v['vehicle_id']], s, s + n)), None)
            y = next((y for y in ys if free(by_[y['yard_slot_id']], s - 2, s + n)), None)
            d = next((d for d in ds if free(bd[d['dock_id']], s, s + n)), None)
            if v and y and d:
                for x in range(s, s + n): bd[d['dock_id']][x] = r['key']; used[r['fid']][x] += lab
                bv[v['vehicle_id']].update(range(s, s + n)); by_[y['yard_slot_id']].update(range(s - 2, s + n))
                r.update(dock=d['dock_id'], yard=y['yard_slot_id'], veh=v['vehicle_id'], s=s); break
    # ---- Step 5: labelled edge cases injected AFTER a valid baseline
    sched = [r for r in reqs if r['dock']]; k = max(1, round(anom_rate * appts)); truth = []
    idx = {}
    for r in sched: idx.setdefault((r['fid'], r['s'] // DAY), []).append(r)
    def pool():
        p = [r for r in sched if not r['mark']]; rng.shuffle(p); return p
    def claim(a, s):
        for x in range(s, s + a['n']): bd[a['dock']].setdefault(x, a['key'])
    cnt = 0
    for A in pool():                                                 # overlapping appointments exceed dock capacity
        if cnt >= k: break
        if A['mark']: continue
        cands = [B for B in idx.get((A['fid'], A['s'] // DAY), []) if not B['mark'] and B['dock'] != A['dock'] and V.dock_ok(DK[B['dock']], A['dir'], A['code'])]
        if not cands: continue
        B = rng.choice(cands); ns = B['s']
        if ns % DAY + A['n'] > CLOSE or ns < A['cr'] + DAY or any(cap[A['fid']][x] == 0 for x in range(ns, ns + A['n'])): continue
        if {bd[B['dock']][x] for x in range(ns, ns + A['n']) if x in bd[B['dock']]} != {B['key']}: continue
        A.update(dock=B['dock'], s=ns); claim(A, ns); A['mark'] = B['mark'] = 'OVERLAP_CAPACITY'
        truth += [('OVERLAP_CAPACITY', A, B, 'INJECTED'), ('OVERLAP_CAPACITY', B, A, 'COUNTERPART')]; cnt += 1
    cnt = 0
    for A in pool():                                                 # incompatible load assigned
        if cnt >= k: break
        if A['code'] == 'DRY': continue
        bad = [d for d in dock_by[A['fid']] if ((A['code'] == 'REEFER' and not d['supports_reefer']) or (A['code'] == 'HAZMAT' and not d['supports_hazmat'])) and free(bd[d['dock_id']], A['s'], A['s'] + A['n'])]
        if not bad: continue
        A['dock'] = rng.choice(bad)['dock_id']; claim(A, A['s']); A['mark'] = 'INCOMPATIBLE_LOAD'; truth.append(('INCOMPATIBLE_LOAD', A, None, 'INJECTED')); cnt += 1
    cnt = 0
    for A in pool():                                                 # labor shift not available
        if cnt >= k: break
        segs = [x for x in cancelled[A['fid']] if x[0] > A['cr'] + DAY and x[1] - x[0] >= A['n']]
        if not segs: continue
        a, b = rng.choice(segs); ds = [d for d in dock_by[A['fid']] if V.dock_ok(d, A['dir'], A['code'])]; rng.shuffle(ds); ok = None
        for _ in range(6):
            s = rng.randint(a, b - A['n']); ok = next((d for d in ds if free(bd[d['dock_id']], s, s + A['n'])), None)
            if ok: break
        if not ok: continue
        A.update(dock=ok['dock_id'], s=s); claim(A, s); A['mark'] = 'LABOR_UNAVAILABLE'; truth.append(('LABOR_UNAVAILABLE', A, None, 'INJECTED')); cnt += 1
    for typ in ('CHECKIN_BEFORE_DATE', 'NOSHOW_UNRECORDED'):         # event-level anomalies
        for A in pool()[:k]: A['mark'] = typ; truth.append((typ, A, None, 'INJECTED'))
    # ---- Step 3/6: deterministic IDs, derived values
    shp = {}
    for i, r in enumerate(reqs, 1):
        r['aid'] = aid = f'APPT-2026-{i:06d}'; q = RQ[r['code']]
        T['appointment'].append(dict(appointment_id=aid, facility_id=r['fid'], dock_id=r['dock'], yard_slot_id=r['yard'], carrier_id=r['cid'], vehicle_id=r['veh'], direction=r['dir'],
            requested_start=iso(sl(r['s0'])), requested_end=iso(sl(r['s0'] + 16)), scheduled_start=iso(sl(r['s'])) if r['dock'] else None,
            scheduled_end=iso(sl(r['s'] + r['n'])) if r['dock'] else None, planned_service_min=r['n'] * SLOT, created_ts=iso(sl(r['cr'])), status=None))
        T['shipment'].append(dict(shipment_id=f'SHP-2026-{i:06d}', appointment_id=aid, requirement_id=q[0], pallets=r['pal'], weight_kg=r['kg'],
            temperature_setpoint_c=rng.choice([-18, -5, 2, 4]) if r['code'] == 'REEFER' else None, hazmat_class=rng.choice(['2.1', '3', '6.1', '8']) if r['code'] == 'HAZMAT' else None))
    # ---- Step 2d: simulate check-in, service, departure; inject no-shows, early/late arrivals, congestion
    occ = {}
    for r in reqs:
        if r['dock']:
            for x in range(r['s'], r['s'] + r['n']): occ[(r['fid'], x // 4)] = occ.get((r['fid'], x // 4), 0) + 1
    exc = []; mins = lambda m: timedelta(minutes=m)
    for r, a in zip(reqs, T['appointment']):
        aid = a['appointment_id']; t0 = sl(r['cr']) + mins(rng.randint(1, 60))
        if not r['dock']:
            evs = [('REJECTED', t0)]; exc.append((aid, 'REJECTED_NO_CAPACITY', 'WARN', 'SIMULATION', t0, 'no compatible dock/yard/labor/vehicle slot in requested window'))
        else:
            st, en = sl(r['s']), sl(r['s'] + r['n']); evs = [('SCHEDULED', t0)]
            if r['mark'] == 'NOSHOW_UNRECORDED': pass
            elif r['mark'] is None and rng.random() < 0.03:
                evs.append(('NO_SHOW', en)); exc.append((aid, 'NO_SHOW', 'WARN', 'SIMULATION', en, 'carrier did not arrive; no-show recorded'))
            else:
                if r['mark'] == 'CHECKIN_BEFORE_DATE': ci = datetime(st.year, st.month, st.day) - mins(rng.randint(60, 360)); off = None
                else:
                    u = rng.random(); off = -rng.randint(16, 90) if u < .12 else rng.randint(5, 60) if u < .22 else rng.randint(-10, 10); ci = st + mins(off)
                idx_ = occ.get((r['fid'], r['s'] // 4), 0) / (4 * docks)
                wait = rng.randint(0, 12) + (int((idx_ - .4) * rng.randint(60, 150)) if idx_ > .4 else 0)
                ss = max(ci, st) + mins(wait); se = ss + mins(int(r['n'] * SLOT * rng.uniform(.85, 1.25))); dp = se + mins(rng.randint(10, 30))
                evs += [('CHECK_IN', ci), ('SERVICE_START', ss), ('SERVICE_END', se), ('DEPARTED', dp)]
                if off is not None and off <= -30: exc.append((aid, 'EARLY_ARRIVAL', 'INFO', 'SIMULATION', ci, f'arrived {-off} min early'))
                if off is not None and off >= 30: exc.append((aid, 'LATE_ARRIVAL', 'WARN', 'SIMULATION', ci, f'arrived {off} min late'))
                if wait >= 30: exc.append((aid, 'CONGESTION_DELAY', 'WARN', 'SIMULATION', ss, f'dock wait {wait} min at facility load {idx_:.2f}'))
        for j, (typ, t) in enumerate(evs, 1):
            T['check_in_event'].append(dict(event_id=f'CHECK-{aid}-{j:02d}', appointment_id=aid, event_seq=j, event_type=typ, event_ts=iso(t)))
        a['status'] = FINAL[evs[-1][0]]
    # rule-engine exceptions (cause-coded) computed from the data, not from labels
    sev = {'OVERLAP_CAPACITY': 'CRITICAL', 'INCOMPATIBLE_LOAD': 'CRITICAL', 'CHECKIN_BEFORE_DATE': 'WARN', 'LABOR_UNAVAILABLE': 'CRITICAL', 'NOSHOW_UNRECORDED': 'WARN'}
    apd = {a['appointment_id']: a for a in T['appointment']}
    for typ, ids in V.detect(T).items():
        for aid in ids: exc.append((aid, typ, sev[typ], 'RULE_ENGINE', datetime.fromisoformat(apd[aid]['scheduled_end']), V.DESC[typ]))
    exc.sort(key=lambda e: (e[4], e[0], e[1]))
    for i, e in enumerate(exc, 1):
        T['exception_record'].append(dict(exception_id=f'EXC-2026-{i:06d}', appointment_id=e[0], cause_code=e[1], severity=e[2], detected_by=e[3], detected_ts=iso(e[4]), details=e[5]))
    truth.sort(key=lambda t: (t[0], t[1]['aid']))
    G = [dict(anomaly_id=f'GT-{i:05d}', issue_type=t, entity='Appointment', entity_id=A['aid'], related_entity_id=B['aid'] if B else None, role=role, rule_violated=V.DESC[t], expected_decision=V.DECISION[t])
         for i, (t, A, B, role) in enumerate(truth, 1)]
    return T, G

def metrics(T, docks):
    ev = {}
    for e in T['check_in_event']: ev.setdefault(e['appointment_id'], {})[e['event_type']] = datetime.fromisoformat(e['event_ts'])
    days = len({s['shift_date'] for s in T['labor_shift']})
    def agg(rows, nd):
        done = [a for a in rows if a['status'] == 'COMPLETED']
        w = [(ev[a['appointment_id']]['SERVICE_START'] - max(ev[a['appointment_id']]['CHECK_IN'], datetime.fromisoformat(a['scheduled_start']))).total_seconds() / 60 for a in done]
        dur = [(ev[a['appointment_id']]['SERVICE_END'] - ev[a['appointment_id']]['SERVICE_START']).total_seconds() / 60 / a['planned_service_min'] for a in done]
        booked = sum(a['planned_service_min'] for a in rows if a['dock_id']); n = len(rows)
        return dict(appointments=n, rejected_rate=round(sum(a['status'] == 'REJECTED' for a in rows) / n, 4), no_show_rate=round(sum(a['status'] == 'NO_SHOW' for a in rows) / n, 4),
                    avg_dock_wait_min=round(sum(w) / max(1, len(w)), 2), p90_dock_wait_min=round(sorted(w)[int(.9 * (len(w) - 1))], 2) if w else 0,
                    avg_actual_vs_planned_service=round(sum(dur) / max(1, len(dur)), 3), dock_utilization=round(booked / (nd * 16 * 60 * days), 4))
    M = dict(overall=agg(T['appointment'], len(T['dock'])), by_facility={f['facility_id']: agg([a for a in T['appointment'] if a['facility_id'] == f['facility_id']], docks) for f in T['facility']})
    M['exceptions_by_cause'] = {}
    for e in T['exception_record']: M['exceptions_by_cause'][e['cause_code']] = M['exceptions_by_cause'].get(e['cause_code'], 0) + 1
    M['exceptions_by_cause'] = dict(sorted(M['exceptions_by_cause'].items()))
    return M

def export(T, G, out):
    os.makedirs(out, exist_ok=True); sums = {}
    def wr(name, rows, cols):
        p = os.path.join(out, name + '.csv')
        with open(p, 'w', newline='') as fh:
            w = csv.writer(fh, lineterminator='\n'); w.writerow(cols)
            for r in rows: w.writerow(['' if r[c] is None else r[c] for c in cols])
    for t, (pk, fs) in SCHEMA.items(): wr(t, T[t], [f[0] for f in fs])
    wr('ground_truth', G, GT_COLS)                                  # separate file; never joined into inputs
    with open(os.path.join(out, 'dataset.json'), 'w') as fh: json.dump(T, fh, separators=(',', ':'))
    with open(os.path.join(out, 'ground_truth.json'), 'w') as fh: json.dump(G, fh, indent=1)
    with open(os.path.join(out, 'schema.sql'), 'w') as fh: fh.write(ddl())
    con = sqlite3.connect(':memory:'); con.execute('PRAGMA foreign_keys=ON'); con.executescript(ddl())
    for t, (pk, fs) in SCHEMA.items():
        cols = [f[0] for f in fs]
        con.executemany(f"INSERT INTO {t}({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [tuple(r[c] for c in cols) for r in T[t]])
    assert con.execute('PRAGMA foreign_key_check').fetchall() == [], 'FK violation in SQL seed'
    with open(os.path.join(out, 'seed.sql'), 'w') as fh: fh.write('\n'.join(con.iterdump()) + '\n')
    for f in sorted([t + '.csv' for t in SCHEMA] + ['ground_truth.csv', 'dataset.json', 'ground_truth.json', 'schema.sql', 'seed.sql']):
        sums[f] = hashlib.sha256(open(os.path.join(out, f), 'rb').read()).hexdigest()
    return sums

def run(kw, out, repro=False):
    T, G = build(**kw); sums = export(T, G, out); res = V.run_all(T, G)
    json.dump(res, open(os.path.join(out, 'validation_summary.json'), 'w'), indent=1)
    json.dump(metrics(T, kw['docks']), open(os.path.join(out, 'metrics.json'), 'w'), indent=1)
    open(os.path.join(out, 'DATA_DICTIONARY.md'), 'w').write(dictionary_md())
    man = dict(seed=kw['seed'], parameters=kw, row_counts=res['row_counts'], ground_truth_rows=len(G), sha256=sums,
               command='python -m dock_scheduling.generate ' + ' '.join(f'--{k.replace("_", "-")} {v}' for k, v in kw.items()) + f' --out {out}',
               sources='No external data used. 100% synthetic; generated from documented rules in dock_scheduling/generate.py (schema inspiration only: generic WMS/YMS dock-scheduling concepts).')
    json.dump(man, open(os.path.join(out, 'manifest.json'), 'w'), indent=1)
    if repro:
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            T1, G1 = build(**kw); s1 = export(T1, G1, t1); T2, G2 = build(**kw); s2 = export(T2, G2, t2)
        rep = dict(seed=kw['seed'], run1_equals_run2=s1 == s2, equals_main_run=s1 == sums, row_counts_run1={t: len(v) for t, v in T1.items()}, row_counts_run2={t: len(v) for t, v in T2.items()}, sha256_run1=s1, sha256_run2=s2)
        json.dump(rep, open(os.path.join(out, 'reproducibility_report.json'), 'w'), indent=1)
        print('reproducible:', rep['run1_equals_run2'] and rep['equals_main_run'])
    print('validation passed:', res['passed'], '| checks:', res['checks_run'], '| rows:', res['row_counts'])
    return res['passed']

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    for k, v in dict(seed=20261022, facilities=10, docks=10, appts=20000, days=60, start='2026-08-03', carriers=30, anom_rate=0.003).items():
        p.add_argument('--' + k.replace('_', '-'), type=type(v), default=v)
    p.add_argument('--out', default='data/full'); p.add_argument('--repro', action='store_true')
    a = vars(p.parse_args(argv)); out, repro = a.pop('out'), a.pop('repro')
    raise SystemExit(0 if run(a, out, repro) else 1)

if __name__ == '__main__': main()

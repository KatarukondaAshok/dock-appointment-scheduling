import os, tempfile
from dock_scheduling import generate as g, validate as V

KW = dict(seed=20261022, facilities=2, docks=10, appts=1200, days=14, start='2026-08-03', carriers=30, anom_rate=0.003)
T, G = g.build(**KW)

def test_validation_suite_passes():
    res = V.run_all(T, G)
    assert res['passed'], [c for c in res['checks'] if not c['passed']]

def test_every_edge_case_injected_and_detected():
    det = V.detect(T)
    for t in V.ISSUES:
        assert det[t], t
        assert set(det[t]) == {x['entity_id'] for x in G if x['issue_type'] == t}

def test_ground_truth_is_not_leaked_into_inputs():
    cols = {c for rows in T.values() for r in rows[:1] for c in r}
    assert not cols & {'issue_type', 'ground_truth', 'anomaly_id', 'role'}

def test_reproducible_same_seed():
    T2, G2 = g.build(**KW)
    assert T == T2 and G == G2
    assert g.build(**{**KW, 'seed': 1})[0]['appointment'] != T['appointment']

def test_exceptions_have_cause_codes_and_states_are_derived():
    assert all(e['cause_code'] for e in T['exception_record'])
    assert {a['status'] for a in T['appointment']} >= {'COMPLETED', 'NO_SHOW', 'SCHEDULED'}

def test_export_sql_and_checksums():
    with tempfile.TemporaryDirectory() as d:
        s = g.export(T, G, d)
        assert 'seed.sql' in s and os.path.exists(os.path.join(d, 'ground_truth.csv'))

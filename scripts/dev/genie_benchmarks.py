#!/usr/bin/env python3
"""Genie benchmarks: ask the provisioned space each governed question and compare its rows
with the metric-view SQL from genie/genie_space_def.py (local dev; CLI profile auth).

  python3 scripts/dev/genie_benchmarks.py --profile <profile> --warehouse <id> --catalog <catalog> [--schema fin_recon_observability]

The space id is resolved by title.
"""
import argparse, importlib.util, json, subprocess, sys, time
ap = argparse.ArgumentParser()
ap.add_argument("--profile", required=True)
ap.add_argument("--warehouse", required=True)
ap.add_argument("--catalog", required=True)
ap.add_argument("--schema", default="fin_recon_observability")
args = ap.parse_args()
sys.path.insert(0, 'scripts/dev')
import run_sql
spec = importlib.util.spec_from_file_location('g', 'genie/genie_space_def.py'); g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
FQ = f'{args.catalog}.{args.schema}'
P = args.profile
WAREHOUSE = args.warehouse
SPACE = next(s['space_id'] for s in json.loads(subprocess.run(['databricks','api','get','/api/2.0/genie/spaces?page_size=100','--profile',P],capture_output=True,text=True).stdout).get('spaces',[]) if s.get('title') == g.TITLE_BASE)
def api(method, path, body=None):
    cmd = ['databricks', 'api', method, path, '--profile', P]
    if body is not None:
        cmd += ['--json', json.dumps(body)]
    out = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(out.stdout or '{}') if out.returncode == 0 else {'error': out.stderr[:300]}
def rows(r):
    return [tuple(x) for x in (r.get('result', {}) or {}).get('data_array') or []]
def norm(v):
    try: return round(float(v), 2)
    except (TypeError, ValueError): return v
for q, sql in g.questions(FQ):
    exp = rows(run_sql.run(sql, P, WAREHOUSE))
    st = api('post', f'/api/2.0/genie/spaces/{SPACE}/start-conversation', {'content': q})
    conv, mid = st.get('conversation_id'), st.get('message_id')
    got, gsql, status = [], '', 'NO_START'
    for i in range(60):
        time.sleep(2)
        m = api('get', f'/api/2.0/genie/spaces/{SPACE}/conversations/{conv}/messages/{mid}')
        status = m.get('status')
        if status in ('COMPLETED', 'FAILED', 'CANCELLED'):
            qa = next((a for a in m.get('attachments', []) or [] if 'query' in a), {})
            gsql = qa.get('query', {}).get('query', '')
            if gsql:
                qr = api('get', f'/api/2.0/genie/spaces/{SPACE}/conversations/{conv}/messages/{mid}/attachments/{qa["attachment_id"]}/query-result')
                sr = qr.get('statement_response') or qr
                got = [tuple(x) for x in (sr.get('result') or {}).get('data_array') or []]
            break
    e = sorted(tuple(map(norm, r)) for r in exp); a = sorted(tuple(map(norm, r)) for r in got)
    # match if every expected value set appears (Genie may add columns)
    flat_e = sorted(v for r in e for v in r if isinstance(v, float)); flat_a = sorted(v for r in a for v in r if isinstance(v, float))
    ok = e == a or (flat_e and all(v in flat_a for v in flat_e))
    print(f"{'MATCH' if ok else 'DIFF '} [{status}] {q}\n   expected {e[:4]}\n   genie    {a[:4]}")
    if not ok: print('   genie sql:', ' '.join(gsql.split())[:400])

# Databricks notebook source
# MAGIC %md
# MAGIC # 30: review activity earlier in the active close (Lakebase seed)
# MAGIC
# MAGIC Demo scaffolding, like the planted exceptions. The active close did not
# MAGIC start today: fictional preparers and reviewers have been working in Audit
# MAGIC Workbench since the start of the month. This notebook writes that activity
# MAGIC into the app's review store (Lakebase `audit.review_actions`) through the
# MAGIC same table the app writes, so it reaches Unity Catalog the same way a
# MAGIC presenter's click does: `run_controls.snapshot_review_state` on the next run.
# MAGIC
# MAGIC Storyline at install (pre-close, before month end):
# MAGIC
# MAGIC | Close task | State after the next control run | Why |
# MAGIC |---|---|---|
# MAGIC | CLS-02 User access review | COMPLETE (pre-close) | every PAM exception proposed and approved (four-eyes), task signed off |
# MAGIC | CLS-01 Journal entry review | BLOCKED by JET-01 only | three self-approved journals have proposals awaiting an independent approver: the live demo |
# MAGIC | CLS-03 Data-quality checks | BLOCKED by DQ-01 only | the BR01 bank feed is still behind (a live issue); drift and referential items are dispositioned |
# MAGIC | Everything else | open, about 40% with a preparer's proposal | normal state before month end |
# MAGIC
# MAGIC Idempotent: an item that already has any review action is never touched,
# MAGIC so live activity always wins. `reset=true` (refresh parameter `reset_reviews`)
# MAGIC first clears the active close's review actions and working papers: the demo reset. Runs in `setup` and in the daily `refresh`
# MAGIC (after the lakehouse build, before `run_controls`).

# COMMAND ----------
# MAGIC %run ./_lib

# COMMAND ----------
import uuid

import psycopg
from databricks.sdk import WorkspaceClient

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "fin_recon_observability")
dbutils.widgets.text("raw_volume", "files")
dbutils.widgets.text("lakebase_project", "fin-recon-observability")
dbutils.widgets.text("app_name", "")
dbutils.widgets.text("reset", "false")   # demo reset: clear the active close's review actions first
catalog, schema, raw_volume = get_widget("catalog"), get_widget("schema"), get_widget("raw_volume", "files")
project, app_name = get_widget("lakebase_project"), get_widget("app_name")
reset = get_widget("reset", "false").strip().lower() == "true"
assert catalog and schema and project
FQ = f"`{catalog}`.`{schema}`"
as_of = load_as_of(catalog, schema, raw_volume)
ACTIVE = period_key(*active_period(as_of))

RESOLVE = {
    "PAM-01": ("remediated", "Conflicting role removed by IT Security; compensating review of the user's postings found no issue. Ticket attached."),
    "PAM-02": ("remediated", "Oracle account disabled; removal lag reviewed with HR. No activity after the termination date."),
    "PAM-03": ("adjusted", "Journal re-reviewed and re-approved by an active preparer; shared-credential root cause escalated to IT Security."),
    "PAM-04": ("remediated", "Provisioning request backfilled and approved by the role owner; grant confirmed appropriate."),
    "JET-02": ("explained", "Pre-approval obtained by email before posting; approval evidence attached to the journal."),
    "JET-03": ("explained", "Posted in the cut-off window with controller approval; business rationale documented."),
    "JET-04": ("adjusted", "Duplicate reversed on the posting day; reversal journal attached."),
    "SLR-04": ("explained", "Manual entry to the control account was part of the approved subledger interface correction."),
    "DQ-02": ("remediated", "Feed contract updated for the new Salesforce field; values were captured in rescued data, none lost."),
    "DQ-03": ("adjusted", "Lines on the unmapped account reclassed; chart-of-accounts mapping corrected at source."),
}
PROPOSE_ONLY = {"JET-01": ("adjusted", "Journal to be reversed and re-posted with an independent approver; preparer coached on the delegation rule.")}
NEVER = {"DQ-01"}   # the bank feed outage is live today
GENERIC = {
    "CASH": ("explained", "Matched to the bank advice; timing item that clears on the next statement."),
    "SLR": ("adjusted", "Interface re-run scheduled; correcting entry prepared for review."),
    "FSC": ("adjusted", "Correcting journal prepared to clear the integrity break."),
    "FPA": ("explained", "Driver confirmed with the budget owner."),
    "JET": ("explained", "Business rationale obtained from the preparer; supporting email attached."),
}
SIGNED_TASKS = {"CLS-02": "Access review complete: all exceptions dispositioned and approved; certification evidence on file."}

# COMMAND ----------
# MAGIC %md ## Fictional staff (active finance workers)

# COMMAND ----------
workers = read_scratch(catalog, schema, raw_volume, "workers")
active_staff = workers.filter(pl.col("Termination_Date").is_null())


def staff(job: str) -> list:
    return sorted(active_staff.filter(pl.col("Job_Profile") == job)["Email_Address"].to_list())


preparers = staff("Senior Accountant") or staff("Accountant")
reviewers = staff("Controller")
it_sec = staff("IT Security Engineer") or reviewers
assert preparers and reviewers, "finance staff missing from the workers scratch"

# COMMAND ----------
# MAGIC %md ## Review store: DDL (shared with the app) and grants for the app's role

# COMMAND ----------
w = WorkspaceClient()
endpoint = f"projects/{project}/branches/production/endpoints/primary"
host = w.postgres.get_endpoint(name=endpoint).status.hosts.host
user = w.current_user.me().user_name
token = w.postgres.generate_database_credential(endpoint=endpoint).token
conninfo = f"host={host} port=5432 dbname=databricks_postgres user={user} password={token} sslmode=require"
ddl_text = open(os.path.join(repo_root(), "apps", "audit-workbench", "backend", "review_store.sql")).read()
stmts = [x.strip() for x in "\n".join(l for l in ddl_text.splitlines() if not l.strip().startswith("--")).split(";") if x.strip()]
app_role = None
if app_name:
    try:
        app_role = w.apps.get(app_name).service_principal_client_id
    except Exception as e:  # noqa: BLE001
        print(f"app {app_name} not found ({e}); grants to PUBLIC only")

with psycopg.connect(conninfo, autocommit=True) as conn:
    for st in stmts:
        try:
            conn.execute(st)
        except psycopg.errors.InsufficientPrivilege:
            pass   # created earlier by the app's role; usable through its grants
    if app_role:
        # Tables created here are owned by the deployer: the app's role reads and writes rows, nothing else.
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (app_role,)).fetchone()
        if exists:
            conn.execute(f'GRANT USAGE ON SCHEMA audit TO "{app_role}"')
            conn.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA audit TO "{app_role}"')
        else:
            print(f"app role {app_role} not in Postgres yet (the app's postgres binding creates it on deploy)")
    if reset:
        n = conn.execute("DELETE FROM audit.review_actions WHERE period = %s", (ACTIVE,)).rowcount
        conn.execute("DELETE FROM audit.working_papers")
        print(f"reset: removed {n} review actions for {ACTIVE} and all working papers")
    # Items a real person acted on are never touched. Items with only seeded
    # actions (from an earlier seed) are completed to the storyline.
    state = {r[0]: {"live": r[1], "actions": set(r[2] or [])} for r in conn.execute(
        """SELECT item_key, bool_or(COALESCE((payload->>'seeded')::boolean, false) = false) AS live, array_agg(action)
           FROM audit.review_actions WHERE period = %s GROUP BY item_key""", (ACTIVE,)).fetchall()}
touched = {k for k, v in state.items() if v["live"]}
print(f"review store ready as {user}; active period {ACTIVE}: {len(touched)} items with live activity, "
      f"{len(state) - len(touched)} with seeded actions only")

# COMMAND ----------
# MAGIC %md ## Earlier-this-month activity

# COMMAND ----------
exc = (spark.sql(f"""SELECT exception_id, control_id, entity_code, record_key, is_info, amount_usd
                     FROM {FQ}.gold_control_exceptions WHERE period = '{ACTIVE}'
                     ORDER BY control_id, exception_id""").collect())
now = datetime.now(timezone.utc).replace(tzinfo=None)
day0 = (now - timedelta(days=1)).replace(hour=9, minute=10, second=0, microsecond=0)
rows, counts = [], {"approved": 0, "proposed": 0, "skipped_existing": 0}


def act(item_type, key, action, who, role, disp=None, comment="", at=None, payload=None):
    at = min(at, now - timedelta(minutes=30))   # never in the future
    rows.append((uuid.uuid4().hex, item_type, key, ACTIVE, action, disp, comment,
                 json.dumps({"seeded": True, "source": "seed_review_activity", **(payload or {})}), who, role, at))


for k, x in enumerate(exc):
    cid, eid = x["control_id"], x["exception_id"]
    if eid in touched:
        counts["skipped_existing"] += 1
        continue
    if cid in NEVER:
        continue
    prep = (it_sec if cid.startswith("PAM") else preparers)[k % len((it_sec if cid.startswith("PAM") else preparers))]
    rev = reviewers[(k + 3) % len(reviewers)]
    p_at = day0 + timedelta(minutes=3 * k)
    have = state.get(eid, {}).get("actions", set())
    if cid in RESOLVE:
        if "approve" in have:
            continue
        disp, comment = RESOLVE[cid]
        if "propose" not in have:
            act("exception", eid, "propose", prep, "preparer", disp, comment, p_at, {"control_id": cid})
        act("exception", eid, "approve", rev, "reviewer", disp, "Reviewed evidence; disposition approved.",
            p_at + timedelta(hours=4, minutes=k % 50), {"control_id": cid, "counterpart_email": prep})
        counts["approved"] += 1
    elif cid in PROPOSE_ONLY:
        if "propose" in have:
            continue
        disp, comment = PROPOSE_ONLY[cid]
        act("exception", eid, "propose", prep, "preparer", disp, comment, p_at, {"control_id": cid})
        counts["proposed"] += 1
    elif have:
        continue
    elif not x["is_info"] and int(hashlib.md5(eid.encode()).hexdigest()[:6], 16) % 10 < 4:
        disp, comment = GENERIC.get(cid.split("-")[0], ("explained", "Reviewed with the process owner."))
        act("exception", eid, "propose", prep, "preparer", disp, comment, p_at, {"control_id": cid})
        counts["proposed"] += 1

for j, (task, comment) in enumerate(SIGNED_TASKS.items()):
    key = f"{ACTIVE}|{task}"
    if key not in touched and "signoff" not in state.get(key, {}).get("actions", set()):
        act("close_task", key, "signoff", reviewers[j % len(reviewers)], "reviewer", None, comment,
            day0 + timedelta(hours=7, minutes=20 + j))

if rows:
    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            cur.executemany("""INSERT INTO audit.review_actions (action_id, item_type, item_key, period, action, disposition, comment,
                                 payload, actor_email, actor_role, created_at)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)""", rows)
        conn.commit()
print(f"seeded {len(rows)} actions: {counts}")
dbutils.notebook.exit(json.dumps({"period": ACTIVE, "actions": len(rows), **counts}))

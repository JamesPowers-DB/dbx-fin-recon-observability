# Fin Recon Observability: continuous close on Databricks

Audit Workbench shows a monthly close run as continuous monitoring. Thirty versioned controls run every day over every record from five source systems: Oracle Fusion ERP, Salesforce Billing, Workday, Anaplan, and a bank camt.053 feed. They cover cash, subledger tie-outs, journal-entry testing, privileged access, and statements with FP&A. AI triage drafts a root cause for every exception. Reviewers disposition the exceptions with four-eyes approval and sign off, and the close burndown moves from recorded runs. Days to close falls from a traditional T+8 to T+3, heading for T+1. The final artifact is a set of financial statements whose status turns from DRAFT to FINAL when the controller's GO task completes. The company (Corvane Technologies) and all data are fictional and synthetic.

Lifecycle: enterprise data, automated monitoring, exception detection, AI investigation, evidence capture, human review, reporting (continuous close).

> **Single-schema build.** Everything lives in `${var.catalog}.${var.schema}` (default `fin_recon_observability`) with layer-prefixed tables: `bronze_*`, `silver_*`, `gold_*` (including `gold_mv_*` metric views), `ml_*`, and `meta_*`. The bundle deploys into an existing catalog. Review state for the app lives in a bundle-managed Lakebase project.

## Install: two commands

```bash
# 1) Deploy assets (schema + volume, pipeline, jobs, Lakebase, app, dashboard, alert)
./apps/build_frontends.sh
databricks bundle deploy -t prod --profile <profile> \
  --var catalog=<existing_catalog> \
  --var warehouse_id=<warehouse_id>

# 2) Build and wire everything
databricks bundle run setup -t prod --profile <profile>
```

Find a warehouse id: `databricks warehouses list -o json | jq -r '.[] | "\(.id)\t\(.name)"'`. Use a regular serverless SQL warehouse, since metric view DDL needs one.

`setup` runs:

| Step | Job or task | What it does |
|---|---|---|
| 1 | `generate_data` | Synthesizes source-shaped files for every system into the volume. Plants control exceptions and registers them in `meta_planted_exceptions`. Reconciles to anchors (±2%). |
| 2 | `publish_controls` | Publishes the control library, risk register, and close calendar from `controls/`. Fails if a definition changed without a version bump. |
| 3 | `build_lakehouse` | Full refresh of the Lakeflow pipeline: bronze, silver, gold, control tests, and expectations. The event log is published to `meta_pipeline_event_log`. |
| 4 | `seed_review_activity` | Demo scaffolding. Writes this month's earlier review activity (preparer proposals, reviewer approvals, one task sign-off) into the Lakebase review store. |
| 5 | `run_controls` | First control run. Steps: open_run, publish, review-state sync, a pipeline update that tests the controls, then record_results, AI triage, and the PLT-01 gate. |
| 6 | `apply_metric_views` | Creates the 7 governed metric views and checks the KPI assertions. |
| 7 | `provision_genie` | Creates or refreshes the Genie space by title. |
| 8 | `grant_app_sp` | Grants the app service principal UC access and Genie CAN_RUN. |

The first run takes about 30 minutes. Re-running is safe.

### Why install needs no hand edits
- The app service principal is resolved from the deployed app. Job permissions name it through `${resources.apps.audit_workbench.service_principal_client_id}`.
- The Genie space is keyed by title, and the app resolves its id by title at runtime.
- Catalog, schema, warehouse, Lakebase project, and model endpoints are bundle variables. The app gets them through `config.env` in `resources/apps.yml`.
- The Lakebase database binding gives the app's service principal its Postgres role. The review-store DDL (`apps/audit-workbench/backend/review_store.sql`) runs lazily from the app or from the seed job, whichever connects first.

## Prerequisites
- A workspace with serverless jobs, serverless SQL, Unity Catalog, Lakebase, Databricks Apps, and Foundation Model APIs. The defaults are `databricks-claude-haiku-5-5` for triage and `databricks-claude-sonnet-5-5` for the agent.
- Databricks CLI 0.281 or later, with an authenticated profile.
- An existing UC catalog where you can create a schema and a managed volume, plus rights to create a Genie space and an app.

## What gets created

| Resource | Bundle key | Name |
|---|---|---|
| Schema + volume | `catalog.yml` | `${var.catalog}.${var.schema}` + volume `files` |
| Pipeline | `lakehouse` | `fin-recon-observability-lakehouse-prod` |
| Jobs | `generate_data`, `build_lakehouse`, `run_controls`, `simulate_activity`, `seed_review_activity`, `apply_metric_views`, `provision_genie`, `grant_app_sp`, `setup`, `refresh` | `fin-recon-observability-*-prod` |
| Lakebase project | `audit_lakebase` | `fin-recon-observability` (review actions, working papers, chat sessions) |
| Metric views | `apply_metric_views` | `gold_mv_close`, `gold_mv_control_health`, `gold_mv_exceptions`, `gold_mv_reconciliations`, `gold_mv_journal_entries`, `gold_mv_access_risk`, `gold_mv_financials` |
| Genie space | `provision_genie` | *Fin Recon Observability - Audit & Controls* |
| App | `audit_workbench` | `audit-workbench-prod` |
| Dashboard | `continuous_close` | *Fin Recon Observability - Continuous Close* |
| SQL alert | `critical_open_exceptions` | Critical open exceptions in the active close |

## Verify
```sql
SELECT period, MEASURE(days_to_close) AS days_to_close
FROM <catalog>.fin_recon_observability.gold_mv_close
GROUP BY period ORDER BY period;
```
- **Ledger:** `meta_control_runs` has one row per run, and `gate_result = 'PASS'` means PLT-01 found all planted exceptions.
- **App:** get the URL with `databricks apps get audit-workbench-prod -o json | jq -r .url`.
- **Genie:** open *Fin Recon Observability - Audit & Controls* and ask *"How has days to close trended over the last 12 months?"*
- **Dashboard:** open *Fin Recon Observability - Continuous Close*.
- **Local checks:**
  - `scripts/dev/smoke_api.py` runs every read endpoint against the live schema.
  - `scripts/dev/genie_benchmarks.py` compares Genie answers with the governed SQL.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `catalog` | `main` | Existing catalog. The bundle does not create it. Pass `--var catalog=<name>` on every deploy. |
| `schema` | `fin_recon_observability` | Single schema for every layer |
| `raw_volume` | `files` | Managed volume for source files |
| `warehouse_id` | | Required. Used by the app, the dashboard, and the alert. |
| `lakebase_project` | `fin-recon-observability` | Lakebase project id for the review store |
| `triage_endpoint` | `databricks-claude-haiku-5-5` | Batch `ai_query` triage |
| `agent_endpoint` | `databricks-claude-sonnet-5-5` | Audit Assistant (tool calling) |

App runtime config is the `config.env` block of `resources/apps.yml`. There is no `app.yaml`, so bundle variables and resource ids are substituted at deploy.

## How the checklist stays bound to orchestration
- **One definition per control.** Each control is a YAML definition in `controls/library/`. It names what executes it: a pipeline expectation (`ctl_<id>`), a gold dataset, or a job task. `controls/validate_controls.py` checks every binding against the SQL.
- **Execution.** `run_controls` is the only job that executes controls. It stamps every result with the job run, the task run, and the pipeline update that tested it. The update is resolved from the event log, and the results go to the immutable ledgers `meta_control_results` and `meta_control_exception_log`.
- **Close tasks.** A close task completes only when its controls are PASS or RESOLVED in a recorded run and its sign-off exists. The app writes human actions to Lakebase only. They reach Unity Catalog one way, on the next run (`snapshot_review_state`).

## Advanced
```bash
databricks bundle run run_controls        -t prod   # re-test every control (about 10 minutes)
databricks bundle run simulate_activity   -t prod   # append an intraday batch, then run the controls
databricks bundle run refresh -t prod --params reset_reviews=true   # demo reset: regenerate, clear review actions, re-seed
databricks bundle run audit_workbench     -t prod   # redeploy the app's code after a bundle deploy
databricks bundle run build_lakehouse     -t prod   # full refresh after regenerating source files
databricks bundle run apply_metric_views  -t prod
databricks bundle run provision_genie     -t prod
databricks bundle run grant_app_sp        -t prod
python3 controls/validate_controls.py              # library, bindings, and close calendar (local)
```

`refresh` runs on weekdays at 05:00 UTC. It rolls the data forward to yesterday, does a full build, re-seeds the earlier activity for new exceptions, runs the controls, and validates the output (freshness, a gate PASS today, close status from the latest run). It never produces future-dated rows. Live review actions survive a scheduled refresh; `reset_reviews=true` clears them for a clean demo.

`bundle deploy` uploads the app's source but does not restart a running app on new code: run `databricks bundle run audit_workbench -t prod` after deploying app changes.

### Adding a period
Periods roll forward automatically to the current month. To change the shape of a quarter, edit `CONSOL_QUARTERS` in `data/generators/01_period_anchors_seed.py`, then run `generate_data` and a full refresh.

### Changing a control
Edit its YAML in `controls/library/` and bump `version`. The next `run_controls` publishes the new version. The old version stays in `meta_control_library`, and results record the version they ran.

## Teardown
```bash
databricks bundle destroy -t prod
# The catalog is not bundle-managed and is left intact.
# The Genie space is provisioned outside the bundle: delete it in the Genie UI or with
# databricks api delete /api/2.0/genie/spaces/<id>
```

## Development notes
- Local scripts run with `uv`. On a network that requires a package mirror, set `UV_INDEX_URL=<your PyPI mirror>`, and add `--native-tls` if it uses a corporate certificate.
- Run metric view DDL and other indentation-sensitive SQL with `scripts/dev/run_sql.py`, which sends it verbatim through the Statement Execution API.
- Current Claude endpoints reject `temperature` and `responseFormat` structured output. Triage therefore uses a JSON prompt contract parsed with `from_json`. Reasoning tokens count against `max_tokens`, so the budgets are generous.

## Repository layout
```
dbx-fin-recon-observability/
├── databricks.yml       bundle root, variables, prod target
├── resources/           catalog, pipeline, apps, dashboards, lakebase, alerts
├── jobs/                one job per file + setup / refresh orchestrators
├── controls/            control library (YAML), risk register, close calendar, runtime tasks of run_controls
├── pipelines/<domain>/{bronze,silver,gold}/*.sql   core, documents, m1_cash .. m5_statements, controls spine
├── ai/                  triage prompt and job task
├── data/generators/     anchor-driven synthetic source-file generators, seed and simulate drivers
├── metric_views/        apply_metric_views.py (7 views + KPI assertions)
├── genie/               genie_space_def.py + job + CLI twin
├── dashboards/          continuous_close.lvdash.json + builder
├── scripts/             grant_app_sp_job.py, validators, dev tools
└── apps/audit-workbench/  FastAPI + React app (9 pages)
```

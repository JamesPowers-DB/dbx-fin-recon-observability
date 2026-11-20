// Platform map content: business lifecycle -> deployed assets -> Databricks features.
// Static description of the demo. Live status per node comes from
// /api/architecture/status (see statusFor() in pages/Architecture.tsx).
import type { NavOpts, PageId } from "../App";

export type Tier = "live" | "config" | "roadmap";
export const TIER_LABEL: Record<Tier, string> = { live: "Live in demo", config: "Configuration", roadmap: "Roadmap" };
export const TIER_NOTE: Record<Tier, string> = {
  live: "Deployed by this bundle and running in the workspace.",
  config: "Platform capability not deployed here; a configuration or integration step for a pilot.",
  roadmap: "Not built; a reuse of the same pattern proposed for a later phase.",
};

export interface Stage { id: string; n: number; label: string; caption: string; page: PageId; tab?: string; }

export const STAGES: Stage[] = [
  { id: "enterprise", n: 1, label: "Enterprise data", caption: "ERP, billing, HR, plan, bank, documents", page: "lineage" },
  { id: "monitoring", n: 2, label: "Automated monitoring", caption: "every control, every run, full population", page: "checklist" },
  { id: "detection", n: 3, label: "Exception detection", caption: "NEW, RECURRING, RESOLVED per run", page: "exceptions" },
  { id: "ai", n: 4, label: "AI investigation", caption: "triage and an investigator agent", page: "assistant" },
  { id: "evidence", n: 5, label: "Evidence capture", caption: "source rows, parsed PDFs, policy", page: "exceptions" },
  { id: "review", n: 6, label: "Human review", caption: "four-eyes dispositions and sign-offs", page: "exceptions" },
  { id: "reporting", n: 7, label: "Reporting", caption: "continuous close and days to close", page: "close" },
];

export interface MapNode {
  id: string;
  kind: "asset" | "feature";
  label: string;
  sub: string;                 // one line under the label
  stage?: string;              // assets: lifecycle column
  group?: string;              // features: band group
  tier: Tier;
  does: string;                // what it does in the close
  where: { page: PageId; opts?: NavOpts; label: string }[];
  uses?: string[];             // assets: feature ids
  probe?: string;              // key into the status binder
  code?: string[];             // repo paths that define it
}

export const ASSETS: MapNode[] = [
  {
    id: "sources", kind: "asset", stage: "enterprise", tier: "live", probe: "sources",
    label: "Source systems in a UC volume", sub: "Oracle, Salesforce, Workday, Anaplan, bank, close tool, PDFs",
    does: "Source-shaped files for Corvane Technologies land in one Unity Catalog volume, one folder per system: Oracle Fusion ERP (GL, AP, users and roles, CSV), Salesforce Billing (invoices and payments, JSON), Workday (workers and payroll, Parquet), Anaplan (budget and forecast, CSV), the bank feed (camt.053 XML), the prior close-tool export (CSV) and evidence PDFs. Every control test starts from these rows.",
    where: [{ page: "lineage", label: "Data Quality & Lineage" }],
    uses: ["uc", "pipelines", "connect"], code: ["data/generators/", "resources/catalog.yml"],
  },
  {
    id: "refresh", kind: "asset", stage: "enterprise", tier: "live", probe: "refresh",
    label: "Daily refresh and setup", sub: "scheduled roll-forward, two-command install",
    does: "The refresh job runs every weekday: it rolls the source data forward to yesterday, rebuilds the lakehouse, and runs the controls, so monitoring is continuous without anyone starting it. The setup job is the two-command install.",
    where: [{ page: "close", label: "Close Cockpit" }],
    uses: ["jobs", "dabs"], code: ["jobs/refresh.yml", "jobs/setup.yml"],
  },
  {
    id: "library", kind: "asset", stage: "monitoring", tier: "live", probe: "library",
    label: "Control library as code", sub: "versioned YAML in Git, published per run",
    does: "Thirty controls, the risk register and the close calendar are YAML files in Git. Each control names its population, tolerance, owner, policy and the exact pipeline dataset, expectation or job task that executes it. publish_controls validates the bindings and refuses a changed definition without a version bump.",
    where: [{ page: "checklist", label: "Audit Checklist" }, { page: "reporting", label: "Risk register" }],
    uses: ["uc", "dabs"], code: ["controls/library/", "controls/risk_register.yml", "controls/close_calendar.yml"],
  },
  {
    id: "pipeline", kind: "asset", stage: "monitoring", tier: "live", probe: "pipeline",
    label: "Lakeflow pipeline", sub: "bronze, silver, gold, WARN expectations",
    does: "One declarative pipeline ingests every source, conforms it, and computes each module's control tests over the full population. Five controls run as WARN expectations so failing rows are kept and counted; the event log is published to Unity Catalog and feeds the Sankey.",
    where: [{ page: "lineage", label: "Data Quality & Lineage" }, { page: "modules", label: "Recons & Testing" }],
    uses: ["pipelines", "uc", "aifn"], code: ["pipelines/", "resources/pipeline.yml"],
  },
  {
    id: "run_controls", kind: "asset", stage: "monitoring", tier: "live", probe: "run_controls",
    label: "run_controls job", sub: "open run, sync reviews, test, record, triage, gate",
    does: "The only job that executes controls. It opens a ledger row, publishes the library, syncs review actions from Lakebase, runs a pipeline update, records results and close status, triages new exceptions with AI, and fails the run if the monitoring-integrity gate (PLT-01) finds a gap. The app's Re-run button starts it.",
    where: [{ page: "close", label: "Close Cockpit run stepper" }, { page: "checklist", label: "Audit Checklist" }],
    uses: ["jobs", "pipelines", "uc"], code: ["jobs/run_controls.yml", "controls/runtime/"],
  },
  {
    id: "ledger", kind: "asset", stage: "detection", tier: "live", probe: "ledger",
    label: "Results ledger and exception log", sub: "immutable snapshot per run",
    does: "Every run writes an immutable snapshot of each control result per entity and period, stamped with the job run, task run and pipeline update that produced it, plus an exception log that marks each exception NEW, RECURRING or RESOLVED against the previous run.",
    where: [{ page: "checklist", label: "Audit Checklist" }, { page: "exceptions", label: "Exceptions & Review" }],
    uses: ["uc"], code: ["controls/runtime/record_results.py"],
  },
  {
    id: "alert", kind: "asset", stage: "detection", tier: "live", probe: "alert",
    label: "SQL alert", sub: "critical open exceptions, three times a day",
    does: "A SQL alert over the exceptions metric view fires when a critical exception is open in the active close, so escalation does not depend on someone opening the app.",
    where: [{ page: "exceptions", label: "Exceptions & Review" }],
    uses: ["alerts", "mv"], code: ["resources/alerts.yml"],
  },
  {
    id: "triage", kind: "asset", stage: "ai", tier: "live", probe: "triage",
    label: "AI triage", sub: "ai_query on every new exception",
    does: "A governed SQL statement in run_controls sends each new exception, its control objective, the policy clause and any parsed evidence to a Claude endpoint and stores root cause, severity, confidence, a draft finding and whether a human must decide. Every output is labelled AI-generated; a person still dispositions.",
    where: [{ page: "exceptions", label: "Exceptions & Review" }],
    uses: ["aifn", "fmapi", "uc"], code: ["ai/triage_exceptions.sql"],
  },
  {
    id: "agent", kind: "asset", stage: "ai", tier: "live", probe: "agent",
    label: "Investigator agent", sub: "tool calling on Model Serving, Genie fallback",
    does: "The Audit Assistant calls tools that read the same governed tables the pages use (close status, checklist, exception, source records, evidence), saves working papers, and asks Genie for open-ended analytics. Tool calls and the SQL they ran are shown and persisted. It never approves anything.",
    where: [{ page: "assistant", label: "Audit Assistant" }],
    uses: ["fmapi", "genie", "lakebase", "apps"], code: ["apps/audit-workbench/backend/routers/assistant.py"],
  },
  {
    id: "evidence", kind: "asset", stage: "evidence", tier: "live", probe: "documents",
    label: "Evidence parsing", sub: "ai_parse_document on invoices and bank advices",
    does: "Invoice and bank-advice PDFs are parsed inside the pipeline and their fields are matched to the AP and bank records, so the evidence pack for an exception is assembled from source rows, documents and the governing policy section without an evidence request.",
    where: [{ page: "exceptions", label: "Exceptions & Review evidence pack" }],
    uses: ["aifn", "uc", "pipelines"], code: ["pipelines/documents/"],
  },
  {
    id: "lakebase", kind: "asset", stage: "review", tier: "live", probe: "lakebase",
    label: "Lakebase review store", sub: "append-only actions, working papers, chat",
    does: "Human actions (propose, approve, reject, explain, acknowledge, sign off) are appended to a Postgres table in Lakebase. Four-eyes is enforced server-side. Each control run copies the actions one way into Unity Catalog, so the next results reflect the review.",
    where: [{ page: "exceptions", label: "Exceptions & Review" }, { page: "statements", opts: { tab: "variances" }, label: "Variance review" }],
    uses: ["lakebase", "uc"], code: ["apps/audit-workbench/backend/review_store.sql", "controls/runtime/snapshot_review_state.py"],
  },
  {
    id: "app", kind: "asset", stage: "review", tier: "live", probe: "app",
    label: "Audit Workbench app", sub: "Databricks App, on-behalf-of the user",
    does: "This app. Reads Unity Catalog as the signed-in user, so grants and column masks apply to the person, not to a service account. Writes only to Lakebase. Starts control runs through the app's service principal and records who asked.",
    where: [{ page: "close", label: "Close Cockpit" }],
    uses: ["apps", "uc", "lakebase"], code: ["apps/audit-workbench/", "resources/apps.yml"],
  },
  {
    id: "close", kind: "asset", stage: "reporting", tier: "live", probe: "close",
    label: "Close status and days to close", sub: "derived on every control run",
    does: "Each close task is bound to controls and a sign-off. When its controls are green and the sign-off exists, the task completes; when they fail again it reopens. Days to close is the business day after month end on which the controller's GO task completes.",
    where: [{ page: "close", label: "Close Cockpit burndown" }],
    uses: ["uc", "mv", "jobs"], code: ["controls/close_calendar.yml"],
  },
  {
    id: "metric_views", kind: "asset", stage: "reporting", tier: "live", probe: "metric_views",
    label: "UC metric views", sub: "one definition per KPI",
    does: "Seven governed metric views define every headline number once: days to close, control pass rate, open exceptions, unreconciled amount, journal flags, access risk, statement lines. The app, the dashboard, Genie and the agent all query them.",
    where: [{ page: "reporting", label: "Risk & Reporting" }],
    uses: ["mv", "uc"], code: ["metric_views/apply_metric_views.py"],
  },
  {
    id: "dashboard", kind: "asset", stage: "reporting", tier: "live", probe: "dashboard",
    label: "AI/BI dashboard", sub: "Continuous Close",
    does: "A published dashboard for the controller and audit committee: days to close by period against the traditional baseline and target, pre-close completion, pass rate by module, exceptions by severity, unreconciled amounts.",
    where: [{ page: "close", label: "Close Cockpit" }],
    uses: ["dashboards", "mv"], code: ["dashboards/continuous_close.lvdash.json"],
  },
  {
    id: "genie", kind: "asset", stage: "reporting", tier: "live", probe: "genie",
    label: "Genie space", sub: "questions in plain language, SQL shown",
    does: "A Genie space over the seven metric views answers questions such as how days to close has trended or which key controls failed in the latest run, and shows the SQL it generated. The agent uses it as its fallback tool.",
    where: [{ page: "assistant", label: "Audit Assistant" }],
    uses: ["genie", "mv"], code: ["genie/genie_space_def.py"],
  },
];

export const FEATURE_GROUPS: { id: string; label: string }[] = [
  { id: "govern", label: "Govern" },
  { id: "build", label: "Build and run" },
  { id: "ai", label: "AI" },
  { id: "serve", label: "Serve" },
  { id: "next", label: "Next steps" },
];

export const FEATURES: MapNode[] = [
  {
    id: "uc", kind: "feature", group: "govern", tier: "live", probe: "uc",
    label: "Unity Catalog", sub: "governance, lineage, tags, column mask",
    does: "One schema holds every layer. Lineage traces an exception back to source files, tags mark PII and confidential tables, a column mask hides personal names from users outside the PII group, and grants apply to the person through on-behalf-of access.",
    where: [{ page: "lineage", label: "Data Quality & Lineage" }, { page: "modules", opts: { tab: "access" }, label: "Access tab (masked names)" }],
  },
  {
    id: "dabs", kind: "feature", group: "govern", tier: "live", probe: "dabs",
    label: "Declarative Automation Bundles", sub: "the whole demo as one bundle",
    does: "Pipeline, jobs, app, dashboard, alert and the Lakebase project are declared in one bundle and installed with two commands. The control library ships in the same repository.",
    where: [{ page: "architecture", opts: { tab: "workflow" }, label: "Audit workflow" }],
  },
  {
    id: "pipelines", kind: "feature", group: "build", tier: "live", probe: "pipelines",
    label: "Lakeflow Declarative Pipelines", sub: "expectations and the event log",
    does: "SQL pipelines with expectations that keep failing rows (WARN) and an event log published as a table: rows written, expectation pass and fail, flow lineage per update. That log is the observability layer.",
    where: [{ page: "lineage", label: "Data Quality & Lineage" }],
  },
  {
    id: "jobs", kind: "feature", group: "build", tier: "live", probe: "jobs",
    label: "Lakeflow Jobs", sub: "schedules, on-demand runs, task values",
    does: "run_controls, refresh, simulate and setup are jobs. Each run's id, task run ids and the pipeline update it triggered are stamped on the results, which is what binds the checklist to orchestration.",
    where: [{ page: "checklist", label: "Audit Checklist" }],
  },
  {
    id: "aifn", kind: "feature", group: "ai", tier: "live", probe: "aifn",
    label: "AI Functions", sub: "ai_query, ai_parse_document",
    does: "AI runs inside governed SQL: ai_parse_document extracts invoice fields in the pipeline and ai_query triages exceptions in the job, with no separate service to operate.",
    where: [{ page: "exceptions", label: "Exceptions & Review" }],
  },
  {
    id: "fmapi", kind: "feature", group: "ai", tier: "live", probe: "fmapi",
    label: "Foundation Model APIs", sub: "pay-per-token Claude endpoints",
    does: "Claude endpoints on Model Serving power the batch triage, the investigator agent, variance explanation drafts and the AI status summary. Calls run as the user.",
    where: [{ page: "assistant", label: "Audit Assistant" }],
  },
  {
    id: "lakebase", kind: "feature", group: "serve", tier: "live", probe: "lakebase",
    label: "Lakebase Postgres", sub: "operational state next to the lakehouse",
    does: "A managed Postgres project holds the app's transactional state (review actions, working papers, chat). It is declared in the bundle and synced one way into Unity Catalog.",
    where: [{ page: "exceptions", label: "Exceptions & Review" }],
  },
  {
    id: "mv", kind: "feature", group: "serve", tier: "live", probe: "metric_views",
    label: "Metric views", sub: "governed KPIs in Unity Catalog",
    does: "KPIs defined once in YAML with display names, synonyms and formats, queried with MEASURE() by the app, dashboard, Genie and the alert.",
    where: [{ page: "reporting", label: "Risk & Reporting" }],
  },
  {
    id: "dashboards", kind: "feature", group: "serve", tier: "live", probe: "dashboard",
    label: "AI/BI Dashboards", sub: "published, shareable",
    does: "The Continuous Close dashboard is a bundle resource bound to the metric views.",
    where: [{ page: "close", label: "Close Cockpit" }],
  },
  {
    id: "genie", kind: "feature", group: "serve", tier: "live", probe: "genie",
    label: "AI/BI Genie", sub: "natural-language analytics",
    does: "A Genie space provisioned by a job from a definition in Git, with instructions, example SQL and benchmarks.",
    where: [{ page: "assistant", label: "Audit Assistant" }],
  },
  {
    id: "alerts", kind: "feature", group: "serve", tier: "live", probe: "alert",
    label: "SQL alerts", sub: "scheduled conditions",
    does: "Alerts evaluate a metric-view query on a schedule and notify subscribers.",
    where: [{ page: "exceptions", label: "Exceptions & Review" }],
  },
  {
    id: "apps", kind: "feature", group: "serve", tier: "live", probe: "app",
    label: "Databricks Apps", sub: "custom app with on-behalf-of auth",
    does: "Hosts this FastAPI and React app inside the workspace with the user's identity, the warehouse, the jobs, Lakebase and the model endpoint as declared resources.",
    where: [{ page: "close", label: "Close Cockpit" }],
  },
  {
    id: "connect", kind: "feature", group: "next", tier: "config",
    label: "Lakeflow Connect", sub: "managed Salesforce and Workday ingestion",
    does: "Managed connectors replace the synthetic Salesforce and Workday files with live ingestion; database sources can use change data capture or federation. The bronze tables keep their names, so nothing downstream changes.",
    where: [{ page: "lineage", label: "Data Quality & Lineage" }],
  },
  {
    id: "sharing", kind: "feature", group: "next", tier: "config",
    label: "Delta Sharing", sub: "share results without copies",
    does: "Selected results (for example the SOX status pack tables) can be shared with external auditors or other functions without extracts, under the same governance.",
    where: [{ page: "reporting", label: "Risk & Reporting" }],
  },
  {
    id: "triggers", kind: "feature", group: "next", tier: "config",
    label: "Table-update and file-arrival triggers", sub: "event-driven control runs",
    does: "run_controls can start when a source table changes or a file arrives, in addition to the daily schedule and the app's button.",
    where: [{ page: "close", label: "Close Cockpit" }],
  },
  {
    id: "supervisor", kind: "feature", group: "next", tier: "config",
    label: "Agent Bricks supervisor", sub: "multi-agent collaboration",
    does: "The triage step, the investigator and a reviewer agent can be composed under a supervisor agent, each with its own tools and evaluation.",
    where: [{ page: "assistant", label: "Audit Assistant" }],
  },
  {
    id: "reuse", kind: "feature", group: "next", tier: "roadmap",
    label: "Reuse beyond the close", sub: "engineering governance, product readiness",
    does: "The same pattern (versioned controls bound to datasets, a run ledger, evidence and sign-off) applies to engineering governance milestones and product quality readiness reviews. Not built in this demo.",
    where: [{ page: "architecture", opts: { tab: "coverage" }, label: "Briefing coverage" }],
  },
];

export const ALL_NODES: MapNode[] = [...ASSETS, ...FEATURES];
export const NODE_BY_ID: Record<string, MapNode> = Object.fromEntries(
  ALL_NODES.map((n) => [`${n.kind}:${n.id}`, n]),
);

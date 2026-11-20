// Audit workflow parity: the same audit steps, and where the work runs in this demo.
// Copy is neutral and factual: it describes how GRC platforms typically organise a
// step and which Databricks asset does it here. Review before any customer use.
import type { NavOpts, PageId } from "../App";

/** The only place the comparison label is defined. */
export const GRC_LABEL = "GRC platforms (e.g., Workiva, Optro)";

export const PARITY_NOTE =
  `This comparison describes where each step of the audit workflow runs. It does not assess ${GRC_LABEL}; ` +
  "product capabilities vary by edition and configuration. Review the wording before customer use.";

export interface ParityStep {
  id: string;
  step: string;
  grc: string;          // how a GRC platform typically organises the step
  databricks: string;   // how this demo does it
  assets: string[];     // concrete assets (files, tables, jobs)
  data: string;         // where the data the step depends on lives
  page: PageId;
  opts?: NavOpts;
  pageLabel: string;
}

export const PARITY: ParityStep[] = [
  {
    id: "plan", step: "Plan and scope",
    grc: "Audit plans, risk assessments and testing calendars are maintained as records in the GRC application, often linked to a risk and control matrix.",
    databricks: "The risk register links each risk to its controls and a key risk indicator. The close calendar sets every task's due day, dependencies and sign-off role. Both are versioned YAML in Git and published to Unity Catalog on every run.",
    assets: ["controls/risk_register.yml", "controls/close_calendar.yml", "publish_controls"],
    data: "Unity Catalog: meta_risk_register, meta_close_calendar",
    page: "reporting", pageLabel: "Risk & Reporting",
  },
  {
    id: "document", step: "Document controls",
    grc: "Control narratives, owners, frequencies and assertions are documented in forms within the application.",
    databricks: "Each control is a YAML definition with objective, assertions, owner, frequency, tolerance, policy reference and the dataset, expectation or job task that executes it. A changed definition without a version bump fails publication.",
    assets: ["controls/library/*.yml", "meta_control_library", "gold_dim_control"],
    data: "Git and Unity Catalog",
    page: "checklist", pageLabel: "Audit Checklist",
  },
  {
    id: "evidence", step: "Request evidence",
    grc: "Evidence requests are sent to control owners, who upload documents or exports to the request.",
    databricks: "Evidence is assembled from the data: the source rows behind an exception (journal lines, bank entries, AP invoices, user access), invoice and bank-advice PDFs parsed with ai_parse_document, and the governing policy section.",
    assets: ["gold_exception_evidence", "silver_document_fields", "/Volumes/.../docs/"],
    data: "Unity Catalog tables and volume",
    page: "exceptions", pageLabel: "Exceptions & Review",
  },
  {
    id: "test", step: "Test controls",
    grc: "Testers record test steps and results for the items selected for testing, often working from data exported out of source systems.",
    databricks: "run_controls tests every control against the full population in a pipeline update and writes an immutable result per control, entity and period, stamped with the job run and pipeline update that produced it.",
    assets: ["run_controls job", "Lakeflow pipeline", "meta_control_results"],
    data: "Unity Catalog, next to the source data",
    page: "checklist", pageLabel: "Audit Checklist",
  },
  {
    id: "issues", step: "Manage issues",
    grc: "Exceptions and findings are logged as issues with owners, ratings and workflow states.",
    databricks: "Every exception is a row with a stable id, AI triage (root cause, severity, draft finding) and a review state. The exception log marks each one NEW, RECURRING or RESOLVED per run; a SQL alert escalates critical items.",
    assets: ["gold_control_exceptions", "ml_exception_triage", "meta_control_exception_log", "SQL alert"],
    data: "Unity Catalog; review actions in Lakebase",
    page: "exceptions", pageLabel: "Exceptions & Review",
  },
  {
    id: "remediate", step: "Track remediation",
    grc: "Remediation plans and due dates are tracked on the issue until it is closed.",
    databricks: "A preparer proposes a disposition (explained, adjusted, remediated, deficiency) and a different reviewer approves it. The next control run applies the approval: the control moves to RESOLVED or stays FAIL, and the close task follows.",
    assets: ["audit.review_actions (Lakebase)", "snapshot_review_state", "silver_review_status"],
    data: "Lakebase, synced one way to Unity Catalog",
    page: "exceptions", pageLabel: "Exceptions & Review",
  },
  {
    id: "signoff", step: "Sign off",
    grc: "Reviewers sign off tests and workpapers in the application; sign-offs are recorded on the record.",
    databricks: "Control and close-task sign-offs are bound to the control run they attest. A newer run marks a sign-off superseded until it is re-attested. Four-eyes is enforced by the server, not the browser.",
    assets: ["audit.review_actions", "meta_close_task_status"],
    data: "Lakebase and Unity Catalog",
    page: "checklist", pageLabel: "Audit Checklist",
  },
  {
    id: "report", step: "Report",
    grc: "Status reports and dashboards are produced from the application's records, often with exports to presentation tools.",
    databricks: "The SOX status pack, the risk register with live KRIs, the financial statements and the Continuous Close dashboard all read the same governed metric views; an AI-drafted summary cites only those numbers.",
    assets: ["gold_mv_* metric views", "AI/BI dashboard", "Genie space"],
    data: "Unity Catalog metric views",
    page: "reporting", pageLabel: "Risk & Reporting",
  },
];

/** What changes when the workflow runs on the data platform (shown above the table). */
export const WHERE_IT_RUNS: { label: string; grc: string; databricks: string }[] = [
  { label: "Population", grc: "Set by the testing approach, often a sample", databricks: "Every record, every run" },
  { label: "Evidence", grc: "Typically requested from control owners and uploaded", databricks: "Assembled from source rows and parsed documents" },
  { label: "Frequency", grc: "Set by the testing cycle", databricks: "Daily schedule and on demand" },
  { label: "Traceability", grc: "Links between records in the application", databricks: "Job run, pipeline update, dataset and source row ids" },
];

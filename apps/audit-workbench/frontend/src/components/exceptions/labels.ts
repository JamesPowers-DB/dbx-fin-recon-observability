// Display labels for exception review. Edit copy here, not in components.

export const MODULE_LABEL: Record<string, string> = {
  M1: "M1 Cash", M2: "M2 Subledger", M3: "M3 Journals", M4: "M4 Access", M5: "M5 Statements & FP&A", DQ: "Data quality",
};

export const ROOT_CAUSE_LABEL: Record<string, string> = {
  timing: "Timing", interface_failure: "Interface failure", missing_evidence: "Missing evidence", data_quality: "Data quality",
  segregation_of_duties: "Segregation of duties", unauthorized_activity: "Unauthorized activity", process_gap: "Process gap",
  valuation_or_estimate: "Valuation or estimate", potential_fraud: "Potential fraud", other: "Other",
};

export const DISPOSITIONS: { value: string; label: string; hint: string }[] = [
  { value: "explained", label: "Explained", hint: "Legitimate item; business rationale documented." },
  { value: "adjusted", label: "Adjusted", hint: "Correcting entry posted or prepared." },
  { value: "remediated", label: "Remediated", hint: "Root cause fixed (access removed, interface re-run)." },
  { value: "false_positive", label: "False positive", hint: "The rule matched a legitimate pattern." },
  { value: "deficiency", label: "Deficiency", hint: "Control failure to report in the SOX pack." },
];
export const DISPOSITION_LABEL: Record<string, string> = Object.fromEntries(DISPOSITIONS.map((d) => [d.value, d.label]));

export const STATUS_FILTERS = [
  { value: "open", label: "Needs action" },
  { value: "proposed", label: "Awaiting approval" },
  { value: "approved", label: "Approved" },
  { value: "all", label: "All" },
];

export const ACTION_LABEL: Record<string, string> = {
  propose: "Proposed disposition", approve: "Approved", reject: "Rejected", reopen: "Reopened",
  explain: "Explained", acknowledge: "Acknowledged", signoff: "Signed off",
};

export const SOURCE_LABEL: Record<string, string> = {
  close_tool: "Legacy close tool", audit_workbench: "Audit Workbench",
};

export const SOURCE_TABLE_LABEL: Record<string, string> = {
  journal_lines: "GL journal lines", bank_entry: "Bank entry (camt.053)", ap_invoice: "AP invoice (Oracle)",
  user_access: "User access (Workday x Oracle)", tieout: "Reconciliation tie-out", variance: "Variance line",
  integrity: "Statement integrity",
};

export function shortId(id: string | null | undefined, n = 10): string {
  return id ? id.slice(0, n) : "—";
}

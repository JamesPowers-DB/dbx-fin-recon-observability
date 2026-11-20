// The operating-model shift the demo argues for: the same assurance work, run
// on the full population inside the close instead of on samples after it.
// Figures come from the close summary and the SOX pack (governed measures).
import React from "react";
import { getCloseSummary } from "../../api";
import { Async, DataTable, monoCaption, useApi } from "../ui";
import { fmtInt } from "../../format";

const t = (v: number | null | undefined) => (v == null ? "—" : `T+${Math.round(v)}`);

export function OperatingModel({ recordsTested, sample }: { recordsTested?: number | null; sample?: number | null }) {
  const s = useApi(getCloseSummary);
  return (
    <Async state={s} height={160}>
      {(d) => {
        const rows = [
          { aspect: "Testing scope", before: `Samples per control (${fmtInt(sample ?? d.traditional_sample)} items in total)`,
            after: `Every record, every day (${fmtInt(recordsTested ?? d.records_tested)} records in the latest run)` },
          { aspect: "When controls run", before: "Quarterly fieldwork after the close", after: "Daily refresh plus on-demand runs during the close" },
          { aspect: "Evidence", before: "Requested from process owners, exported to spreadsheets",
            after: "Assembled from source rows, parsed documents and the run ledger" },
          { aspect: "Exception triage", before: "Manual first pass by the tester", after: "AI triage on every exception; a person approves each disposition (four-eyes)" },
          { aspect: "Lines of defense", before: "Management and Internal Audit work from separate extracts",
            after: "Management monitoring and independent assurance read the same governed data, in separate lanes" },
          { aspect: "Days to close", before: `${t(d.days_to_close_traditional)} (FY2025 average)`,
            after: `${t(d.days_to_close_last)} last close; projected ${t(d.projected_days_to_close)}; north star T+${d.north_star_days_to_close}` },
          { aspect: "Audit tooling", before: "Separate GRC application, data copied in", after: "Workflow runs where the data and the controls run" },
        ];
        return (
          <>
            <DataTable rowKey={(r) => r.aspect} rows={rows} columns={[
              { key: "aspect", label: "Aspect", width: 170, render: (r) => <strong>{r.aspect}</strong> },
              { key: "before", label: "Traditional close and audit" },
              { key: "after", label: "Continuous close on Databricks" },
            ]} />
            <div style={{ ...monoCaption, marginTop: 8 }}>
              Figures from the close and control-health metric views for the active close. The comparison describes where the work runs.
            </div>
          </>
        );
      }}
    </Async>
  );
}

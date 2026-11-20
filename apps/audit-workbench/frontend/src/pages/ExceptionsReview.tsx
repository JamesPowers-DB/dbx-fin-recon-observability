// Exceptions & Review: the queue of everything the control tests found, with AI
// triage, and the four-eyes review of each item. Exceptions, triage and evidence
// come from Unity Catalog; review actions go to Lakebase and are applied to the
// control results by the next run_controls run.
import React, { useMemo, useState } from "react";
import type { PageProps } from "../App";
import { getExceptions } from "../api";
import type { ExceptionRow } from "../types";
import {
  AiBadge, Async, DataTable, Grid, Mono, Page, Section, Select, StatusBadge, activePeriod, monoCaption, periodOptions, useApi,
  type Column,
} from "../components/ui";
import { PageHero } from "../components/layout/PageHero";
import { StatTile } from "../components/StatTile";
import { Pill, SegSelect } from "../components/Buttons";
import { fmtInt, fmtUSD } from "../format";
import { ExceptionDrawer } from "../components/exceptions/ExceptionDrawer";
import { MODULE_LABEL, ROOT_CAUSE_LABEL, STATUS_FILTERS } from "../components/exceptions/labels";

const SEV_RANK: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };

export function ExceptionsReview({ onNavigate, nav, user }: PageProps) {
  const active = activePeriod();
  const [period, setPeriod] = useState(active);
  const [module, setModule] = useState<string>(nav.filter?.module ?? "");
  const [control, setControl] = useState<string>(nav.filter?.control ?? "");
  const [status, setStatus] = useState<string>(nav.filter?.status ?? (nav.focusId ? "all" : "open"));
  const [focus, setFocus] = useState<string | null>(nav.focusId ?? null);
  const st = useApi(() => getExceptions({ period, limit: 2000 }), [period]);

  const all = st.data?.rows ?? [];
  const modules = useMemo(() => Array.from(new Set(all.map((r) => r.module))).sort(), [all]);
  const controls = useMemo(() => Array.from(new Set(all.filter((r) => !module || r.module === module).map((r) => r.control_id))).sort(), [all, module]);
  const rows = useMemo(() => all
    .filter((r) => !module || r.module === module)
    .filter((r) => !control || r.control_id === control)
    .filter((r) => status === "all" ? true : status === "open" ? r.disposition_status !== "approved" : r.disposition_status === status)
    .sort((a, b) => Number(a.is_info) - Number(b.is_info)
      || (SEV_RANK[a.ai_severity ?? ""] ?? 9) - (SEV_RANK[b.ai_severity ?? ""] ?? 9)
      || (b.amount_usd ?? 0) - (a.amount_usd ?? 0)), [all, module, control, status]);

  const counts = useMemo(() => ({
    total: all.length,
    open: all.filter((r) => r.disposition_status === "open" || r.disposition_status === "rejected").length,
    proposed: all.filter((r) => r.disposition_status === "proposed").length,
    approved: all.filter((r) => r.disposition_status === "approved").length,
    high: all.filter((r) => r.disposition_status !== "approved" && (r.ai_severity === "critical" || r.ai_severity === "high")).length,
    pending: all.filter((r) => r.pending_sync).length,
    triaged: all.filter((r) => r.ai_severity).length,
  }), [all]);

  const columns: Column<ExceptionRow>[] = [
    { key: "sev", label: <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>Severity <AiBadge text="AI" /></span>, width: 120,
      render: (r) => r.ai_severity ? <StatusBadge status={r.ai_severity} small />
        : <Mono dim>{r.rule_severity ? `rule: ${r.rule_severity}` : "not triaged"}</Mono> },
    { key: "control", label: "Control", render: (r) => (
      <div style={{ minWidth: 220 }}>
        <button onClick={(e) => { e.stopPropagation(); onNavigate("checklist", { focusId: r.control_id }); }}
                style={{ background: "none", border: "none", padding: 0, cursor: "pointer", color: "var(--fg-link)", fontFamily: "var(--font-mono)", fontSize: "var(--fs-caption)" }}>
          {r.control_id}
        </button>
        {r.key_control && <Mono dim style={{ marginLeft: 6 }}>KEY</Mono>}
        {r.is_info && <Mono dim style={{ marginLeft: 6 }}>INFO</Mono>}
        <div style={{ fontSize: "var(--fs-body-sm)", color: "var(--fg-1)" }}>{r.control_title}</div>
        {r.ai_root_cause && <div style={{ ...monoCaption, fontSize: 11 }}>{ROOT_CAUSE_LABEL[r.ai_root_cause] ?? r.ai_root_cause}</div>}
      </div>
    ) },
    { key: "entity_code", label: "Entity", mono: true },
    { key: "amount_usd", label: "Amount", align: "right", render: (r) => fmtUSD(r.amount_usd, true) },
    { key: "detected_value", label: "Detected", render: (r) => (
      <span title={r.detected_value} style={{ display: "inline-block", maxWidth: 380, color: "var(--fg-2)" }}>
        {r.detected_value.length > 110 ? `${r.detected_value.slice(0, 110)}…` : r.detected_value}
      </span>
    ) },
    { key: "age_bd", label: "Age", align: "right", render: (r) => r.age_bd == null ? "—" : r.age_bd < 0 ? "month to date" : `${r.age_bd} bd` },
    { key: "status", label: "Disposition", render: (r) => (
      <div style={{ display: "flex", flexDirection: "column", gap: 3, alignItems: "flex-start" }}>
        <StatusBadge status={r.disposition_status} small />
        {r.pending_sync && <Mono dim style={{ fontSize: 10 }}>pending sync</Mono>}
        {r.disposition_status === "proposed" && r.proposed_by && <Mono dim style={{ fontSize: 10 }}>by {r.proposed_by.split("@")[0]}</Mono>}
      </div>
    ) },
  ];

  return (
    <Page>
      <PageHero
        eyebrow="Close · Exceptions & Review"
        title="Exceptions & Review"
        subtitle="Every exception the control tests found, with AI triage, source records and evidence. A preparer proposes a disposition; an independent reviewer approves it. The next control run applies approvals to the checklist and the close."
        right={<Select label="Period" value={period} onChange={(v) => { setPeriod(v); setFocus(null); }} options={periodOptions(active)} />}
      />

      <Async state={st} height={300}>
        {() => (
          <>
            <div style={{ display: "flex", gap: "var(--space-4)", flexWrap: "wrap", marginBottom: "var(--space-6)" }}>
              <StatTile label="Needs a disposition" value={fmtInt(counts.open)} sub={`of ${fmtInt(counts.total)} exceptions in ${period}`} accent="var(--db-lava-600)" />
              <StatTile label="Awaiting approval" value={fmtInt(counts.proposed)} sub="proposed by a preparer" />
              <StatTile label="Approved" value={fmtInt(counts.approved)} sub="four-eyes complete" />
              <StatTile label="AI high or critical" value={fmtInt(counts.high)} sub={`${fmtInt(counts.triaged)} of ${fmtInt(counts.total)} triaged`} />
              <StatTile label="Pending sync" value={fmtInt(counts.pending)} sub="recorded, applied on the next run" />
            </div>

            <Section padding="var(--space-4) var(--space-5)" style={{ marginBottom: "var(--space-5)" }}>
              <Grid cols="auto 1fr" gap="var(--space-3) var(--space-5)" style={{ alignItems: "center" }}>
                <span style={{ ...monoCaption, textTransform: "uppercase" }}>Module</span>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  <Pill active={!module} onClick={() => { setModule(""); setControl(""); }}>All</Pill>
                  {modules.map((m) => (
                    <Pill key={m} active={module === m} onClick={() => { setModule(m); setControl(""); }}>
                      {MODULE_LABEL[m] ?? m} · {all.filter((r) => r.module === m && r.disposition_status !== "approved").length}
                    </Pill>
                  ))}
                </div>
                <span style={{ ...monoCaption, textTransform: "uppercase" }}>Status</span>
                <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap" }}>
                  <SegSelect options={STATUS_FILTERS} value={status} onChange={setStatus} />
                  <Select label="Control" value={control} onChange={setControl}
                          options={[{ value: "", label: "All controls" }, ...controls.map((c) => ({ value: c, label: c }))]} />
                  <span style={monoCaption}>{fmtInt(rows.length)} shown</span>
                </div>
              </Grid>
            </Section>

            <DataTable<ExceptionRow>
              columns={columns} rows={rows} rowKey={(r) => r.exception_id} activeKey={focus}
              onRowClick={(r) => setFocus(r.exception_id)} maxHeight={720}
              empty={status === "open" ? "No exception needs a disposition for this selection." : "No exceptions match this selection."} />
            <div style={{ ...monoCaption, marginTop: 8 }}>
              Severity and root cause are AI-generated by the triage_exceptions task (ai_query) and do not disposition anything.
              Sorted by AI severity, then amount.
            </div>
          </>
        )}
      </Async>

      <ExceptionDrawer exceptionId={focus} onClose={() => setFocus(null)} user={user} onNavigate={onNavigate} onChanged={st.reload} />
    </Page>
  );
}

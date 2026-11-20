// Reconciliations & Testing: one tab per module (Cash, Subledger, Journals,
// Access). KPIs from the module's metric view, one visual from the gold tables
// its controls test, the shared checklist slice, and a hand-off to the queue.
import React, { useMemo, useState } from "react";
import type { PageProps } from "../App";
import { getModule } from "../api";
import type { ModuleResponse, Row } from "../types";
import { PageHero } from "../components/layout/PageHero";
import { StatTile } from "../components/StatTile";
import { SecondaryBtn } from "../components/Buttons";
import { Icon } from "../components/Icon";
import { ChecklistSlice } from "../components/ChecklistSlice";
import { METRICS } from "../components/metricDefinitions";
import {
  Async, DataTable, Grid, LoadingNote, Mono, Page, Section, Select, Stack, StatusBadge, Tabs, activePeriod, monoCaption, periodOptions, useApi,
  type Column,
} from "../components/ui";
import { useWidth } from "../components/modules/useWidth";
import { CashWaterfall } from "../charts/CashWaterfall";
import { TieoutHeatmap, TieoutTrend } from "../charts/TieoutHeatmap";
import { BenfordChart, type DigitRow } from "../charts/BenfordChart";
import { SodMatrix } from "../charts/SodMatrix";
import { fmtDate, fmtInt, fmtPct, fmtUSD } from "../format";

type TabId = "cash" | "subledger" | "journals" | "access";
const TABS: { id: TabId; label: string; module: string; blurb: string }[] = [
  { id: "cash", label: "Cash", module: "M1", blurb: "Bank (camt.053) to book: continuity, matching within the aging window, unexplained difference, aged items backed by bank advices." },
  { id: "subledger", label: "Subledger", module: "M2", blurb: "Oracle AP, Salesforce AR and Workday payroll tied to the GL control accounts every day, within tolerance." },
  { id: "journals", label: "Journals", module: "M3", blurb: "Full-population journal entry testing: self-approval, approval thresholds, off-hours, duplicates, round amounts and Benford outliers." },
  { id: "access", label: "Access", module: "M4", blurb: "Workday terminations against Oracle access, segregation-of-duties conflicts, postings after termination, privileged grants without a request." },
];
const pct = (v: unknown) => (v == null ? "—" : fmtPct(Number(v) * 100));

export function ReconsTesting({ nav, onNavigate }: PageProps) {
  const initial = (TABS.find((t) => t.id === nav.tab)?.id ?? "cash") as TabId;
  const [tab, setTab] = useState<TabId>(initial);
  const [period, setPeriod] = useState(activePeriod());
  const meta = TABS.find((t) => t.id === tab)!;
  const st = useApi(() => getModule(tab, period), [tab, period]);

  return (
    <Page>
      <PageHero
        eyebrow="Modules · reconciliations and testing"
        title="Recons & Testing"
        subtitle="Each module tests its full population on every control run. The results here are the same ledger rows the Audit Checklist shows."
        right={<Select label="Period" value={period} onChange={setPeriod} options={periodOptions(activePeriod())} />}
      />
      <Tabs tabs={TABS.map((t) => ({ id: t.id, label: `${t.module} ${t.label}` }))} value={tab} onChange={setTab} />
      <Stack>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16 }}>
          <p style={{ margin: 0, color: "var(--fg-2)", fontSize: "var(--fs-body-sm)", maxWidth: 820 }}>{meta.blurb}</p>
          <SecondaryBtn onClick={() => onNavigate("exceptions", { filter: { module: meta.module } })}>
            <Icon name="warn" size={14} /> Open {meta.module} exceptions
          </SecondaryBtn>
        </div>
        <Async state={st}>
          {(d) => d.name !== tab || d.period !== period ? <LoadingNote height={200} /> : (
            <Stack>
              <Kpis tab={tab} d={d} />
              {tab === "cash" && <CashTab d={d} />}
              {tab === "subledger" && <SubledgerTab d={d} />}
              {tab === "journals" && <JournalsTab d={d} />}
              {tab === "access" && <AccessTab d={d} />}
            </Stack>
          )}
        </Async>
        <Section title={`${meta.module} controls`} eyebrow="Audit checklist slice · latest control run">
          <ChecklistSlice module={meta.module} period={period} onNavigate={onNavigate} title={`${meta.module} ${meta.label}`} />
        </Section>
      </Stack>
    </Page>
  );
}

function Kpis({ tab, d }: { tab: TabId; d: ModuleResponse }) {
  const k = d.kpis;
  const tiles: { label: string; value: string; sub?: string; tooltip?: (typeof METRICS)[keyof typeof METRICS] }[] =
    tab === "cash" ? [
      { label: "Unexplained (USD)", value: fmtUSD(k.unreconciled_amount_usd, true), sub: "aged items, CASH-03", tooltip: METRICS.unreconciled },
      { label: "Accounts in tolerance", value: pct(k.in_tolerance_pct), sub: `${fmtInt(k.reconciliations)} bank accounts` },
      { label: "Auto-match rate", value: pct(k.auto_match_rate), sub: "bank lines matched to GL" },
      { label: "Aged unmatched items", value: fmtInt(k.aged_items), sub: "past the aging window" },
      { label: "Breaks", value: fmtInt(k.breaks ?? 0), sub: "accounts over tolerance" },
    ] : tab === "subledger" ? [
      { label: "Unreconciled (USD)", value: fmtUSD(k.unreconciled_amount_usd, true), sub: "absolute difference", tooltip: METRICS.unreconciled },
      { label: "Tie-outs in tolerance", value: pct(k.in_tolerance_pct), sub: `${fmtInt(k.reconciliations)} tie-outs` },
      { label: "Breaks", value: fmtInt(k.breaks ?? 0), sub: "entity x subledger over tolerance" },
    ] : tab === "journals" ? [
      { label: "Journals tested", value: fmtInt(k.je_count), sub: `${fmtUSD(k.je_amount_usd, true)} posted`, tooltip: METRICS.records_tested },
      { label: "Manual journals", value: pct(k.manual_je_pct), sub: "share of journals" },
      { label: "Flagged journals", value: fmtInt(k.flagged_je_count), sub: fmtUSD(k.flagged_je_amount_usd, true) },
      { label: "Self-approved", value: fmtInt(k.self_approved_count), sub: "JET-01" },
      { label: "Unapproved over threshold", value: fmtInt(k.unapproved_over_threshold_count), sub: "JET-02" },
    ] : [
      { label: "Active ERP users", value: fmtInt(k.active_users), sub: "Oracle Fusion" },
      { label: "SoD conflict users", value: fmtInt(k.sod_conflict_users), sub: "PAM-01" },
      { label: "Terminated with access", value: fmtInt(k.terminated_with_access), sub: "PAM-02" },
      { label: "Post-termination journals", value: fmtInt(k.post_termination_journals), sub: fmtUSD(k.post_termination_amount_usd, true) },
    ];
  return (
    <div style={{ display: "flex", gap: "var(--space-4)", flexWrap: "wrap" }}>
      {tiles.map((t) => <StatTile key={t.label} label={t.label} value={t.value} sub={t.sub} tooltip={t.tooltip} />)}
    </div>
  );
}

// ── Cash ────────────────────────────────────────────────────────────────────
function CashTab({ d }: { d: ModuleResponse }) {
  const accounts = (d.visual.accounts as Row[]) ?? [];
  const sorted = useMemo(() => [...accounts].sort((a, b) => Math.abs(Number(b.unexplained_amount_usd ?? 0)) - Math.abs(Number(a.unexplained_amount_usd ?? 0))
    || Number(b.items_aged_unmatched ?? 0) - Number(a.items_aged_unmatched ?? 0)), [accounts]);
  const [sel, setSel] = useState<string | null>(sorted[0]?.bank_account ?? null);
  const acct = sorted.find((a) => a.bank_account === sel) ?? sorted[0];
  const [ref, w] = useWidth<HTMLDivElement>(640);
  const match = (d.visual.match as Row[]) ?? [];
  const cols: Column<Row>[] = [
    { key: "bank_account", label: "Account", mono: true },
    { key: "unexplained_amount_usd", label: "Unexplained USD", align: "right",
      render: (r) => <span style={{ color: Math.abs(Number(r.unexplained_amount_usd)) >= 1 ? "var(--danger)" : "var(--fg-3)" }}>{fmtUSD(Number(r.unexplained_amount_usd))}</span> },
    { key: "items", label: "Matched / total", align: "right", render: (r) => `${fmtInt(r.items_matched)} / ${fmtInt(r.items_total)}` },
    { key: "items_aged_unmatched", label: "Aged", align: "right" },
    { key: "last_statement_date", label: "Last stmt", mono: true, render: (r) => fmtDate(r.last_statement_date) },
  ];
  return (
    <Grid cols="minmax(380px, 0.9fr) minmax(0, 1.4fr)">
      <Section title="Bank accounts" eyebrow={`${accounts.length} accounts · ${d.period}`} padding="var(--space-4)">
        <DataTable columns={cols} rows={sorted} rowKey={(r) => String(r.bank_account)} activeKey={acct?.bank_account ?? null}
                   onRowClick={(r) => setSel(String(r.bank_account))} maxHeight={430} dense />
      </Section>
      <Section title={acct ? `${acct.bank_account} reconciliation` : "Reconciliation"} eyebrow={acct ? `${acct.entity_code} · ${acct.currency_code}` : undefined}>
        <div ref={ref}>
          {acct && <CashWaterfall account={acct} width={Math.max(420, w)} height={290} />}
        </div>
        {acct && (
          <div style={{ ...monoCaption, marginTop: 6 }}>
            Book {fmtUSD(Number(acct.book_balance))} {acct.currency_code} · bank {acct.external_balance == null ? "no statement" : `${fmtUSD(Number(acct.external_balance))} ${acct.currency_code}`} ·
            {" "}{fmtInt(acct.items_pending)} pending, {fmtInt(acct.items_aged_unmatched)} aged. Timing / other is derived as bank minus the components shown.
          </div>
        )}
        <div style={{ display: "flex", gap: 10, marginTop: 14, flexWrap: "wrap" }}>
          {match.map((m) => (
            <div key={m.match_status} style={{ flex: "1 1 140px", padding: "8px 10px", border: "1px solid var(--border)", borderRadius: "var(--radius-md)" }}>
              <div style={{ ...monoCaption, textTransform: "uppercase" }}>{String(m.match_status).replace("_", " ").toLowerCase()}</div>
              <div style={{ fontWeight: 700, fontSize: "var(--fs-h4)", color: m.match_status === "MATCHED" ? "var(--fg-1)" : "var(--db-lava-700)" }}>{fmtInt(m.items)}</div>
              <Mono dim>{fmtUSD(Number(m.amount), true)} gross, all accounts</Mono>
            </div>
          ))}
        </div>
      </Section>
    </Grid>
  );
}

// ── Subledger ───────────────────────────────────────────────────────────────
function SubledgerTab({ d }: { d: ModuleResponse }) {
  const cells = (d.visual.cells as Row[]) ?? [];
  const trend = (d.visual.trend as Row[]) ?? [];
  const [ref, w] = useWidth<HTMLDivElement>(560);
  const [sel, setSel] = useState<Row | null>(null);
  const breaks = cells.filter((c) => !c.in_tolerance);
  return (
    <Grid cols="minmax(0, 1.2fr) minmax(340px, 1fr)">
      <Section title="Tie-out heatmap" eyebrow={`Subledger vs GL control account · ${d.period} · difference in USD`}>
        <div ref={ref}>
          <TieoutHeatmap cells={cells} onCell={setSel} width={Math.max(420, w)} />
        </div>
        <div style={{ ...monoCaption, marginTop: 8 }}>Lava cells are over tolerance; shade grows with the multiple of tolerance. Click a cell for the tie-out.</div>
      </Section>
      <Stack>
        <Section title={sel ? `${sel.entity_code} ${sel.recon_type} tie-out` : "Breaks"} eyebrow={sel ? String(sel.control_id) : `${breaks.length} over tolerance`}>
          {sel ? (
            <TieoutDetail c={sel} />
          ) : breaks.length ? (
            <Stack gap="var(--space-2)">
              {breaks.map((c) => (
                <button key={`${c.entity_code}${c.recon_type}`} onClick={() => setSel(c)}
                        style={{ display: "flex", justifyContent: "space-between", padding: "8px 10px", border: "1px solid var(--border)",
                                 borderRadius: "var(--radius-md)", background: "var(--bg-canvas)", cursor: "pointer", fontFamily: "var(--font-sans)" }}>
                  <span><Mono>{c.control_id}</Mono> {c.entity_code} {c.recon_type}</span>
                  <Mono style={{ color: "var(--danger)" }}>{fmtUSD(Number(c.difference_usd))}</Mono>
                </button>
              ))}
            </Stack>
          ) : <div style={{ color: "var(--fg-3)", fontSize: "var(--fs-body-sm)" }}>Every tie-out is within tolerance for this period.</div>}
        </Section>
        <Section title="Breaks by month" eyebrow="last six months">
          <TieoutTrend trend={trend} width={Math.max(320, Math.min(560, w))} />
        </Section>
      </Stack>
    </Grid>
  );
}

function TieoutDetail({ c }: { c: Row }) {
  const items: [string, React.ReactNode][] = [
    ["GL control account", `${fmtUSD(Number(c.book_balance))} ${c.currency_code}`],
    ["Subledger", `${fmtUSD(Number(c.external_balance))} ${c.currency_code}`],
    ["Difference", `${fmtUSD(Number(c.difference))} ${c.currency_code}`],
    ["Difference (USD)", fmtUSD(Number(c.difference_usd))],
    ["Tolerance", `${fmtUSD(Number(c.tolerance_amount))} ${c.currency_code}`],
    ["Result", <StatusBadge key="s" status={c.in_tolerance ? "PASS" : "FAIL"} label={c.in_tolerance ? "in tolerance" : "over tolerance"} small />],
  ];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "6px 14px", fontSize: "var(--fs-body-sm)" }}>
      {items.map(([k, v]) => (
        <React.Fragment key={k}>
          <div style={{ ...monoCaption, textTransform: "uppercase", paddingTop: 2 }}>{k}</div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: "var(--fs-caption)" }}>{v}</div>
        </React.Fragment>
      ))}
    </div>
  );
}

// ── Journals ────────────────────────────────────────────────────────────────
function JournalsTab({ d }: { d: ModuleResponse }) {
  const digits = (d.visual.digits as DigitRow[]) ?? [];
  const users = (d.visual.users as Row[]) ?? [];
  const flags = (d.visual.flags as Row) ?? {};
  const [ref, w] = useWidth<HTMLDivElement>(560);
  const flagRows: { label: string; key: string; ctl: string }[] = [
    { label: "Self-approved (preparer = approver)", key: "self_approved", ctl: "JET-01" },
    { label: "Manual over threshold, not pre-approved", key: "unapproved_over_threshold", ctl: "JET-02" },
    { label: "Weekend or after-hours postings", key: "off_hours", ctl: "JET-03" },
    { label: "Duplicate journals", key: "duplicates", ctl: "JET-04" },
    { label: "Round amounts", key: "round_amounts", ctl: "JET-05" },
    { label: "Statistical outliers (|z| > 3)", key: "outliers", ctl: "JET-05" },
  ];
  const maxF = Math.max(1, ...flagRows.map((f) => Number(flags[f.key] ?? 0)));
  const ucols: Column<Row>[] = [
    { key: "user_name", label: "Preparer", mono: true },
    { key: "journals", label: "Journals", align: "right" },
    { key: "mad", label: "MAD", align: "right", render: (r) => Number(r.mad).toFixed(4) },
    { key: "non_conforming", label: "Benford", render: (r) => <StatusBadge status={r.non_conforming ? "warn" : "ok"} label={r.non_conforming ? "non-conforming" : "conforming"} small /> },
  ];
  return (
    <Grid cols="minmax(0, 1.3fr) minmax(340px, 1fr)">
      <Section title="Benford first-digit test" eyebrow={`Manual journals over $10 · ${fmtInt(Number(d.visual.population))} amounts · ${d.period}`}>
        <div ref={ref}>
          <BenfordChart digits={digits} width={Math.max(420, w)} height={250} />
        </div>
        <div style={{ ...monoCaption, marginTop: 6 }}>Small populations deviate from Benford by chance; the test is a pointer for JET-05 review, not a finding on its own.</div>
      </Section>
      <Stack>
        <Section title="Journal test flags" eyebrow={`population ${fmtInt(Number(flags.population))} journals`}>
          <Stack gap="var(--space-2)">
            {flagRows.map((f) => {
              const v = Number(flags[f.key] ?? 0);
              return (
                <div key={f.key} style={{ display: "grid", gridTemplateColumns: "56px 1fr 40px", gap: 10, alignItems: "center" }}>
                  <Mono dim>{f.ctl}</Mono>
                  <div>
                    <div style={{ fontSize: "var(--fs-body-sm)", marginBottom: 3 }}>{f.label}</div>
                    <div style={{ height: 6, borderRadius: 3, background: "var(--bg-subtle)" }}>
                      <div style={{ width: `${(v / maxF) * 100}%`, height: 6, borderRadius: 3, background: v ? "var(--db-lava-600)" : "transparent" }} />
                    </div>
                  </div>
                  <Mono style={{ textAlign: "right", fontWeight: 600 }}>{fmtInt(v)}</Mono>
                </div>
              );
            })}
          </Stack>
        </Section>
        <Section title="Preparers by Benford deviation" eyebrow="mean absolute deviation, 30+ journals">
          <DataTable columns={ucols} rows={users} rowKey={(r) => String(r.created_by_user_id ?? r.user_name)} maxHeight={260} dense
                     empty="No preparer has enough journals for a Benford test." />
        </Section>
      </Stack>
    </Grid>
  );
}

// ── Access ──────────────────────────────────────────────────────────────────
function AccessTab({ d }: { d: ModuleResponse }) {
  const pairs = (d.visual.pairs as Row[]) ?? [];
  const roles = (d.visual.roles as Row[]) ?? [];
  const terminated = (d.visual.terminated as Row[]) ?? [];
  const [ref, w] = useWidth<HTMLDivElement>(520);
  const maxR = Math.max(1, ...roles.map((r) => Number(r.users ?? 0)));
  const tcols: Column<Row>[] = [
    { key: "user_name", label: "Oracle user", mono: true },
    { key: "legal_name", label: "Name", render: (r) => <span title="Masked by mask_pii unless you are in fin_recon_pii_readers">{r.legal_name}</span> },
    { key: "entity_code", label: "Entity", mono: true },
    { key: "job_profile", label: "Job profile" },
    { key: "termination_date", label: "Terminated", mono: true, render: (r) => fmtDate(r.termination_date) },
    { key: "access_end_date", label: "Access ended", mono: true,
      render: (r) => r.access_end_date ? fmtDate(r.access_end_date) : <span style={{ color: "var(--danger)" }}>still active</span> },
    { key: "removal_lag_bd", label: "Lag (bd)", align: "right",
      render: (r) => <span style={{ color: Number(r.removal_lag_bd) > 1 ? "var(--danger)" : undefined }}>{fmtInt(r.removal_lag_bd)}</span> },
    { key: "post_termination_journals", label: "Journals after", align: "right" },
    { key: "post_termination_amount_usd", label: "Amount after", align: "right", render: (r) => fmtUSD(Number(r.post_termination_amount_usd)) },
  ];
  return (
    <Stack>
      <Grid cols="minmax(0, 1.2fr) minmax(320px, 1fr)">
        <Section title="Segregation-of-duties conflicts" eyebrow={`Oracle roles held together · ${pairs.length} conflict rules triggered`}>
          <div ref={ref} style={{ overflowX: "auto" }}>
            {pairs.length ? <SodMatrix pairs={pairs} width={Math.max(420, w)} />
              : <div style={{ color: "var(--fg-3)", fontSize: "var(--fs-body-sm)" }}>No user holds a conflicting role pair in this period.</div>}
          </div>
        </Section>
        <Section title="Users per Oracle role" eyebrow="active grants">
          <Stack gap="6px">
            {roles.map((r) => (
              <div key={r.role} style={{ display: "grid", gridTemplateColumns: "180px 1fr 32px", gap: 8, alignItems: "center" }}>
                <Mono>{r.role}</Mono>
                <div style={{ height: 8, borderRadius: 4, background: "var(--bg-subtle)" }}>
                  <div style={{ width: `${(Number(r.users) / maxR) * 100}%`, height: 8, borderRadius: 4, background: "var(--db-navy-400)" }} />
                </div>
                <Mono style={{ textAlign: "right" }}>{fmtInt(r.users)}</Mono>
              </div>
            ))}
          </Stack>
        </Section>
      </Grid>
      <Section title="Terminated workers and their Oracle access" eyebrow="Workday terminations joined to Oracle users · PAM-02, PAM-03">
        <DataTable columns={tcols} rows={terminated} rowKey={(r) => String(r.user_name)} dense
                   empty="No terminated worker kept access or posted after termination in this period." />
      </Section>
    </Stack>
  );
}

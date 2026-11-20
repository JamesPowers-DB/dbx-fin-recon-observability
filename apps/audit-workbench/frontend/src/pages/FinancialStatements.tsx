// Financial Statements: the final artifact of the close. Amounts come from the
// governed gold_mv_financials view; the DRAFT/FINAL badge follows the close
// (FINAL once CLS-12, the controller's GO, is complete). The GAAP integrity
// checks and the FP&A variance review are checklist slices on the same page.
import React, { useEffect, useState } from "react";
import type { PageProps } from "../App";
import { drillLine, getIntegrity, getStatement } from "../api";
import type { Row, StatementLine, StatementResponse } from "../types";
import { PageHero } from "../components/layout/PageHero";
import { SecondaryBtn } from "../components/Buttons";
import { Icon } from "../components/Icon";
import { ChecklistSlice } from "../components/ChecklistSlice";
import { VarianceReview } from "../components/statements/VarianceReview";
import {
  Async, DataTable, Drawer, Grid, KV, Mono, Page, Section, Select, Stack, StatusBadge, Tabs, activePeriod, monoCaption, periodOptions, useApi,
  type Column,
} from "../components/ui";
import { fmtPct, fmtUSD } from "../format";

type TabId = "IS" | "BS" | "CF" | "variances";
const TABS: { id: TabId; label: string }[] = [
  { id: "IS", label: "Income statement" }, { id: "BS", label: "Balance sheet" }, { id: "CF", label: "Cash flow" }, { id: "variances", label: "Variance review" },
];
const TITLE: Record<string, string> = { IS: "Income statement", BS: "Balance sheet", CF: "Statement of cash flows" };
// Income statement lines where a higher actual than budget is unfavorable.
const EXPENSE = new Set(["IS-200", "IS-300", "IS-310", "IS-320", "IS-330", "IS-T30", "IS-400", "IS-500"]);

const PRINT_CSS = `
.print-only { display: none; }
@media print {
  .no-print { display: none !important; }
  .print-only { display: block !important; }
  main { overflow: visible !important; }
  section { break-inside: avoid; border: none !important; }
}`;

export function FinancialStatements({ nav, onNavigate }: PageProps) {
  const initial = (TABS.find((t) => t.id === nav.tab)?.id ?? "IS") as TabId;
  const [tab, setTab] = useState<TabId>(initial);
  const [entity, setEntity] = useState("ALL");
  const [period, setPeriod] = useState(activePeriod());
  const [drill, setDrill] = useState<string | null>(nav.focusId ?? null);
  const stmt: "IS" | "BS" | "CF" = tab === "variances" ? "IS" : tab;
  const st = useApi(() => getStatement(stmt, entity, period), [stmt, entity, period]);
  const d = st.data;

  return (
    <Page>
      <style>{PRINT_CSS}</style>
      <div className="no-print">
        <PageHero
          eyebrow="Modules · financial statements"
          title="Financial Statements"
          subtitle="Corvane Technologies statements from the governed metric view. The badge turns FINAL when the controller's GO (CLS-12) completes the close."
          right={
            <>
              {d && <StatusBadge status={d.badge} label={d.badge === "FINAL" ? `FINAL · closed T+${d.close_day ?? "?"}` : `DRAFT · projected T+${d.close_day ?? "?"}`} />}
              <SecondaryBtn onClick={() => window.print()} disabled={tab === "variances"}><Icon name="download" size={14} /> Print</SecondaryBtn>
            </>
          }
        />
        <Tabs tabs={TABS} value={tab} onChange={setTab} />
        <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap", marginBottom: "var(--space-5)" }}>
          <Select label="Entity" value={entity} onChange={setEntity}
                  options={[{ value: "ALL", label: "Consolidated (all entities)" },
                            ...(d?.entities ?? []).map((e) => ({ value: e.entity_code, label: `${e.entity_code} · ${e.entity_name} (${e.currency_code})` }))]} />
          <Select label="Period" value={period} onChange={setPeriod} options={periodOptions(activePeriod())} />
          {d && <span style={monoCaption}>{d.basis_note} · USD</span>}
        </div>
      </div>

      {tab === "variances" ? (
        <VarianceReview period={period} entity={entity} onNavigate={onNavigate} />
      ) : (
        <Stack>
          <Async state={st} empty={(x) => x.lines.length === 0} emptyText="No statement lines for this entity and period.">
            {(x) => x.statement !== stmt || x.entity !== entity || x.period !== period ? <div /> : (
              <StatementView d={x} onDrill={setDrill} onVariances={() => setTab("variances")} />
            )}
          </Async>
          <div className="no-print">
            <Grid cols="minmax(320px, 1fr) minmax(0, 1.3fr)">
              <Section title="GAAP integrity checks" eyebrow="Audit checklist slice · pipeline-bound">
                <ChecklistSlice controlIds={["FSC-01", "FSC-02", "FSC-03", "FSC-04"]} period={period} onNavigate={onNavigate} title="Statement integrity" compact />
              </Section>
              <IntegrityDiffs period={period} />
            </Grid>
          </div>
        </Stack>
      )}
      <LineDrill line={drill} entity={entity} period={period} onClose={() => setDrill(null)} lineName={d?.lines.find((l) => l.line_code === drill)?.line_name} />
    </Page>
  );
}

function StatementView({ d, onDrill, onVariances }: { d: StatementResponse; onDrill: (code: string) => void; onVariances: () => void }) {
  const mtd = d.data_status === "MONTH_TO_DATE";
  const isIS = d.statement === "IS";
  const hasPlan = isIS && d.lines.some((l) => l.budget != null);
  const cmp = (l: StatementLine) => (mtd ? l.budget_mtd : l.budget);
  const material = d.lines.reduce((a, l) => a + Number(l.material_variances ?? 0), 0);
  const unexplained = d.lines.reduce((a, l) => a + Number(l.unexplained ?? 0), 0);

  const name: Column<StatementLine> = {
    key: "line_name", label: "Line",
    render: (l) => {
      const strong = l.line_type !== "detail";
      return (
        <span style={{ paddingLeft: strong ? 0 : 14, fontWeight: strong ? 700 : 400, display: "inline-flex", alignItems: "center", gap: 8 }}>
          {l.line_name}
          {Number(l.material_variances) > 0 && (
            <button className="no-print" onClick={(e) => { e.stopPropagation(); onVariances(); }}
                    title={`${l.material_variances} material variance(s), ${l.unexplained} unexplained. Open the variance review.`}
                    style={{ border: "1px solid var(--db-lava-600)", background: Number(l.unexplained) > 0 ? "var(--db-lava-600)" : "transparent",
                             color: Number(l.unexplained) > 0 ? "var(--fg-on-dark)" : "var(--db-lava-700)", borderRadius: "var(--radius-pill)",
                             fontFamily: "var(--font-mono)", fontSize: 10, padding: "0 6px", cursor: "pointer" }}>
              {Number(l.unexplained) > 0 ? `${l.unexplained} unexplained` : `${l.material_variances} material`}
            </button>
          )}
        </span>
      );
    },
  };
  const money = (key: keyof StatementLine, label: string): Column<StatementLine> => ({
    key: String(key), label, align: "right", render: (l) => fmtUSD(l[key] as number | null),
  });
  const delta = (label: string, base: (l: StatementLine) => number | null | undefined, expenseAware: boolean): Column<StatementLine> => ({
    key: label, label, align: "right",
    render: (l) => {
      const b = base(l);
      if (b == null || l.actual == null) return <span style={{ color: "var(--fg-3)" }}>—</span>;
      const v = l.actual - b;
      const bad = expenseAware ? (EXPENSE.has(l.line_code) ? v > 0 : v < 0) : false;
      return <span style={{ color: bad && Math.abs(v) >= 1 ? "var(--danger)" : "var(--fg-1)" }}>{v > 0 ? "+" : ""}{fmtUSD(v)}</span>;
    },
  });
  const deltaPct = (label: string, base: (l: StatementLine) => number | null | undefined): Column<StatementLine> => ({
    key: label, label, align: "right",
    render: (l) => {
      const b = base(l);
      if (b == null || l.actual == null || Math.abs(b) < 1) return <span style={{ color: "var(--fg-3)" }}>—</span>;
      return fmtPct(((l.actual - b) / Math.abs(b)) * 100);
    },
  });

  const cols: Column<StatementLine>[] = isIS && hasPlan ? [
    name, money("actual", mtd ? "Actual MTD" : "Actual"),
    { key: "cmp", label: mtd ? "Budget MTD (phased)" : "Budget", align: "right", render: (l) => fmtUSD(cmp(l)) },
    delta("Variance", cmp, true), deltaPct("Var %", cmp),
    ...(mtd ? [money("budget", "Full-month budget")] : []),
    money("forecast", "Forecast"), money("prior_period", "Prior period"), money("prior_year", "Prior year"),
  ] : [
    name, money("actual", d.statement === "BS" ? "Period end" : "Actual"),
    money("prior_period", d.statement === "BS" ? "Prior period end" : "Prior period"),
    delta("Change", (l) => l.prior_period, false),
    money("prior_year", d.statement === "BS" ? "Prior year end" : "Prior year"),
    delta("Change YoY", (l) => l.prior_year, false),
  ];
  const ent = d.entity === "ALL" ? "Consolidated" : d.entities.find((e) => e.entity_code === d.entity)?.entity_name ?? d.entity;
  const canDrill = d.statement !== "CF";

  return (
    <Section padding="var(--space-5)"
             title={`${TITLE[d.statement]} · ${ent}`}
             eyebrow={`${d.period} · ${mtd ? "month to date" : "full month"} · USD`}
             right={
               <span className="no-print" style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
                 {isIS && <Mono dim>{material} material · {unexplained} unexplained</Mono>}
                 {canDrill && <Mono dim>click a line to drill to accounts and journals</Mono>}
               </span>
             }>
      <div className="print-only" style={{ marginBottom: 12 }}>
        <div style={{ fontWeight: 700, fontSize: 18 }}>Corvane Technologies</div>
        <div>{TITLE[d.statement]} · {ent} · {d.period} · {d.badge}{d.badge === "FINAL" ? ` (closed T+${d.close_day})` : " (close in progress)"}</div>
        <div style={monoCaption}>Synthetic data. Printed {new Date().toISOString().slice(0, 16).replace("T", " ")} UTC from gold_mv_financials.</div>
      </div>
      <StatementGrid cols={cols} lines={d.lines} onRow={canDrill ? (l) => { if (l.line_type === "detail") onDrill(l.line_code); } : undefined} />
      {d.statement === "BS" && <BalanceCheck lines={d.lines} />}
    </Section>
  );
}

/** Statement table with subtotal and total rules (the shared DataTable has no row styling hooks). */
function StatementGrid({ cols, lines, onRow }: { cols: Column<StatementLine>[]; lines: StatementLine[]; onRow?: (l: StatementLine) => void }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ minWidth: "100%", borderCollapse: "collapse", fontSize: "var(--fs-body-sm)" }}>
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c.key} style={{ textAlign: c.align ?? "left", padding: "8px 10px", borderBottom: "2px solid var(--border-strong)",
                                       fontFamily: "var(--font-mono)", fontSize: "var(--fs-caption)", fontWeight: 500, color: "var(--fg-2)",
                                       textTransform: "uppercase", whiteSpace: "nowrap" }}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {lines.map((l) => {
            const total = l.line_type === "total";
            const sub = l.line_type === "subtotal";
            const clickable = !!onRow && l.line_type === "detail";
            return (
              <tr key={l.line_code} onClick={clickable ? () => onRow!(l) : undefined}
                  style={{ cursor: clickable ? "pointer" : "default", background: total ? "var(--bg-subtle)" : undefined }}
                  onMouseEnter={(e) => { if (clickable) e.currentTarget.style.background = "var(--bg-subtle)"; }}
                  onMouseLeave={(e) => { if (clickable) e.currentTarget.style.background = ""; }}>
                {cols.map((c) => (
                  <td key={c.key} style={{ textAlign: c.align ?? "left", padding: "7px 10px",
                                           borderTop: sub || total ? "1px solid var(--border-strong)" : undefined,
                                           borderBottom: total ? "3px double var(--border-strong)" : "1px solid var(--border)",
                                           fontFamily: c.align === "right" ? "var(--font-mono)" : undefined,
                                           fontSize: c.align === "right" ? "var(--fs-caption)" : undefined,
                                           fontWeight: (sub || total) && c.align === "right" ? 700 : undefined, whiteSpace: "nowrap" }}>
                    {c.render ? c.render(l) : String((l as unknown as Row)[c.key] ?? "")}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function BalanceCheck({ lines }: { lines: StatementLine[] }) {
  const a = lines.find((l) => l.line_code === "BS-T20")?.actual;
  const le = lines.find((l) => l.line_code === "BS-T60")?.actual;
  if (a == null || le == null) return null;
  const diff = a - le;
  const ok = Math.abs(diff) < 1;
  return (
    <div style={{ marginTop: 10, display: "flex", gap: 10, alignItems: "center" }}>
      <StatusBadge status={ok ? "PASS" : "FAIL"} label={ok ? "balances" : "out of balance"} small />
      <span style={monoCaption}>Total assets {fmtUSD(a)} · total liabilities and equity {fmtUSD(le)} · difference {fmtUSD(diff)} (FSC-02 tests this per entity)</span>
    </div>
  );
}

function IntegrityDiffs({ period }: { period: string }) {
  const st = useApi(() => getIntegrity(period), [period]);
  const diff = (k: string): Column<Row> => ({
    key: k, label: k.replace("_difference_usd", "").replace("re_rollforward", "RE roll-forward").replace("tb", "TB").replace("bs", "BS").replace("cf", "CF"),
    align: "right",
    render: (r) => {
      const v = Number(r[k] ?? 0);
      return <span style={{ color: Math.abs(v) >= 0.01 ? "var(--danger)" : "var(--fg-3)" }}>{Math.abs(v) < 0.005 ? "0" : fmtUSD(v)}</span>;
    },
  });
  const cols: Column<Row>[] = [{ key: "entity_code", label: "Entity", mono: true },
    diff("tb_difference_usd"), diff("bs_difference_usd"), diff("cf_difference_usd"), diff("re_rollforward_difference_usd")];
  return (
    <Section title="Integrity differences by entity" eyebrow={`${period} · USD · zero means the check holds`}>
      <Async state={st} empty={(d) => d.differences.length === 0} emptyText="No integrity rows for this period yet.">
        {(d) => (
          <>
            <DataTable columns={cols} rows={d.differences} rowKey={(r) => String(r.entity_code)} dense />
            <div style={{ ...monoCaption, marginTop: 6 }}>
              TB: debits minus credits (FSC-01). BS: assets minus liabilities and equity (FSC-02). CF: ending cash minus balance-sheet cash (FSC-03). RE: retained earnings roll-forward (FSC-04).
            </div>
          </>
        )}
      </Async>
    </Section>
  );
}

function LineDrill({ line, entity, period, onClose, lineName }: { line: string | null; entity: string; period: string; onClose: () => void; lineName?: string }) {
  const [key, setKey] = useState(0);
  useEffect(() => setKey((k) => k + 1), [line, entity, period]);
  return (
    <Drawer open={!!line} onClose={onClose} width={860}
            title={line ? `${line}${lineName ? ` · ${lineName}` : ""}` : ""}
            subtitle={`Postings in ${period} · ${entity === "ALL" ? "all entities" : entity} · from gold_fact_gl_lines`}>
      {line && <DrillBody key={key} line={line} entity={entity} period={period} />}
    </Drawer>
  );
}

function DrillBody({ line, entity, period }: { line: string; entity: string; period: string }) {
  const st = useApi(() => drillLine(line, entity, period), [line, entity, period]);
  const acols: Column<Row>[] = [
    { key: "account_code", label: "Account", mono: true }, { key: "account_name", label: "Name" },
    { key: "net_usd", label: "Net USD", align: "right", render: (r) => fmtUSD(Number(r.net_usd)) },
    { key: "journals", label: "Journals", align: "right" },
  ];
  const jcols: Column<Row>[] = [
    { key: "je_header_id", label: "Journal", mono: true }, { key: "entity_code", label: "Entity", mono: true },
    { key: "journal_name", label: "Name" }, { key: "je_source", label: "Source" }, { key: "je_category", label: "Category" },
    { key: "accounting_date", label: "Date", mono: true }, { key: "created_by", label: "Created by", mono: true },
    { key: "net_usd", label: "Net USD", align: "right", render: (r) => fmtUSD(Number(r.net_usd)) },
  ];
  return (
    <Async state={st} empty={(d) => d.accounts.length === 0} emptyText="No GL postings map to this line in the period.">
      {(d) => {
        const total = d.accounts.reduce((a, r) => a + Number(r.net_usd ?? 0), 0);
        return (
          <Stack>
            <KV cols={2} items={[["Accounts", String(d.accounts.length)], ["Net postings", fmtUSD(total)]]} />
            <Section title="By account" padding="var(--space-4)"><DataTable columns={acols} rows={d.accounts} rowKey={(r) => String(r.account_code)} dense /></Section>
            <Section title="Largest journals" eyebrow="top 25 by absolute amount" padding="var(--space-4)">
              <DataTable columns={jcols} rows={d.journals} rowKey={(r) => String(r.je_header_id)} dense maxHeight={420} />
            </Section>
          </Stack>
        );
      }}
    </Async>
  );
}

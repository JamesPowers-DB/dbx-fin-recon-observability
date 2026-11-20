// Risk & Reporting: risk register with live KRIs, SOX status pack, AI-drafted
// summary. Everything is computed for the period from the control-results
// ledger (meta_control_results) and the governed metric views; the AI summary
// is drafted from the same numbers, shown next to it.
import React, { useState } from "react";
import type { PageProps } from "../App";
import { draftReportSummary, getAppConfig, getRisks, getSoxPack } from "../api";
import type { ReportSummary, RiskRow, Row, SoxPack } from "../types";
import {
  AiBadge, Async, DataTable, DeepLink, ErrorNote, Grid, LoadingNote, Mono, Page, Section, Select, Stack, StatusBadge,
  activePeriod, linkBtn, monoCaption, periodOptions, toneColor, useApi, type Column,
} from "../components/ui";
import { PageHero } from "../components/layout/PageHero";
import { StatTile } from "../components/StatTile";
import { PrimaryBtn, SecondaryBtn } from "../components/Buttons";
import { Icon } from "../components/Icon";
import { Markdown } from "../components/Markdown";
import { fmtInt, fmtPct, fmtUSD } from "../format";
import { fmtTs } from "../components/lineage/lineageUtil";
import { OperatingModel } from "../components/reporting/OperatingModel";

const LANE_LABEL: Record<string, { title: string; sub: string }> = {
  management: { title: "Management monitoring", sub: "first and second line: controllers, process owners" },
  assurance: { title: "Independent assurance", sub: "third line: Internal Audit testing the same ledger" },
};

export function RiskReporting({ onNavigate }: PageProps) {
  const active = activePeriod();
  const [period, setPeriod] = useState(active);
  const risks = useApi(() => getRisks(period), [period]);
  const sox = useApi(() => getSoxPack(period), [period]);
  const cfg = useApi(getAppConfig, []);
  const h = sox.data?.health ?? {};
  const elevated = risks.data ? risks.data.risks.filter((r) => r.residual === "Elevated").length : null;

  return (
    <Page>
      <PageHero
        eyebrow="Insights · Risk & Reporting"
        title="Risk & Reporting"
        subtitle="The risk register's indicators and the SOX status pack are computed for the period from the control-results ledger and the governed metric views. Nothing on this page is maintained by hand; re-running the controls updates it."
        right={<Select label="Period" value={period} onChange={setPeriod} options={periodOptions(active)} />}
      />

      <div style={{ display: "flex", gap: "var(--space-4)", flexWrap: "wrap", marginBottom: "var(--space-6)" }}>
        <StatTile label="Control pass rate" value={sox.data ? fmtPct((h.pass_rate ?? 0) * 100) : "…"} sub="control x entity instances, latest run" />
        <StatTile label="Controls failing" value={sox.data ? `${fmtInt(h.failed)} / ${fmtInt(h.executed)}` : "…"}
                  sub={sox.data ? `${fmtInt(h.key_failed)} key controls` : undefined} accent={h.key_failed ? "var(--db-lava-600)" : undefined} />
        <StatTile label="Records tested" value={sox.data ? fmtInt(h.records_tested) : "…"}
                  sub={sox.data ? `full population; a sample approach tests ${fmtInt(h.traditional_sample)}` : undefined} />
        <StatTile label="Open deficiency items" value={sox.data ? fmtInt(sox.data.deficiencies.length) : "…"} sub="key-control exceptions and deficiency dispositions" />
        <StatTile label="Risks above appetite" value={risks.data ? `${elevated} / ${risks.data.risks.length}` : "…"} sub="KRI breached and a linked control failing" />
      </div>

      <Stack>
        <Section eyebrow="Enterprise risk register" title="Risks, key risk indicators and the controls that mitigate them"
                 right={<span style={monoCaption}>KRI = a governed metric-view measure against its appetite threshold</span>}>
          <Async state={risks} empty={(d) => d.risks.length === 0} emptyText="The risk register is empty. Publish controls/risk_register.yml with publish_controls.">
            {(d) => <RiskTable rows={d.risks} onNavigate={onNavigate} />}
          </Async>
        </Section>

        <Section eyebrow="SOX status pack" title={`Control results for ${period}`}
                 right={sox.data?.run ? (
                   <span style={monoCaption}>
                     reflects run <DeepLink href={cfg.data && sox.data.run.job_id ? `${cfg.data.workspace_url}/jobs/${sox.data.run.job_id}/runs/${sox.data.run.job_run_id}` : null}>
                       {String(sox.data.run.job_run_id)}</DeepLink> · {fmtTs(sox.data.run.started_at)} UTC
                     {sox.data.run.gate_result && <> · gate <StatusBadge status={sox.data.run.gate_result} small /></>}
                   </span>) : undefined}>
          <Async state={sox} empty={(d) => d.by_module.length === 0} emptyText="No control results for this period yet.">
            {(d) => <SoxPackView d={d} onNavigate={onNavigate} />}
          </Async>
        </Section>

        <Section eyebrow="Operating model" title="From sampled, after-the-close testing to continuous assurance">
          <OperatingModel recordsTested={h.records_tested} sample={h.traditional_sample} />
        </Section>

        <AiSummary period={period} />
      </Stack>
    </Page>
  );
}

// ── Risk register ───────────────────────────────────────────────────────────
function fmtKri(r: RiskRow, v: number | null | undefined): string {
  if (v == null) return "—";
  if (/usd/i.test(r.kri_label) || r.kri_measure.endsWith("_usd")) return fmtUSD(v, true);
  if (r.kri_measure.endsWith("_pct") || (r.kri_threshold > 0 && r.kri_threshold <= 1)) return fmtPct(v * 100);
  return fmtInt(v);
}

function RiskTable({ rows, onNavigate }: { rows: RiskRow[]; onNavigate: PageProps["onNavigate"] }) {
  const cols: Column<RiskRow>[] = [
    { key: "risk", label: "Risk", render: (r) => (
      <div style={{ minWidth: 200, maxWidth: 280 }}>
        <Mono dim>{r.risk_id}</Mono>
        <div style={{ fontWeight: 600 }}>{r.title}</div>
        <div style={monoCaption}>{r.category} · owner {r.owner_role}</div>
      </div>) },
    { key: "inherent", label: "Inherent · appetite", render: (r) => (
      <div><RiskHeatCell likelihood={r.inherent_likelihood} impact={r.inherent_impact} />
        <div style={{ ...monoCaption, fontSize: 10, marginTop: 4 }}>appetite {r.appetite}</div></div>) },
    { key: "kri", label: "Key risk indicator", render: (r) => (
      <div style={{ minWidth: 210 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "flex-start" }}>
          <span style={{ fontSize: "var(--fs-body-sm)" }}>{r.kri_label}</span>
          <StatusBadge status={r.kri_breached == null ? "NOT_RUN" : r.kri_breached ? "fail" : "ok"}
                       label={r.kri_breached == null ? "no data" : r.kri_breached ? "breached" : "within"} small />
        </div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 2 }}>
          <span style={{ fontFamily: "var(--font-mono)", fontWeight: 700, color: r.kri_breached ? "var(--danger)" : "var(--fg-1)" }}>{fmtKri(r, r.kri_value)}</span>
          <span style={monoCaption}>{r.kri_direction === "below_is_bad" ? "at least" : "at most"} {fmtKri(r, r.kri_threshold)}</span>
        </div>
        <div style={{ ...monoCaption, fontSize: 10 }}>MEASURE({r.kri_measure}) · {r.kri_metric_view}</div>
      </div>) },
    { key: "controls", label: "Mitigating controls (latest run)", render: (r) => (
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap", maxWidth: 250 }}>
        {r.linked_controls.map((c) => (
          <button key={c.control_id} onClick={() => onNavigate("checklist", { focusId: c.control_id })}
                  title={`${c.control_id}: ${c.result}${c.open_exceptions ? `, ${c.open_exceptions} open exceptions` : ""}`}
                  style={{ fontFamily: "var(--font-mono)", fontSize: 10, padding: "2px 7px", borderRadius: "var(--radius-pill)", cursor: "pointer",
                           border: `1px solid ${toneColor(c.result)}`, background: "var(--bg-canvas)", color: "var(--fg-1)",
                           display: "inline-flex", alignItems: "center", gap: 4 }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: toneColor(c.result) }} />{c.control_id}
          </button>
        ))}
      </div>) },
    { key: "residual", label: "Residual", render: (r) => (
      <div>
        <StatusBadge status={r.residual} small />
        <div style={{ ...monoCaption, fontSize: 10, marginTop: 3 }}>{r.failing_controls} of {r.linked_controls.length} controls failing</div>
      </div>) },
  ];
  return (
    <Stack gap="var(--space-2)">
      <DataTable columns={cols} rows={rows} rowKey={(r) => r.risk_id} />
      <span style={monoCaption}>
        Residual rule: elevated when the KRI is breached and a mitigating control is failing; monitor when one of the two holds; otherwise within appetite.
      </span>
    </Stack>
  );
}

/** 5 x 5 likelihood x impact grid with the risk's cell filled. */
function RiskHeatCell({ likelihood, impact }: { likelihood: number; impact: number }) {
  const score = likelihood * impact;
  const fill = score >= 15 ? "var(--db-lava-600)" : score >= 8 ? "var(--db-yellow-600)" : "var(--db-navy-400)";
  const c = 7, g = 1;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }} title={`Likelihood ${likelihood} x impact ${impact} = ${score}`}>
      <svg width={5 * (c + g)} height={5 * (c + g)} aria-label={`likelihood ${likelihood}, impact ${impact}`}>
        {Array.from({ length: 25 }, (_, k) => {
          const l = (k % 5) + 1, i = 5 - Math.floor(k / 5);
          const on = l === likelihood && i === impact;
          return <rect key={k} x={(l - 1) * (c + g)} y={(5 - i) * (c + g)} width={c} height={c} rx={1}
                       fill={on ? fill : "var(--border)"} opacity={on ? 1 : 0.55} />;
        })}
      </svg>
      <span style={{ fontFamily: "var(--font-mono)", fontWeight: 700 }}>{score}</span>
    </div>
  );
}

// ── SOX pack ────────────────────────────────────────────────────────────────
function SoxPackView({ d, onNavigate }: { d: SoxPack; onNavigate: PageProps["onNavigate"] }) {
  const lanes = ["management", "assurance"].map((k) => d.by_lane.find((x) => x.lane === k) ?? { lane: k, controls: 0, failed: 0 });
  return (
    <Stack>
      <Grid cols={3}>
        <div>
          <div style={{ ...monoCaption, textTransform: "uppercase", marginBottom: 8 }}>By module</div>
          <RiskPassBars rows={d.by_module.map((m) => ({ key: m.module, label: `${m.module} ${m.module_name}`, controls: m.controls, failed: m.failed,
                                                        note: m.key_failed ? `${m.key_failed} key` : undefined }))} />
        </div>
        <div>
          <div style={{ ...monoCaption, textTransform: "uppercase", marginBottom: 8 }}>By financial statement assertion</div>
          <RiskPassBars rows={d.by_assertion.map((a) => ({ key: a.assertion, label: String(a.assertion).replace(/_/g, " "), controls: a.controls, failed: a.failed }))} />
        </div>
        <div>
          <div style={{ ...monoCaption, textTransform: "uppercase", marginBottom: 8 }}>By lane</div>
          <Stack gap="var(--space-3)">
            {lanes.map((l) => {
              const meta = LANE_LABEL[l.lane] ?? { title: l.lane, sub: "" };
              const pass = Number(l.controls) - Number(l.failed);
              return (
                <div key={l.lane} style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: "10px 12px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                    <span style={{ fontWeight: 700, fontSize: "var(--fs-body-sm)" }}>{meta.title}</span>
                    <Mono>{fmtInt(pass)} / {fmtInt(l.controls)} passing</Mono>
                  </div>
                  <div style={{ ...monoCaption, marginTop: 2 }}>{meta.sub}</div>
                </div>
              );
            })}
            <span style={monoCaption}>Both lanes read the same results ledger, so management and Internal Audit work from the same evidence.</span>
          </Stack>
        </div>
      </Grid>

      <Grid cols="minmax(0, 2fr) minmax(0, 1fr)">
        <div>
          <div style={{ ...monoCaption, textTransform: "uppercase", marginBottom: 8 }}>
            Open key-control exceptions and deficiency dispositions ({fmtInt(d.deficiencies.length)})
          </div>
          <DataTable<Row>
            rows={d.deficiencies} rowKey={(r) => r.exception_id} dense maxHeight={420}
            onRowClick={(r) => onNavigate("exceptions", { focusId: r.exception_id })}
            empty="No open key-control exceptions or deficiencies for this period."
            columns={[
              { key: "control_id", label: "Control", render: (r) => (
                <div><Mono>{r.control_id}</Mono>{r.key_control && <Mono dim style={{ marginLeft: 6 }}>KEY</Mono>}
                  <div style={{ fontSize: "var(--fs-caption)", color: "var(--fg-2)" }}>{r.control_title}</div></div>) },
              { key: "entity_code", label: "Entity", mono: true },
              { key: "detected_value", label: "Detected", render: (r) => <span style={{ fontSize: "var(--fs-caption)" }}>{r.detected_value}</span> },
              { key: "amount_usd", label: "Amount", align: "right", render: (r) => fmtUSD(r.amount_usd, true) },
              { key: "disposition_status", label: "Review", render: (r) => <StatusBadge status={r.disposition === "deficiency" ? "fail" : r.disposition_status}
                                                                                       label={r.disposition === "deficiency" ? "deficiency" : r.disposition_status} small /> },
            ]} />
        </div>
        <div>
          <div style={{ ...monoCaption, textTransform: "uppercase", marginBottom: 8 }}>Remediation by disposition</div>
          <DataTable<Row>
            rows={d.remediation} rowKey={(r) => `${r.disposition}|${r.disposition_status}`} dense
            empty="No exceptions in this period."
            columns={[
              { key: "disposition", label: "Disposition", render: (r) => r.disposition ?? <span style={{ color: "var(--fg-3)" }}>not yet dispositioned</span> },
              { key: "disposition_status", label: "Status", render: (r) => <StatusBadge status={r.disposition_status} small /> },
              { key: "n", label: "Items", align: "right", render: (r) => fmtInt(r.n) },
              { key: "amount_usd", label: "Amount", align: "right", render: (r) => fmtUSD(r.amount_usd, true) },
            ]} />
          <div style={{ ...monoCaption, marginTop: 8 }}>
            Approved means dispositioned under four-eyes review: proposed by one person, approved by another.
          </div>
        </div>
      </Grid>
    </Stack>
  );
}

/** Passing vs failing controls per group: navy for passing, Lava for failing. */
function RiskPassBars({ rows }: { rows: { key: string; label: string; controls: number; failed: number; note?: string }[] }) {
  const max = Math.max(1, ...rows.map((r) => Number(r.controls)));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {rows.map((r) => {
        const pass = Number(r.controls) - Number(r.failed);
        return (
          <div key={r.key}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: "var(--fs-caption)", marginBottom: 3 }}>
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={r.label}>{r.label}</span>
              <Mono dim>{pass}/{r.controls}{r.note ? ` · ${r.note} failing` : ""}</Mono>
            </div>
            <div style={{ display: "flex", height: 8, borderRadius: 4, overflow: "hidden", background: "var(--bg-subtle)", width: `${(Number(r.controls) / max) * 100}%` }}>
              <div style={{ width: `${(pass / Math.max(1, Number(r.controls))) * 100}%`, background: "var(--db-navy-700)" }} />
              <div style={{ width: `${(Number(r.failed) / Math.max(1, Number(r.controls))) * 100}%`, background: "var(--db-lava-600)" }} />
            </div>
          </div>
        );
      })}
      <div style={{ display: "flex", gap: 12, ...monoCaption }}>
        <span><span style={{ display: "inline-block", width: 10, height: 6, background: "var(--db-navy-700)", marginRight: 4 }} />passing or resolved</span>
        <span><span style={{ display: "inline-block", width: 10, height: 6, background: "var(--db-lava-600)", marginRight: 4 }} />failing</span>
      </div>
    </div>
  );
}

// ── AI summary ──────────────────────────────────────────────────────────────
function fmtNumber(k: string, v: unknown): string {
  if (v == null) return "—";
  if (typeof v !== "number") return String(v);
  if (k.endsWith("_pct") || k.endsWith("_rate")) return fmtPct(v * 100);
  if (k.endsWith("_usd")) return fmtUSD(v);
  return Number.isInteger(v) ? fmtInt(v) : v.toFixed(2);
}

function AiSummary({ period }: { period: string }) {
  const [state, setState] = useState<{ loading: boolean; error: string | null; data: ReportSummary | null }>({ loading: false, error: null, data: null });
  const run = async () => {
    setState({ loading: true, error: null, data: null });
    try {
      setState({ loading: false, error: null, data: await draftReportSummary(period) });
    } catch (e) {
      console.error(e);
      setState({ loading: false, error: e instanceof Error ? e.message : String(e), data: null });
    }
  };
  const download = () => {
    if (!state.data) return;
    const blob = new Blob([state.data.markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `corvane-close-and-sox-status-${state.data.period}.md`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };
  const numbers = state.data
    ? Object.entries(state.data.numbers).filter(([k]) => k !== "failed_controls").map(([k, v]) => ({ measure: k, value: fmtNumber(k, v) }))
    : [];
  const failed = (state.data?.numbers.failed_controls ?? []) as Row[];

  return (
    <Section eyebrow="Audit committee pack" title="Close and SOX status summary"
             right={
               <>
                 {state.data && <SecondaryBtn onClick={download}><Icon name="download" size={14} /> Download .md</SecondaryBtn>}
                 <PrimaryBtn onClick={run} disabled={state.loading}><Icon name="spark" size={14} /> {state.data ? "Redraft" : "Draft summary with AI"}</PrimaryBtn>
               </>
             }>
      {!state.data && !state.loading && !state.error && (
        <div style={{ color: "var(--fg-2)", fontSize: "var(--fs-body-sm)" }}>
          Drafts a one-page summary for {period} from the governed numbers (close progress, control results, exceptions, reconciliations,
          variances). The numbers it was given are listed next to the draft so a reviewer can check each one.
        </div>
      )}
      {state.loading && <LoadingNote height={120} text="drafting from the governed numbers…" />}
      {state.error && <ErrorNote message={state.error} onRetry={run} />}
      {state.data && (
        <Grid cols="minmax(0, 3fr) minmax(0, 2fr)">
          <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: "var(--space-4) var(--space-5)" }}>
            <div style={{ marginBottom: 10 }}><AiBadge model={state.data.model} text="AI-generated draft" /></div>
            <Markdown text={state.data.markdown} />
          </div>
          <div>
            <div style={{ ...monoCaption, textTransform: "uppercase", marginBottom: 8 }}>Numbers the draft was given (metric views)</div>
            <DataTable<Row> rows={numbers} rowKey={(r) => r.measure} dense
                            columns={[{ key: "measure", label: "Measure", mono: true }, { key: "value", label: "Value", align: "right" }]} />
            {failed.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <div style={{ ...monoCaption, textTransform: "uppercase", marginBottom: 6 }}>Failing controls in the latest run</div>
                <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                  {failed.map((c) => (
                    <span key={c.control_id} title={c.control_title} style={{ ...linkBtn, cursor: "default", fontFamily: "var(--font-mono)", fontSize: 10,
                          padding: "2px 7px", border: "1px solid var(--danger)", borderRadius: "var(--radius-pill)", color: "var(--fg-1)" }}>
                      {c.control_id}{c.key_control ? " KEY" : ""}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </Grid>
      )}
    </Section>
  );
}

// FP&A variance review as a management review control (FPA-01..FPA-04).
// The controller explains a material variance (optionally starting from an AI
// draft built from the actual postings); an independent reviewer acknowledges
// it. Four-eyes is enforced by the server; its message is shown verbatim.
import React, { useEffect, useState } from "react";
import { acknowledgeVariance, draftVarianceExplanation, explainVariance, getVariances } from "../../api";
import type { Row } from "../../types";
import type { NavOpts, PageId } from "../../App";
import { PrimaryBtn, SecondaryBtn } from "../Buttons";
import { Icon } from "../Icon";
import { ChecklistSlice } from "../ChecklistSlice";
import {
  AiBadge, Async, DataTable, Drawer, KV, Mono, Notice, RowsTable, Section, Stack, StatusBadge, TextArea, monoCaption, useApi,
  type Column,
} from "../ui";
import { fmtDate, fmtPct, fmtUSD } from "../../format";

export function varianceState(v: Row): { status: string; label: string } {
  if (v.acknowledged_by || v.independently_acknowledged) return { status: "approved", label: "Acknowledged" };
  if (v.explained_by) return { status: "proposed", label: "Explained, awaiting acknowledgement" };
  return { status: "open", label: "Unexplained" };
}

export function VarianceReview({ period, entity, onNavigate }: { period: string; entity: string; onNavigate: (p: PageId, o?: NavOpts) => void }) {
  const st = useApi(() => getVariances({ period, entity, material_only: true }), [period, entity]);
  const [selKey, setSelKey] = useState<string | null>(null);
  const sel = st.data?.rows.find((r) => r.variance_key === selKey) ?? null;
  const cols: Column<Row>[] = [
    { key: "entity_code", label: "Entity", mono: true },
    { key: "line_name", label: "Line", render: (r) => <span><Mono dim>{r.fsli_code}</Mono> {r.line_name}</span> },
    { key: "actual_usd", label: "Actual", align: "right", render: (r) => fmtUSD(Number(r.actual_usd)) },
    { key: "budget_compare_usd", label: "Budget compared", align: "right", render: (r) => fmtUSD(Number(r.budget_compare_usd)) },
    { key: "variance_usd", label: "Variance", align: "right",
      render: (r) => <span style={{ color: r.is_favorable ? "var(--fg-1)" : "var(--danger)" }}>{Number(r.variance_usd) > 0 ? "+" : ""}{fmtUSD(Number(r.variance_usd))}</span> },
    { key: "variance_pct", label: "%", align: "right", render: (r) => r.variance_pct == null ? "—" : fmtPct(Number(r.variance_pct) * 100) },
    { key: "state", label: "Review", render: (r) => { const s = varianceState(r); return <StatusBadge status={s.status} label={s.label} small />; } },
    { key: "explained_by", label: "Explained by", render: (r) => r.explained_by ?? <span style={{ color: "var(--fg-3)" }}>—</span> },
    { key: "acknowledged_by", label: "Acknowledged by", render: (r) => r.acknowledged_by ?? <span style={{ color: "var(--fg-3)" }}>—</span> },
  ];
  return (
    <Stack>
      <Section title="Material variances" eyebrow={`Management review · ${period} · ${entity === "ALL" ? "all entities" : entity}`}
               right={<Mono dim>material = over max($250k, 10%) or |z| &gt; 2.5</Mono>}>
        <Async state={st} empty={(d) => d.rows.length === 0}
               emptyText="No material variance for this selection. FPA-02 flags lines over the materiality rule on every control run.">
          {(d) => (
            <>
              <DataTable columns={cols} rows={d.rows} rowKey={(r) => String(r.variance_key)} onRowClick={(r) => setSelKey(String(r.variance_key))} activeKey={selKey} />
              <div style={{ ...monoCaption, marginTop: 8 }}>
                {d.rows[0]?.period_status === "ACTIVE"
                  ? "Active close: actuals month to date against the phased MTD budget (continuous flux)."
                  : "Closed period: full-month actuals against the full-month budget."}
              </div>
            </>
          )}
        </Async>
      </Section>
      <Section title="FP&A review controls" eyebrow="Audit checklist slice · latest control run">
        <ChecklistSlice controlIds={["FPA-01", "FPA-02", "FPA-03", "FPA-04"]} period={period} onNavigate={onNavigate} title="FP&A variance review" />
      </Section>
      <VarianceDrawer v={sel} onClose={() => setSelKey(null)} onChanged={() => st.reload()} />
    </Stack>
  );
}

function VarianceDrawer({ v, onClose, onChanged }: { v: Row | null; onClose: () => void; onChanged: () => void }) {
  const [text, setText] = useState("");
  const [ai, setAi] = useState<{ draft: string; drivers: Row[]; model: string; label: string } | null>(null);
  const [usedDraft, setUsedDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ kind: "success" | "danger"; text: string } | null>(null);
  const key = v ? String(v.variance_key) : null;
  useEffect(() => {
    setText(String(v?.explanation ?? ""));
    setAi(null); setUsedDraft(null); setMsg(null);
    // reset only when a different variance opens
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  if (!v) return null;
  const s = varianceState(v);
  const run = async (what: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(what); setMsg(null);
    try { await fn(); setMsg({ kind: "success", text: ok }); onChanged(); }
    catch (e) { setMsg({ kind: "danger", text: e instanceof Error ? e.message : String(e) }); }
    finally { setBusy(null); }
  };
  return (
    <Drawer open={!!v} onClose={onClose} width={820}
            title={`${v.entity_code} · ${v.line_name}`} subtitle={<span><Mono dim>{v.variance_key}</Mono> · {v.period_status === "ACTIVE" ? "active close, month to date" : "closed period"}</span>}
            right={<StatusBadge status={s.status} label={s.label} />}>
      <Stack>
        <Section padding="var(--space-4)">
          <KV cols={2} items={[
            ["Actual", fmtUSD(Number(v.actual_usd))], ["Budget compared", fmtUSD(Number(v.budget_compare_usd))],
            ["Variance", `${fmtUSD(Number(v.variance_usd))} (${v.variance_pct == null ? "—" : fmtPct(Number(v.variance_pct) * 100)})`],
            ["Direction", v.is_favorable ? "favorable" : "unfavorable"],
            ["Full-month budget", fmtUSD(Number(v.budget_usd))], ["Forecast", fmtUSD(Number(v.forecast_usd))],
            ["Prior period", fmtUSD(Number(v.prior_period_usd))], ["Prior year", fmtUSD(Number(v.prior_year_usd))],
            ["Explanation due", fmtDate(v.explanation_due)], ["Statistical outlier", v.is_statistical_outlier ? `yes (z ${Number(v.zscore).toFixed(1)})` : "no"],
          ]} />
        </Section>

        <Section title="Explanation" eyebrow="FPA-03 · controller">
          {v.explanation ? (
            <div style={{ padding: "10px 12px", borderLeft: "3px solid var(--db-navy-400)", background: "var(--bg-subtle)", marginBottom: 12, fontSize: "var(--fs-body-sm)" }}>
              {v.explanation}
              <div style={{ ...monoCaption, marginTop: 6 }}>by {v.explained_by}{v.explained_at ? ` · ${String(v.explained_at).slice(0, 16)}` : ""}{v.pending_sync ? " · recorded, applied on the next control run" : ""}</div>
            </div>
          ) : <div style={{ ...monoCaption, marginBottom: 10 }}>No explanation on file.</div>}
          <TextArea value={text} onChange={setText} rows={4} placeholder="Explain the driver of the variance, citing the postings." />
          <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
            <SecondaryBtn disabled={!!busy} onClick={() => run("ai", async () => setAi(await draftVarianceExplanation(String(v.variance_key))), "Draft ready below. Review and edit before recording it.")}>
              <Icon name="spark" size={14} /> {busy === "ai" ? "Drafting…" : "Draft with AI"}
            </SecondaryBtn>
            <PrimaryBtn disabled={!!busy || !text.trim()} onClick={() => run("explain", () => explainVariance(String(v.variance_key), text.trim(), usedDraft),
                                                                                   "Explanation recorded. The next control run applies it to FPA-03.")}>
              {busy === "explain" ? "Recording…" : "Record explanation"}
            </PrimaryBtn>
          </div>
          {ai && (
            <div style={{ marginTop: 14, padding: 12, border: "1px dashed var(--db-navy-400)", borderRadius: "var(--radius-md)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                <AiBadge model={ai.model} />
                <SecondaryBtn onClick={() => { setText(ai.draft); setUsedDraft(ai.draft); }}>Use this draft</SecondaryBtn>
              </div>
              <div style={{ fontSize: "var(--fs-body-sm)", whiteSpace: "pre-wrap", marginBottom: 8 }}>{ai.draft}</div>
              <div style={{ ...monoCaption, marginBottom: 6 }}>{ai.label} Drivers used (largest postings on this line):</div>
              <RowsTable rows={ai.drivers} maxHeight={220} />
            </div>
          )}
        </Section>

        <Section title="Independent acknowledgement" eyebrow="FPA-04 · reviewer">
          {v.acknowledged_by ? (
            <div style={{ fontSize: "var(--fs-body-sm)" }}>Acknowledged by {v.acknowledged_by}{v.acknowledged_at ? ` on ${String(v.acknowledged_at).slice(0, 16)}` : ""}.</div>
          ) : (
            <>
              <div style={{ ...monoCaption, marginBottom: 10 }}>The reviewer must be a different person from the author of the explanation.</div>
              <PrimaryBtn disabled={!!busy || !v.explained_by} onClick={() => run("ack", () => acknowledgeVariance(String(v.variance_key)),
                                                                                  "Acknowledgement recorded. The next control run applies it to FPA-04.")}>
                <Icon name="check" size={14} /> {busy === "ack" ? "Recording…" : "Acknowledge explanation"}
              </PrimaryBtn>
            </>
          )}
        </Section>
        {msg && <Notice kind={msg.kind} onClose={() => setMsg(null)}>{msg.text}</Notice>}
      </Stack>
    </Drawer>
  );
}


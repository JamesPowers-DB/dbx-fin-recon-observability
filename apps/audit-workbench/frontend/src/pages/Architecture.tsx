// Architecture: ties the business context (the close lifecycle) to the assets this
// demo deployed and the Databricks features underneath, with live status per node.
// Tabs: platform map, audit workflow parity, briefing coverage (acceptance matrix).
import React, { useMemo, useState } from "react";
import type { NavOpts, PageId, PageProps } from "../App";
import { getArchitectureStatus } from "../api";
import type { ArchitectureStatus, Probe, Row } from "../types";
import {
  DataTable, DeepLink, Drawer, EmptyNote, ErrorNote, Grid, KV, Mono, Notice, Page, Section, Select, Stack, StatusBadge, Tabs,
  fillLink, monoCaption, useApi, type ApiState,
} from "../components/ui";
import { PageHero } from "../components/layout/PageHero";
import { SecondaryBtn } from "../components/Buttons";
import { Icon } from "../components/Icon";
import { fmtInt } from "../format";
import { ALL_NODES, ASSETS, FEATURES, NODE_BY_ID, STAGES, TIER_LABEL, TIER_NOTE, type MapNode } from "../architecture/platformMap";
import { PlatformMapView, STATE_COLOR, STATE_LABEL, TierBadge, type NodeState, type NodeStatus } from "../architecture/PlatformMapView";
import { GRC_LABEL, PARITY, PARITY_NOTE, WHERE_IT_RUNS, type ParityStep } from "../architecture/workflowParity";
import { COVERAGE, COVERAGE_AREAS, TIER_DESC, type CoverageRow } from "../architecture/coverage";

type TabId = "platform" | "workflow" | "coverage";
const TAB_IDS: TabId[] = ["platform", "workflow", "coverage"];

const PAGE_LABEL: Record<PageId, string> = {
  close: "Close Cockpit", checklist: "Audit Checklist", exceptions: "Exceptions & Review", modules: "Recons & Testing",
  statements: "Financial Statements", assistant: "Audit Assistant", reporting: "Risk & Reporting", lineage: "Data Quality & Lineage",
  architecture: "Architecture",
};

export function Architecture({ onNavigate, nav }: PageProps) {
  const initialTab: TabId = TAB_IDS.includes(nav.tab as TabId) ? (nav.tab as TabId) : "platform";
  const [tab, setTab] = useState<TabId>(initialTab);
  const st = useApi(getArchitectureStatus, []);
  const focus = nav.focusId ? (NODE_BY_ID[`asset:${nav.focusId}`] ?? NODE_BY_ID[`feature:${nav.focusId}`]) : undefined;
  const [selected, setSelected] = useState<string | null>(focus ? `${focus.kind}:${focus.id}` : null);
  const go = (p: PageId, o?: NavOpts) => (p === "architecture" ? setTab((o?.tab as TabId) ?? "platform") : onNavigate(p, o));

  return (
    <Page>
      <PageHero
        eyebrow="Platform"
        title="Architecture"
        subtitle="How Corvane Technologies' continuous close runs on Databricks: the business lifecycle, the assets this demo deployed for each stage, and the platform features underneath. Status is live."
        right={tab === "platform" ? <SecondaryBtn onClick={st.reload} disabled={st.loading}><Icon name="refresh" size={14} /> {st.loading ? "Checking…" : "Refresh status"}</SecondaryBtn> : undefined}
      />
      <Tabs<TabId>
        tabs={[
          { id: "platform", label: "Platform map" },
          { id: "workflow", label: "Audit workflow" },
          { id: "coverage", label: "Briefing coverage", badge: <Mono dim>{COVERAGE.length}</Mono> },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === "platform" && <PlatformTab st={st} selected={selected} setSelected={setSelected} go={go} />}
      {tab === "workflow" && <WorkflowTab go={go} />}
      {tab === "coverage" && <CoverageTab go={go} />}
    </Page>
  );
}

// ── Live status binder ──────────────────────────────────────────────────────
const SYSTEMS: [string, string][] = [
  ["oracle", "Oracle Fusion ERP"], ["sfdc", "Salesforce"], ["workday", "Workday"], ["anaplan", "Anaplan"],
  ["bank", "Bank feed (camt.053)"], ["close", "Close tool export"], ["docs", "Evidence PDFs"],
];

function rows(p?: Probe<Row[]>): Row[] { return p?.ok && Array.isArray(p.data) ? p.data : []; }
function first(p?: Probe<Row[]>): Row | undefined { return rows(p)[0]; }
function obj(p?: Probe<Row>): Row | undefined { return p?.ok && p.data && !Array.isArray(p.data) ? p.data : undefined; }

function fmtWhen(v: unknown): string {
  if (v == null || v === "") return "—";
  const d = typeof v === "number" ? new Date(v) : new Date(String(v).replace(" ", "T") + (/Z|[+-]\d\d:?\d\d$/.test(String(v)) ? "" : "Z"));
  if (Number.isNaN(d.getTime())) return String(v);
  return `${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })} ${d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false })}`;
}
const compact = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(2)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n));

interface Bound extends NodeStatus { facts: [string, React.ReactNode][]; links: { label: string; href: string | null }[]; }

function layerCount(s: ArchitectureStatus, layer: string): number {
  return Number(rows(s.tables).find((r) => r.layer === layer)?.n ?? 0);
}

function jobFacts(p: Probe<Row> | undefined): { state: NodeState; summary: string[]; facts: [string, React.ReactNode][]; href: string | null; error?: string } {
  if (!p) return { state: "static", summary: [], facts: [], href: null };
  if (!p.ok) return { state: "error", summary: [], facts: [], href: null, error: p.error };
  const lr = (obj(p)?.last_run ?? null) as Row | null;
  if (!lr) return { state: "warn", summary: ["no runs yet"], facts: [["Last run", "none"]], href: null };
  const result = lr.result ?? lr.state;
  const state: NodeState = lr.result === "SUCCESS" || ["RUNNING", "PENDING", "QUEUED"].includes(lr.state) ? "ok" : "warn";
  return {
    state, href: lr.run_page_url ?? null,
    summary: [`last run ${String(result ?? "").toLowerCase()} · ${fmtWhen(lr.start_time)}`],
    facts: [["Last run", <StatusBadge key="s" status={result} small />], ["Started", fmtWhen(lr.start_time)], ["Ended", fmtWhen(lr.end_time)], ["Run id", <Mono key="r">{String(lr.run_id)}</Mono>]],
  };
}

export function bind(n: MapNode, s: ArchitectureStatus | null, loading: boolean): Bound {
  if (!s) return { state: "static", summary: loading ? ["checking…"] : [], facts: [], links: [] };
  const a = obj(s.assets) ?? {};
  const L = s.links;
  const ledger = first(s.ledger);
  const out = (state: NodeState, summary: string[], facts: [string, React.ReactNode][], links: { label: string; href: string | null }[] = [], error?: string): Bound =>
    ({ state, summary, facts, links, error });
  const probeErr = (p?: Probe<unknown>) => (p && !p.ok ? p.error : undefined);

  switch (n.probe) {
    case "sources": {
      if (!s.sources.ok) return out("error", [], [], [], s.sources.error);
      const by = new Map<string, { tables: number; rows: number }>();
      for (const r of rows(s.sources)) {
        const k = String(r.dataset).replace(/^bronze_/, "").split("_")[0];
        const cur = by.get(k) ?? { tables: 0, rows: 0 };
        by.set(k, { tables: cur.tables + 1, rows: cur.rows + Number(r.rows_in_table ?? 0) });
      }
      const total = [...by.values()].reduce((x, y) => x + y.rows, 0);
      const tables = [...by.values()].reduce((x, y) => x + y.tables, 0);
      return out(total > 0 ? "ok" : "warn", [`${by.size} systems · ${tables} bronze tables`, `${compact(total)} rows ingested`],
        SYSTEMS.map(([k, label]) => [label, by.has(k) ? `${fmtInt(by.get(k)!.rows)} rows in ${by.get(k)!.tables} table${by.get(k)!.tables === 1 ? "" : "s"}` : "—"] as [string, React.ReactNode]),
        [{ label: "Schema in Catalog Explorer", href: a.schema_url ?? null }]);
    }
    case "refresh": {
      const j = jobFacts(s.refresh);
      return out(j.state, j.summary.length ? j.summary : ["weekdays 05:00 UTC"], [["Schedule", "weekdays 05:00 UTC"], ...j.facts],
        [{ label: "Last run", href: j.href }, { label: "Job", href: a.refresh_url ?? null }], j.error);
    }
    case "library": {
      const l = first(s.library);
      if (!l) return out(s.library.ok ? "warn" : "error", [], [], [], probeErr(s.library));
      return out("ok", [`${l.controls} controls · ${l.key_controls} key`, `published ${fmtWhen(l.published_at)}`],
        [["Controls", fmtInt(l.controls)], ["Key controls", fmtInt(l.key_controls)], ["Modules", fmtInt(l.modules)], ["Published", fmtWhen(l.published_at)],
         ["Library hash", <Mono key="h">{String(ledger?.library_hash ?? "—")}</Mono>]],
        [{ label: "gold_dim_control", href: fillLink(L?.table, { table: "gold_dim_control" }) }]);
    }
    case "pipeline":
    case "pipelines": {
      const p = first(s.pipeline);
      if (!p) return out(s.pipeline.ok ? "warn" : "error", s.pipeline.ok ? ["no update recorded yet"] : [], [], [], probeErr(s.pipeline));
      const failed = Number(p.failed_records ?? 0);
      return out("ok", [`${p.datasets} datasets · update ${String(p.update_id).slice(0, 8)}`, `${fmtInt(failed)} rows failed WARN expectations`],
        [["Last tested update", <Mono key="u">{String(p.update_id)}</Mono>], ["Recorded", fmtWhen(p.recorded_at)], ["Datasets", fmtInt(p.datasets)],
         ["Rows written", fmtInt(p.rows_written)], ["Expectation failures", `${fmtInt(failed)} rows (kept: WARN)`],
         ["Tables", `${layerCount(s, "bronze")} bronze · ${layerCount(s, "silver")} silver · ${layerCount(s, "gold")} gold`]],
        [{ label: "Pipeline update", href: fillLink(L?.pipeline_update, { update_id: p.update_id }) }, { label: "Pipeline", href: a.pipeline_url ?? null }]);
    }
    case "run_controls":
    case "jobs": {
      const j = jobFacts(s.run_controls);
      if (!ledger && j.state === "error") return out("error", [], [], [], j.error);
      const gate = ledger?.gate_result as string | undefined;
      const state: NodeState = gate === "FAIL" ? "warn" : ledger ? "ok" : j.state;
      const runHref = fillLink(L?.job_run, { job_id: ledger?.job_id, run_id: ledger?.job_run_id });
      return out(state, ledger ? [`run ${String(ledger.status ?? "").toLowerCase()} · ${fmtWhen(ledger.started_at)}`,
                                  `${ledger.controls_executed ?? "—"} controls · gate ${String(gate ?? "pending").toLowerCase()}`] : j.summary,
        [["Latest ledger run", <Mono key="r">{String(ledger?.job_run_id ?? "—")}</Mono>], ["Status", ledger ? <StatusBadge key="s" status={String(ledger.status)} small /> : "—"],
         ["Trigger", `${ledger?.trigger_source ?? "—"}${ledger?.requested_by ? ` by ${ledger.requested_by}` : ""}`], ["Started", fmtWhen(ledger?.started_at)],
         ["Controls executed", fmtInt(ledger?.controls_executed)], ["Controls failed", fmtInt(ledger?.controls_failed)],
         ["Integrity gate (PLT-01)", gate ? <StatusBadge key="g" status={gate === "PASS" ? "PASS" : "FAIL"} label={gate} small /> : "pending"],
         ...j.facts.map(([k, v]) => [`Jobs API: ${k.toLowerCase()}`, v] as [string, React.ReactNode])],
        [{ label: "Ledger run", href: runHref }, { label: "Job", href: a.run_controls_url ?? null }],
        j.state === "error" ? `Jobs API: ${j.error}` : undefined);
    }
    case "ledger": {
      if (!ledger) return out(s.ledger.ok ? "warn" : "error", [], [], [], probeErr(s.ledger));
      return out("ok", [`${fmtInt(ledger.exceptions_found)} exceptions in ${ledger.active_period}`, `${fmtInt(ledger.new_exceptions ?? 0)} new · ${fmtInt(ledger.resolved_exceptions ?? 0)} resolved`],
        [["Active close", String(ledger.active_period ?? "—")], ["Exceptions found", fmtInt(ledger.exceptions_found)], ["New this run", fmtInt(ledger.new_exceptions)],
         ["Resolved this run", fmtInt(ledger.resolved_exceptions)], ["Data cutoff", String(ledger.data_cutoff ?? "—")]],
        [{ label: "meta_control_results", href: fillLink(L?.table, { table: "meta_control_results" }) },
         { label: "meta_control_exception_log", href: fillLink(L?.table, { table: "meta_control_exception_log" }) }]);
    }
    case "alert":
      return out("static", ["06:15, 12:15, 18:15 UTC"], [["Condition", "critical open exceptions in the active close > 0"], ["Schedule", "06:15, 12:15, 18:15 UTC"],
        ["Source", "gold_mv_exceptions (metric view)"]], [{ label: "SQL alerts", href: a.alerts_url ?? null }]);
    case "triage": {
      const t = first(s.triage);
      if (!t) return out(s.triage.ok ? "warn" : "error", [], [], [], probeErr(s.triage));
      const n2 = Number(t.triaged ?? 0);
      return out(n2 > 0 ? "ok" : "warn", [`${fmtInt(n2)} exceptions triaged`, String(t.model ?? "")],
        [["Triaged", fmtInt(n2)], ["Model", <Mono key="m">{String(t.model ?? a.triage_endpoint ?? "—")}</Mono>], ["Last triaged", fmtWhen(t.last_triaged_at)]],
        [{ label: "ml_exception_triage", href: fillLink(L?.table, { table: "ml_exception_triage" }) }]);
    }
    case "agent":
    case "fmapi":
      return out("static", [String(a.agent_endpoint ?? "")], [["Agent endpoint", <Mono key="a">{String(a.agent_endpoint ?? "—")}</Mono>],
        ["Triage endpoint", <Mono key="t">{String(a.triage_endpoint ?? "—")}</Mono>], ["Auth", "on-behalf-of the user (model-serving scope)"]],
        [{ label: "Serving endpoint", href: a.agent_endpoint_url ?? null }]);
    case "documents":
    case "aifn": {
      const d = first(s.documents);
      const t = first(s.triage);
      if (!d && !s.documents.ok) return out("error", [], [], [], probeErr(s.documents));
      return out(Number(d?.parsed ?? 0) > 0 ? "ok" : "warn", [`${fmtInt(d?.parsed)} documents parsed`],
        [["Documents parsed (ai_parse_document)", fmtInt(d?.parsed)], ["Exceptions triaged (ai_query)", fmtInt(t?.triaged)]],
        [{ label: "silver_document_parsed", href: fillLink(L?.table, { table: "silver_document_parsed" }) }]);
    }
    case "lakebase": {
      if (!s.lakebase.ok) return out("error", [], [], [], s.lakebase.error);
      const l = obj(s.lakebase) ?? {};
      return out("ok", [`${fmtInt(l.review_actions)} review actions`, `${fmtInt(l.working_papers)} working papers`],
        [["Review actions", fmtInt(l.review_actions)], ["Working papers", fmtInt(l.working_papers)], ["Chat sessions", fmtInt(l.chat_sessions)],
         ["Endpoint", <Mono key="e">{String(l.endpoint ?? "—")}</Mono>]]);
    }
    case "app":
      return out("ok", ["you are here", "OBO: sql, genie, model-serving, files"],
        [["Auth", "on-behalf-of the signed-in user"], ["User scopes", "sql, genie, model-serving, files"], ["Writes", "Lakebase only"],
         ["Starts runs as", "the app's service principal (requester recorded)"]]);
    case "close":
      if (!ledger) return out(s.ledger.ok ? "warn" : "error", [], [], [], probeErr(s.ledger));
      return out("ok", [`active close ${ledger.active_period}`, `derived by run ${String(ledger.job_run_id).slice(-6)}`],
        [["Active close", String(ledger.active_period ?? "—")], ["Derived by run", <Mono key="r">{String(ledger.job_run_id)}</Mono>]],
        [{ label: "meta_close_task_status", href: fillLink(L?.table, { table: "meta_close_task_status" }) }]);
    case "metric_views":
    case "mv": {
      if (!s.tables.ok) return out("error", [], [], [], s.tables.error);
      const mv = layerCount(s, "metric_view");
      return out(mv >= 7 ? "ok" : "warn", [`${mv} metric views`], [["Metric views", fmtInt(mv)], ["Queried by", "app, dashboard, Genie, alert, agent"]],
        [{ label: "gold_mv_close", href: fillLink(L?.table, { table: "gold_mv_close" }) }]);
    }
    case "dashboard":
      return a.dashboard_url ? out("ok", ["published"], [["Dashboard", "Fin Recon Observability - Continuous Close"]], [{ label: "Open dashboard", href: a.dashboard_url }])
        : out("warn", ["id not in app environment"], [["Dashboard", "DASHBOARD_ID is not set for this app"]]);
    case "genie": {
      if (!s.genie.ok) return out("error", [], [], [], s.genie.error);
      const g = obj(s.genie) ?? {};
      return g.space_id ? out("ok", ["space resolved by title"], [["Title", String(g.title)], ["Space id", <Mono key="g">{String(g.space_id)}</Mono>]], [{ label: "Open Genie", href: a.genie_url ?? null }])
        : out("warn", ["space not found"], [["Title", String(g.title ?? "—")], ["Space", "not provisioned yet (setup: provision_genie)"]]);
    }
    case "uc": {
      if (!s.tables.ok) return out("error", [], [], [], s.tables.error);
      const tagged = Number(first(s.tags)?.tagged ?? 0);
      const total = rows(s.tables).reduce((x, r) => x + Number(r.n ?? 0), 0);
      return out("ok", [`${total} objects in one schema`, `${tagged} tagged`],
        [["Schema", <Mono key="s">{`${a.catalog}.${a.schema}`}</Mono>],
         ...rows(s.tables).map((r) => [`${r.layer || "other"}`, fmtInt(r.n)] as [string, React.ReactNode]),
         ["Tagged tables", s.tags.ok ? fmtInt(tagged) : `probe failed: ${s.tags.error}`], ["Column mask", "mask_pii on legal_name and email (gold_fact_user_access)"]],
        [{ label: "Catalog Explorer", href: a.schema_url ?? null }]);
    }
    default:
      return out("static", [], [], []);
  }
}

// ── Platform tab ────────────────────────────────────────────────────────────
function PlatformTab({ st, selected, setSelected, go }: { st: ApiState<ArchitectureStatus>; selected: string | null; setSelected: (k: string | null) => void; go: (p: PageId, o?: NavOpts) => void }) {
  const status = (n: MapNode): NodeStatus => bind(n, st.data, st.loading);
  const counts = useMemo(() => {
    const c: Record<NodeState, number> = { ok: 0, warn: 0, error: 0, static: 0 };
    if (st.data) for (const n of ALL_NODES.filter((x) => x.tier === "live")) c[bind(n, st.data, false).state] += 1;
    return c;
  }, [st.data]);
  return (
    <Stack>
      {st.error && !st.data && <ErrorNote message={st.error} onRetry={st.reload} />}
      <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap", ...monoCaption }}>
        {(["ok", "warn", "error", "static"] as NodeState[]).map((k) => (
          <span key={k} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: STATE_COLOR[k], border: k === "static" ? "1px solid var(--fg-3)" : "none" }} />
            {STATE_LABEL[k]}{st.data ? ` (${counts[k]})` : ""}
          </span>
        ))}
        <span style={{ marginLeft: "auto" }}>Select a box to trace it to its stage and the features it uses.</span>
      </div>
      <Section padding="var(--space-5)">
        <PlatformMapView status={status} selected={selected} onSelect={setSelected} />
      </Section>
      <Grid cols={3}>
        {(["live", "config", "roadmap"] as const).map((t) => (
          <div key={t} style={{ display: "flex", gap: 10, alignItems: "flex-start", fontSize: "var(--fs-body-sm)", color: "var(--fg-2)" }}>
            <TierBadge tier={t} />
            <span>{TIER_NOTE[t]}</span>
          </div>
        ))}
      </Grid>
      <NodeDrawer k={selected} onClose={() => setSelected(null)} onSelect={setSelected} st={st} go={go} />
    </Stack>
  );
}

function NodeDrawer({ k, onClose, onSelect, st, go }: { k: string | null; onClose: () => void; onSelect: (k: string) => void; st: ApiState<ArchitectureStatus>; go: (p: PageId, o?: NavOpts) => void }) {
  if (!k) return null;
  const [kind, id] = k.split(":");
  if (kind === "stage") {
    const s = STAGES.find((x) => x.id === id);
    if (!s) return null;
    const assets = ASSETS.filter((a) => a.stage === id);
    return (
      <Drawer open onClose={onClose} title={`${String(s.n).padStart(2, "0")} ${s.label}`} subtitle={s.caption} width={620}>
        <Stack>
          <Section title="Deployed for this stage">
            <Stack gap="var(--space-2)">
              {assets.map((a) => <NodeLink key={a.id} n={a} onClick={() => onSelect(`asset:${a.id}`)} />)}
            </Stack>
          </Section>
          <div><SecondaryBtn onClick={() => { onClose(); go(s.page, s.tab ? { tab: s.tab } : undefined); }}>Open {PAGE_LABEL[s.page]} <Icon name="arrow-right" size={14} /></SecondaryBtn></div>
        </Stack>
      </Drawer>
    );
  }
  const n = NODE_BY_ID[k];
  if (!n) return null;
  const b = bind(n, st.data, st.loading);
  const stage = n.stage ? STAGES.find((x) => x.id === n.stage) : undefined;
  const linked = n.kind === "asset" ? (n.uses ?? []).map((f) => FEATURES.find((x) => x.id === f)).filter(Boolean) as MapNode[]
    : ASSETS.filter((a) => a.uses?.includes(n.id));
  const links = b.links.filter((l) => l.href);
  return (
    <Drawer open onClose={onClose} width={680}
            title={<span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>{n.label} <TierBadge tier={n.tier} /></span>}
            subtitle={<>{n.sub}{stage ? <> · stage <b>{stage.label}</b></> : null}</>}>
      <Stack>
        <Section title="What it does in the close">
          <p style={{ margin: 0, fontSize: "var(--fs-body-sm)", lineHeight: 1.6, color: "var(--fg-1)" }}>{n.does}</p>
          <p style={{ margin: "10px 0 0", ...monoCaption }}>{TIER_LABEL[n.tier]}: {TIER_NOTE[n.tier]}</p>
        </Section>
        {n.tier === "live" && (
          <Section title="Live status" right={<span style={{ display: "inline-flex", alignItems: "center", gap: 6, ...monoCaption }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: STATE_COLOR[b.state] }} />{STATE_LABEL[b.state]}</span>}>
            {b.error && <div style={{ marginBottom: 12 }}><Notice kind="danger">This probe failed: <Mono>{b.error}</Mono></Notice></div>}
            {b.facts.length ? <KV cols={1} items={b.facts} /> : !b.error && <span style={monoCaption}>{st.loading ? "checking…" : "This node has no live probe; it is deployed by the bundle."}</span>}
            {links.length > 0 && (
              <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 14, fontSize: "var(--fs-body-sm)" }}>
                {links.map((l) => <DeepLink key={l.label} href={l.href}>{l.label}</DeepLink>)}
              </div>
            )}
          </Section>
        )}
        <Section title="See it in the app">
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {n.where.map((w) => (
              <SecondaryBtn key={w.label} onClick={() => { onClose(); go(w.page, w.opts); }}>{w.label} <Icon name="arrow-right" size={14} /></SecondaryBtn>
            ))}
          </div>
        </Section>
        {linked.length > 0 && (
          <Section title={n.kind === "asset" ? "Databricks features it uses" : "Deployed assets that use it"}>
            <Stack gap="var(--space-2)">
              {linked.map((x) => <NodeLink key={x.id} n={x} onClick={() => onSelect(`${x.kind}:${x.id}`)} />)}
            </Stack>
          </Section>
        )}
        {n.code && n.code.length > 0 && (
          <Section title="Defined in the repository">
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>{n.code.map((c) => <Mono key={c}>{c}</Mono>)}</div>
          </Section>
        )}
      </Stack>
    </Drawer>
  );
}

function NodeLink({ n, onClick }: { n: MapNode; onClick: () => void }) {
  return (
    <button onClick={onClick} style={{ display: "flex", alignItems: "center", gap: 10, background: "var(--bg-canvas)", border: "1px solid var(--border)",
                                       borderRadius: "var(--radius-sm)", padding: "8px 10px", cursor: "pointer", textAlign: "left", fontFamily: "var(--font-sans)" }}>
      <span style={{ fontSize: "var(--fs-body-sm)", fontWeight: 600, color: "var(--fg-1)" }}>{n.label}</span>
      <span style={{ fontSize: "var(--fs-caption)", color: "var(--fg-2)", flex: 1 }}>{n.sub}</span>
      <Icon name="chev_r" size={14} color="var(--fg-3)" />
    </button>
  );
}

// ── Audit workflow tab ──────────────────────────────────────────────────────
function WorkflowTab({ go }: { go: (p: PageId, o?: NavOpts) => void }) {
  return (
    <Stack>
      <Notice kind="info">{PARITY_NOTE}</Notice>
      <Section title="Where the work runs" eyebrow="Audit workflow on the data platform">
        <DataTable<Row>
          rows={WHERE_IT_RUNS as unknown as Row[]}
          rowKey={(r) => String(r.label)}
          columns={[
            { key: "label", label: "Aspect", width: 140, render: (r) => <b>{r.label}</b> },
            { key: "grc", label: GRC_LABEL },
            { key: "databricks", label: "This demo on Databricks" },
          ]}
        />
      </Section>
      <Section title="Step by step" eyebrow={`Each step against ${GRC_LABEL}`}>
        <DataTable<ParityStep & Row>
          rows={PARITY as (ParityStep & Row)[]}
          rowKey={(r) => r.id}
          columns={[
            { key: "step", label: "Step", width: 130, render: (r) => <b>{r.step}</b> },
            { key: "grc", label: `Typically in ${GRC_LABEL}`, width: "26%", render: (r) => <span style={{ color: "var(--fg-2)", lineHeight: 1.5 }}>{r.grc}</span> },
            { key: "databricks", label: "In this demo on Databricks", width: "34%", render: (r) => <span style={{ lineHeight: 1.5 }}>{r.databricks}</span> },
            { key: "assets", label: "Assets", render: (r) => (
              <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                {r.assets.map((x) => <Mono key={x}>{x}</Mono>)}
                <span style={{ ...monoCaption, fontSize: 10, marginTop: 2 }}>{r.data}</span>
              </div>) },
            { key: "page", label: "Live", width: 150, render: (r) => (
              <button onClick={() => go(r.page, r.opts)} style={{ background: "none", border: "none", padding: 0, cursor: "pointer", color: "var(--fg-link)",
                                                                   fontSize: "var(--fs-body-sm)", display: "inline-flex", alignItems: "center", gap: 4, textAlign: "left" }}>
                {r.pageLabel} <Icon name="arrow-right" size={12} />
              </button>) },
          ]}
        />
      </Section>
    </Stack>
  );
}

// ── Briefing coverage tab ───────────────────────────────────────────────────
const COVERAGE_TONE: Record<string, string> = { planned: "NOT_RUN", built: "RESOLVED", verified: "PASS", "talk track": "INFO" };

function CoverageTab({ go }: { go: (p: PageId, o?: NavOpts) => void }) {
  const [tier, setTier] = useState("ALL");
  const [status, setStatus] = useState("ALL");
  const tiers = ["T1", "T2", "T3", "D"];
  const match = (r: CoverageRow) =>
    (tier === "ALL" || (tier === "none" ? !r.tier || r.tier === "n/a" : r.tier.split("/").includes(tier))) &&
    (status === "ALL" || r.status === status);
  const shown = COVERAGE.filter(match);
  const total = COVERAGE.length;
  const by = (s: string) => COVERAGE.filter((r) => r.status === s).length;
  const verified = by("verified");

  return (
    <Stack>
      <Notice kind="info">
        The acceptance checklist for this workshop: every item in the briefing from an Internal Audit, Risk and SOX team, the demo moment
        that answers it, the Databricks feature, and a feasibility tier. The demo is complete when every row is verified in a dry run
        of the run-of-show. Rows and statuses are defined in <Mono>frontend/src/architecture/coverage.ts</Mono>.
      </Notice>
      <Grid cols={4}>
        <SummaryTile label="Briefing items" value={fmtInt(total)} sub={`${COVERAGE_AREAS.length} areas`} />
        <SummaryTile label="Verified in a dry run" value={fmtInt(verified)} sub={`${Math.round((100 * verified) / total)}% of rows`} />
        <SummaryTile label="Built" value={fmtInt(by("built"))} sub="works in the deployed demo" />
        <SummaryTile label="Planned" value={fmtInt(by("planned"))} sub="designed, not yet built" />
        <SummaryTile label="Talk track" value={fmtInt(by("talk track"))} sub="intentionally not built; discussed" />
      </Grid>
      <Section title="Progress by area">
        <div style={{ display: "grid", gridTemplateColumns: "minmax(220px, max-content) 1fr 120px", gap: "8px 14px", alignItems: "center" }}>
          {COVERAGE_AREAS.map((a) => {
            const rs = COVERAGE.filter((r) => r.area === a.id);
            const v = rs.filter((r) => r.status === "verified").length;
            const b = rs.filter((r) => r.status === "built").length;
            return (
              <React.Fragment key={a.id}>
                <span style={{ fontSize: "var(--fs-body-sm)" }}><Mono dim>{a.id}</Mono> {a.label}</span>
                <div style={{ height: 10, background: "var(--bg-subtle)", borderRadius: 5, overflow: "hidden", display: "flex", border: "1px solid var(--border)" }}>
                  <div style={{ width: `${(100 * v) / rs.length}%`, background: "var(--success)" }} />
                  <div style={{ width: `${(100 * b) / rs.length}%`, background: "var(--info)" }} />
                </div>
                <Mono dim style={{ textAlign: "right" }}>{v}/{rs.length} verified</Mono>
              </React.Fragment>
            );
          })}
        </div>
      </Section>
      <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap" }}>
        <Select label="Tier" value={tier} onChange={setTier}
                options={[{ value: "ALL", label: "All tiers" }, ...tiers.map((t) => ({ value: t, label: `${t}: ${TIER_DESC[t].split(":")[0]}` })), { value: "none", label: "No tier" }]} />
        <Select label="Status" value={status} onChange={setStatus}
                options={[{ value: "ALL", label: "All statuses" }, { value: "planned", label: "Planned" }, { value: "built", label: "Built" }, { value: "verified", label: "Verified" }, { value: "talk track", label: "Talk track" }]} />
        <span style={monoCaption}>{shown.length} of {total} rows</span>
      </div>
      {COVERAGE_AREAS.map((a) => {
        const rs = shown.filter((r) => r.area === a.id);
        if (!rs.length) return null;
        const hasFeature = rs.some((r) => r.feature);
        const hasTier = rs.some((r) => r.tier);
        return (
          <Section key={a.id} eyebrow={`Area ${a.id}`} title={a.label}>
            <DataTable<CoverageRow & Row>
              rows={rs as (CoverageRow & Row)[]}
              rowKey={(r) => r.id}
              columns={[
                { key: "id", label: "#", width: 44, mono: true },
                { key: "item", label: "Briefing item", width: "24%" },
                { key: "moment", label: "Demo moment", render: (r) => (
                  <div style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-start" }}>
                    <span style={{ lineHeight: 1.45 }}>{r.moment}</span>
                    <button onClick={() => go(r.page, r.tab ? { tab: r.tab } : undefined)}
                            style={{ background: "none", border: "none", padding: 0, cursor: "pointer", color: "var(--fg-link)", fontSize: "var(--fs-caption)",
                                     display: "inline-flex", alignItems: "center", gap: 4, fontFamily: "var(--font-mono)" }}>
                      {PAGE_LABEL[r.page]}{r.tab && r.page !== "architecture" ? ` · ${r.tab}` : ""} <Icon name="arrow-right" size={11} />
                    </button>
                  </div>) },
                ...(hasFeature ? [{ key: "feature", label: "Databricks feature", width: "20%" }] : []),
                ...(hasTier ? [{ key: "tier", label: "Tier", width: 70, render: (r: CoverageRow & Row) => r.tier
                  ? <span title={r.tier.split("/").map((t) => TIER_DESC[t] ?? t).join("\n")}><Mono>{r.tier}</Mono></span> : <Mono dim>—</Mono> }] : []),
                { key: "status", label: "Status", width: 100, render: (r) => <StatusBadge status={COVERAGE_TONE[r.status]} label={r.status} small /> },
              ]}
            />
          </Section>
        );
      })}
      {!shown.length && <EmptyNote>No briefing rows match these filters.</EmptyNote>}
    </Stack>
  );
}

function SummaryTile({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div style={{ background: "var(--bg-canvas)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", padding: "var(--space-4) var(--space-5)" }}>
      <div style={{ ...monoCaption, textTransform: "uppercase", letterSpacing: "var(--tracking-eyebrow)" }}>{label}</div>
      <div style={{ fontSize: "var(--fs-h2)", fontWeight: 700, color: "var(--fg-1)", margin: "4px 0 2px" }}>{value}</div>
      <div style={monoCaption}>{sub}</div>
    </div>
  );
}

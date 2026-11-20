// Data Quality & Lineage: the pipeline observing itself. Every band, count and
// expectation below comes from meta_pipeline_update_metrics, which
// run_controls.record_results copies from the pipeline's published event log
// for the update that tested the controls. Nothing here is hard-coded.
import React, { useMemo, useState } from "react";
import type { PageProps } from "../App";
import {
  getExpectations, getFailingRecords, getFeeds, getLineageDatasets, getLineageTimeline, getSankey,
} from "../api";
import type {
  FailingRecords, LineageDatasets, LineageExpectations, LineageFeeds, LinkTemplates, Row, SankeyLink, SankeyNode, SankeyResponse,
} from "../types";
import {
  Async, CodeBlock, DataTable, DeepLink, Drawer, EmptyNote, ErrorNote, Grid, LoadingNote, Mono, Notice, Page, RowsTable,
  Section, Stack, StatusBadge, linkBtn, monoCaption, useApi, type Column,
} from "../components/ui";
import { PageHero } from "../components/layout/PageHero";
import { StatTile } from "../components/StatTile";
import { SegSelect, SecondaryBtn } from "../components/Buttons";
import { ChecklistSlice } from "../components/ChecklistSlice";
import { Sankey, SankeyLegend, STAGE_LABEL, compactRows, type SankeySelection } from "../charts/Sankey";
import { fmtInt } from "../format";
import { fmtTs, jobRunHref, shortId, tableHref, updateHref } from "../components/lineage/lineageUtil";

type Level = "domain" | "dataset";
type Sel =
  | { kind: "node"; node: SankeyNode }
  | { kind: "link"; link: SankeyLink }
  | { kind: "dataset"; name: string };

export function DataQualityLineage({ onNavigate, nav }: PageProps) {
  const [level, setLevel] = useState<Level>(nav.tab === "dataset" ? "dataset" : "domain");
  const sk = useApi(() => getSankey(level), [level]);
  const ds = useApi(() => getLineageDatasets(), []);
  const feeds = useApi(getFeeds, []);
  const exp = useApi(getExpectations, []);
  const tl = useApi(getLineageTimeline, []);
  const [sel, setSel] = useState<Sel | null>(nav.focusId ? { kind: "dataset", name: nav.focusId } : null);
  const [chartSel, setChartSel] = useState<SankeySelection | null>(null);

  const rescuedByTable = useMemo(() => {
    const m: Record<string, number> = {};
    for (const d of feeds.data?.drift ?? []) m[d.bronze_table] = (m[d.bronze_table] ?? 0) + Number(d.rows_rescued ?? 0);
    return m;
  }, [feeds.data]);

  const fresh = feeds.data ? feeds.data.feeds.filter((f) => f.within_sla).length : null;
  const totals = sk.data?.totals;
  // KPI placeholder: "…" while loading, "—" once the request has failed (the Sankey panel shows the error).
  const skPending = sk.error ? "—" : "…";
  const feedsPending = feeds.error ? "—" : "…";
  const pipelineId = (tl.data?.runs.find((r) => r.pipeline_id)?.pipeline_id as string | undefined) ?? null;
  const links = sk.data?.links_tpl ?? ds.data?.links ?? tl.data?.links;

  const closeDrawer = () => { setSel(null); setChartSel(null); };

  return (
    <Page>
      <PageHero
        eyebrow="Platform · Observability"
        title="Data Quality & Lineage"
        subtitle="Source systems through bronze, silver and gold to the control tests, drawn from the pipeline's own event log for the update that tested the controls. Band colors carry expectation results and schema drift; click any node or band for the datasets and failing rows behind it."
      />

      <div style={{ display: "flex", gap: "var(--space-4)", flexWrap: "wrap", marginBottom: "var(--space-6)" }}>
        <StatTile label="Datasets in update" value={totals ? fmtInt(totals.datasets) : skPending} sub="streaming tables and materialized views" />
        <StatTile label="Rows" value={totals ? compactRows(totals.rows) : skPending} sub="across all pipeline datasets" />
        <StatTile label="Expectation failures" value={totals ? fmtInt(totals.failed_records) : skPending} accent={totals?.failed_records ? "var(--db-yellow-600)" : undefined}
                  sub="rows flagged by WARN expectations (controls)" />
        <StatTile label="Schema drift rows" value={totals ? fmtInt(totals.rescued_rows) : skPending} accent={totals?.rescued_rows ? "var(--warning)" : undefined}
                  sub="fields outside the feed contract (rescued)" />
        <StatTile label="Feeds within SLA" value={feeds.data ? `${fresh}/${feeds.data.feeds.length}` : feedsPending}
                  accent={feeds.data && fresh !== feeds.data.feeds.length ? "var(--db-lava-600)" : undefined} sub="DQ-01 freshness" />
      </div>

      <Stack>
        <Section
          eyebrow="Lineage and data quality"
          title={sk.data ? <>Pipeline update <Mono style={{ fontSize: "var(--fs-body-sm)" }}>{shortId(sk.data.update_id, 13)}</Mono></> : "Pipeline update"}
          right={
            <>
              <SegSelect value={level} onChange={(v) => { setLevel(v as Level); setChartSel(null); }}
                         options={[{ label: "By domain", value: "domain" }, { label: "By dataset", value: "dataset" }]} />
            </>
          }
        >
          <Async state={sk} height={420} empty={(d) => d.nodes.length === 0}
                 emptyText="No pipeline update has been recorded yet. Run run_controls to record the update metrics.">
            {(d) => <SankeyBlock d={d} level={level} pipelineId={pipelineId} chartSel={chartSel}
                                 onSelect={(s, node, link) => {
                                   setChartSel(s);
                                   if (node) setSel({ kind: "node", node });
                                   else if (link) setSel({ kind: "link", link });
                                 }} />}
          </Async>
        </Section>

        <Grid cols="minmax(0, 3fr) minmax(0, 2fr)">
          <Section eyebrow="DQ-01" title="Feed freshness">
            <Async state={feeds} empty={(d) => d.feeds.length === 0} emptyText="No feeds recorded.">
              {(d) => <FeedsTable d={d} />}
            </Async>
          </Section>
          <Stack>
            <Section eyebrow="DQ-02" title="Schema drift by source file">
              <Async state={feeds}>
                {(d) => d.drift.length === 0 ? <EmptyNote>No rows outside the feed contracts in the current files.</EmptyNote> : (
                  <Stack gap="var(--space-2)">
                    {d.drift.map((x) => (
                      <button key={`${x.bronze_table}-${x.file_name}`} onClick={() => setSel({ kind: "dataset", name: x.bronze_table })}
                              style={{ textAlign: "left", background: "var(--warning-bg)", border: "1px solid var(--warning)", borderRadius: "var(--radius-md)",
                                       padding: "10px 12px", cursor: "pointer", fontFamily: "var(--font-sans)" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                          <Mono>{x.bronze_table}</Mono>
                          <Mono>{fmtInt(x.rows_rescued)} / {fmtInt(x.rows_total)} rows</Mono>
                        </div>
                        <div style={{ fontSize: "var(--fs-body-sm)", marginTop: 4 }}>
                          {x.file_name}: new field <Mono>{x.sample_rescued_field ?? "unknown"}</Mono> captured in rescued data, no rows dropped.
                        </div>
                      </button>
                    ))}
                  </Stack>
                )}
              </Async>
            </Section>
            <Section eyebrow="Checklist" title="Data-quality and monitoring-integrity controls">
              <ChecklistSlice module="DQ" onNavigate={onNavigate} title="DQ and PLT controls" compact />
            </Section>
          </Stack>
        </Grid>

        <Section eyebrow="Controls implemented as pipeline expectations" title="Expectation results by update"
                 right={<span style={monoCaption}>WARN expectations keep every row and flag it; the control test reads the flag</span>}>
          <Async state={exp} empty={(d) => d.rows.length === 0} emptyText="No expectation metrics recorded yet.">
            {(d) => <ExpectationsTable d={d} onNavigate={onNavigate} onDataset={(name) => setSel({ kind: "dataset", name })} />}
          </Async>
        </Section>

        <Section eyebrow="Audit trail of monitoring" title="Control runs and the pipeline updates they tested">
          <Async state={tl} empty={(d) => d.runs.length === 0} emptyText="No control runs recorded yet.">
            {(d) => <TimelineTable runs={d.runs} links={d.links} />}
          </Async>
        </Section>
      </Stack>

      <Drawer open={sel != null} onClose={closeDrawer} width={880}
              title={sel ? selTitle(sel) : ""}
              subtitle={sel ? selSubtitle(sel) : undefined}>
        {sel && (
          <LineagePanel sel={sel} datasets={ds} rescued={rescuedByTable} links={links} pipelineId={pipelineId}
                        onNavigate={onNavigate} onDataset={(name) => setSel({ kind: "dataset", name })} />
        )}
      </Drawer>
    </Page>
  );
}

// ── Sankey block ────────────────────────────────────────────────────────────
function SankeyBlock({ d, level, pipelineId, chartSel, onSelect }: {
  d: SankeyResponse; level: Level; pipelineId: string | null; chartSel: SankeySelection | null;
  onSelect: (s: SankeySelection, node?: SankeyNode, link?: SankeyLink) => void;
}) {
  const height = level === "dataset" ? Math.max(900, d.nodes.length * 14) : 620;
  const stagesPresent = d.stages.filter((s) => d.nodes.some((n) => n.stage === s));
  return (
    <Stack gap="var(--space-3)">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        <span style={monoCaption}>
          Flow: {stagesPresent.map((s) => STAGE_LABEL[s] ?? s).join(" → ")}
        </span>
        <span style={{ ...monoCaption, display: "inline-flex", gap: 12 }}>
          <DeepLink href={updateHref(d.links_tpl, d.update_id, pipelineId)}>pipeline update</DeepLink>
          {d.job_run_id && <span>recorded by run {d.job_run_id}</span>}
          <span>{fmtTs(d.recorded_at)} UTC</span>
        </span>
      </div>
      <div style={{ overflow: level === "dataset" ? "auto" : "visible", maxHeight: level === "dataset" ? 900 : undefined,
                    border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: "8px 4px", background: "var(--bg-canvas)" }}>
        <Sankey nodes={d.nodes} links={d.links} height={height} dense={level === "dataset"} minWidth={level === "dataset" ? 2000 : 640}
                selected={chartSel} onSelect={onSelect} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <SankeyLegend />
        <span style={monoCaption}>
          Band width is the square root of rows read, so small control-test flows stay visible next to ledger tables. Hover for exact rows.
          {d.dropped_back_edges > 0 && ` ${d.dropped_back_edges} back reference${d.dropped_back_edges > 1 ? "s" : ""} folded at this grouping level.`}
        </span>
      </div>
    </Stack>
  );
}

function selTitle(s: Sel): React.ReactNode {
  if (s.kind === "node") return s.node.label;
  if (s.kind === "link") return <>{labelOf(s.link.source)} to {labelOf(s.link.target)}</>;
  return <Mono style={{ fontSize: "var(--fs-h4)" }}>{s.name}</Mono>;
}
function selSubtitle(s: Sel): React.ReactNode {
  if (s.kind === "node") return `${STAGE_LABEL[s.node.stage] ?? s.node.stage} · ${fmtInt(s.node.rows)} rows${s.node.datasets.length > 1 ? ` in ${s.node.datasets.length} datasets` : ""}`;
  if (s.kind === "link") return `${fmtInt(s.link.rows)} rows read across this band`;
  return "Pipeline dataset";
}
function labelOf(id: string): string {
  const [, rest] = id.includes(":") ? id.split(/:(.*)/s) : ["", id];
  return rest || id;
}

// ── Drawer: datasets behind a node, band or dataset ─────────────────────────
function LineagePanel({ sel, datasets, rescued, links, pipelineId, onNavigate, onDataset }: {
  sel: Sel; datasets: ReturnType<typeof useApi<LineageDatasets>>; rescued: Record<string, number>; links: LinkTemplates | undefined;
  pipelineId: string | null; onNavigate: PageProps["onNavigate"]; onDataset: (name: string) => void;
}) {
  const [rec, setRec] = useState<{ dataset: string; expectation?: string } | null>(null);
  const names: string[] =
    sel.kind === "dataset" ? [sel.name]
      : sel.kind === "link" ? sel.link.datasets
        : sel.node.datasets;

  if (sel.kind === "node" && sel.node.stage === "exceptions") {
    const module = sel.node.id.split(":")[1];
    return (
      <Stack>
        <Notice kind={sel.node.status === "fail" ? "danger" : "info"}>
          {fmtInt(sel.node.rows)} exceptions from the {module} control tests in this update{sel.node.open != null ? `, ${fmtInt(sel.node.open)} still open` : ""}.
          Review, evidence and four-eyes dispositions happen in the exceptions queue.
        </Notice>
        <div><SecondaryBtn onClick={() => onNavigate("exceptions", { filter: { module } })}>Open the {module} exceptions queue</SecondaryBtn></div>
      </Stack>
    );
  }
  if (sel.kind === "node" && sel.node.stage === "source") {
    const label = sel.node.label;
    const note = label.startsWith("Control library")
      ? "Versioned control definitions, risk register and close calendar (YAML in Git), published by run_controls.publish_controls into meta_ tables that the pipeline reads. Control thresholds reach the tests as data, not as code edits."
      : label.startsWith("Lakebase")
        ? "Human review actions from Audit Workbench (dispositions, sign-offs, variance explanations), copied one way into meta_review_actions by run_controls.snapshot_review_state at the start of every control run."
        : `${label} lands raw files in the Unity Catalog volume; the pipeline ingests them into bronze streaming tables with read_files (${fmtInt(sel.node.rows)} rows in the bronze tables it feeds).`;
    return (
      <Stack>
        <Notice kind="info">{note}</Notice>
        <span style={monoCaption}>Click a band to the right of this source for the datasets it feeds.</span>
      </Stack>
    );
  }

  return (
    <Stack>
      {sel.kind === "link" && (
        <Notice kind={sel.link.status === "ok" ? "info" : "warning"}>
          Datasets in <b>{labelOf(sel.link.target)}</b> that read from <b>{labelOf(sel.link.source)}</b> in this update.
        </Notice>
      )}
      <Async state={datasets} empty={() => names.length === 0} emptyText="No pipeline datasets behind this selection.">
        {(d) => {
          const by = new Map(d.rows.map((r) => [r.dataset as string, r]));
          const rows = names.map((n) => by.get(n) ?? { dataset: n, status: "NOT_IN_UPDATE" });
          const cols: Column<Row>[] = [
            { key: "dataset", label: "Dataset", render: (r) => (
              <button onClick={() => onDataset(r.dataset)} style={{ ...linkBtn, fontFamily: "var(--font-mono)", fontSize: "var(--fs-caption)", textAlign: "left" }}>{r.dataset}</button>
            ) },
            { key: "layer", label: "Layer", mono: true, render: (r) => `${r.domain ?? ""}/${r.layer ?? ""}` },
            { key: "rows_in_table", label: "Rows", align: "right", render: (r) => fmtInt(r.rows_in_table) },
            { key: "rows_written", label: "Written", align: "right", render: (r) => fmtInt(r.rows_written) },
            { key: "duration_s", label: "Secs", align: "right", render: (r) => (r.duration_s == null ? "—" : Number(r.duration_s).toFixed(1)) },
            { key: "expectations", label: "Expectations", render: (r) => <ExpChips exps={r.expectations} /> },
            { key: "status", label: "Status", render: (r) => <StatusBadge status={r.status === "COMPLETED" ? "ok" : r.status} label={r.status === "COMPLETED" ? "completed" : String(r.status).toLowerCase()} small /> },
            { key: "uc", label: "", render: (r) => <DeepLink href={tableHref(links, r.dataset)} title="Open in Catalog Explorer">UC</DeepLink> },
          ];
          return (
            <Stack>
              <DataTable columns={cols} rows={rows} rowKey={(r) => r.dataset} dense maxHeight={340} />
              <RecordActions rows={rows} rescued={rescued} onPick={setRec} active={rec} />
              {rows.length === 1 && rows[0].source_file && (
                <div style={monoCaption}>Defined in <Mono>{rows[0].source_file}</Mono> · update <DeepLink href={updateHref(links, rows[0].update_id, pipelineId)}>{shortId(rows[0].update_id)}</DeepLink>
                  {rows[0].input_datasets?.length ? <> · reads {(rows[0].input_datasets as string[]).map((x) => (
                    <button key={x} onClick={() => onDataset(x)} style={{ ...linkBtn, fontFamily: "var(--font-mono)", fontSize: "var(--fs-caption)", marginLeft: 6 }}>{x}</button>
                  ))}</> : null}
                </div>
              )}
            </Stack>
          );
        }}
      </Async>
      {rec && <FailingRecordsView key={`${rec.dataset}|${rec.expectation ?? ""}`} dataset={rec.dataset} expectation={rec.expectation} />}
    </Stack>
  );
}

function ExpChips({ exps }: { exps: { name: string; passed: number; failed: number }[] | null | undefined }) {
  if (!exps || !exps.length) return <span style={{ color: "var(--fg-3)" }}>—</span>;
  return (
    <span style={{ display: "inline-flex", gap: 4, flexWrap: "wrap" }}>
      {exps.map((e) => (
        <span key={e.name} title={`${fmtInt(e.passed)} passed, ${fmtInt(e.failed)} failed`}
              style={{ fontFamily: "var(--font-mono)", fontSize: 10, padding: "1px 6px", borderRadius: "var(--radius-pill)",
                       border: `1px solid ${e.failed > 0 ? "var(--db-yellow-600)" : "var(--border-strong)"}`,
                       background: e.failed > 0 ? "var(--warning-bg)" : "var(--bg-subtle)" }}>
          {e.name} {e.failed > 0 ? `${fmtInt(e.failed)} failed` : "pass"}
        </span>
      ))}
    </span>
  );
}

function RecordActions({ rows, rescued, onPick, active }: {
  rows: Row[]; rescued: Record<string, number>; onPick: (r: { dataset: string; expectation?: string }) => void;
  active: { dataset: string; expectation?: string } | null;
}) {
  const actions: { key: string; label: string; dataset: string; expectation?: string; tone: "warn" | "drift" | "plain" }[] = [];
  for (const r of rows) {
    for (const e of (r.expectations ?? []) as { name: string; failed: number }[]) {
      if (e.failed > 0) actions.push({ key: `${r.dataset}|${e.name}`, label: `Failing rows: ${e.name} (${fmtInt(e.failed)})`, dataset: r.dataset, expectation: e.name, tone: "warn" });
    }
    if (rescued[r.dataset]) actions.push({ key: `${r.dataset}|rescued`, label: `Rescued rows: ${r.dataset} (${fmtInt(rescued[r.dataset])})`, dataset: r.dataset, tone: "drift" });
    if (String(r.dataset).endsWith("_exceptions")) actions.push({ key: `${r.dataset}|exc`, label: `Exception rows: ${r.dataset}`, dataset: r.dataset, tone: "plain" });
  }
  if (rows.length === 1 && !actions.length) actions.push({ key: `${rows[0].dataset}|sample`, label: "Sample rows", dataset: rows[0].dataset, tone: "plain" });
  if (!actions.length) return <span style={monoCaption}>No failing expectations or rescued data in these datasets. Open a dataset for sample rows.</span>;
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
      {actions.slice(0, 12).map((a) => {
        const on = active?.dataset === a.dataset && (active?.expectation ?? "") === (a.expectation ?? "");
        return (
          <button key={a.key} onClick={() => onPick({ dataset: a.dataset, expectation: a.expectation })}
                  style={{ fontFamily: "var(--font-mono)", fontSize: "var(--fs-caption)", padding: "5px 10px", cursor: "pointer",
                           borderRadius: "var(--radius-sm)", color: "var(--fg-1)",
                           border: `1px solid ${a.tone === "warn" ? "var(--db-yellow-600)" : a.tone === "drift" ? "var(--warning)" : "var(--border-strong)"}`,
                           background: on ? "var(--bg-subtle)" : a.tone === "plain" ? "var(--bg-canvas)" : "var(--warning-bg)",
                           boxShadow: on ? "inset 0 -2px 0 var(--db-lava-600)" : undefined }}>
            {a.label}
          </button>
        );
      })}
    </div>
  );
}

function FailingRecordsView({ dataset, expectation }: { dataset: string; expectation?: string }) {
  const st = useApi<FailingRecords>(() => getFailingRecords(dataset, expectation), [dataset, expectation]);
  if (st.error) return <ErrorNote message={st.error} onRetry={st.reload} />;
  if (!st.data) return <LoadingNote text="querying the dataset as you…" />;
  const d = st.data;
  const keys = d.rows[0] ? Object.keys(d.rows[0]).filter((k) => k !== "_rescued_data").slice(0, 14) : undefined;
  return (
    <Stack gap="var(--space-3)">
      <CodeBlock code={d.sql} label="SQL run on the SQL warehouse (your permissions)" maxHeight={120} />
      {d.note && <span style={monoCaption}>{d.note}</span>}
      <span style={monoCaption}>{fmtInt(d.rows.length)} row{d.rows.length === 1 ? "" : "s"}{d.rows.length >= 100 ? " (first 100)" : ""}</span>
      {d.rows.length > 0 && d.rows[0]._rescued_data !== undefined && (
        <RowsTable rows={d.rows.slice(0, 20).map((r) => ({ _source_file: r._source_file, _rescued_data: r._rescued_data }))} maxHeight={200} />
      )}
      <RowsTable rows={d.rows} keys={keys} maxHeight={380} empty="No rows match." />
    </Stack>
  );
}

// ── Feeds ──────────────────────────────────────────────────────────────────
function FeedsTable({ d }: { d: LineageFeeds }) {
  const cols: Column<Row>[] = [
    { key: "feed", label: "Feed", render: (r) => (
      <div><Mono>{String(r.feed).replace(/^[a-z]+:/, "")}</Mono><div style={{ fontSize: "var(--fs-caption)", color: "var(--fg-2)" }}>{r.source_system}</div></div>) },
    { key: "entity_code", label: "Entity", mono: true },
    { key: "latest_date", label: "Latest", render: (r) => <Mono style={{ whiteSpace: "nowrap" }}>{r.latest_date ?? "—"}</Mono> },
    { key: "behind", label: "Behind / SLA", align: "right",
      render: (r) => `${fmtInt(r.behind)} / ${fmtInt(r.sla)} ${r.sla_unit === "bd" ? "bd" : "days"}` },
    { key: "within_sla", label: "Status", render: (r) => <StatusBadge status={r.within_sla ? "ok" : "fail"} label={r.within_sla ? "within SLA" : "behind SLA"} small /> },
  ];
  return (
    <Stack gap="var(--space-2)">
      <DataTable columns={cols} rows={d.feeds} rowKey={(r) => r.feed} dense maxHeight={420} />
      <span style={monoCaption}>Business days behind yesterday's data cutoff (calendar days for payroll). Stale feeds raise DQ-01 exceptions.</span>
    </Stack>
  );
}

// ── Expectations ────────────────────────────────────────────────────────────
function ExpectationsTable({ d, onNavigate, onDataset }: { d: LineageExpectations; onNavigate: PageProps["onNavigate"]; onDataset: (n: string) => void }) {
  const updates = Array.from(new Map(d.rows.map((r) => [r.update_id as string, String(r.recorded_at)])).entries())
    .sort((a, b) => a[1].localeCompare(b[1])).slice(-8).map(([u]) => u);
  const byName = new Map<string, Row[]>();
  for (const r of d.rows) byName.set(r.name, [...(byName.get(r.name) ?? []), r]);
  const rows = Array.from(byName.entries()).map(([name, rs]) => {
    const byUpd = new Map(rs.map((r) => [r.update_id as string, r]));
    const latest = byUpd.get(updates[updates.length - 1]) ?? rs[0];
    return { name, control_id: latest.control_id, control_title: latest.control_title, dataset: latest.dataset,
             passed: latest.passed, failed: latest.failed, trend: updates.map((u) => byUpd.get(u)?.failed ?? null) };
  }).sort((a, b) => (b.failed ?? 0) - (a.failed ?? 0) || a.name.localeCompare(b.name));
  const cols: Column<Row>[] = [
    { key: "name", label: "Expectation", mono: true },
    { key: "control_id", label: "Implements", render: (r) => r.control_id ? (
      <button onClick={() => onNavigate("checklist", { focusId: r.control_id })} style={{ ...linkBtn, textAlign: "left" }}>
        <Mono>{r.control_id}</Mono> <span style={{ color: "var(--fg-2)" }}>{r.control_title}</span>
      </button>) : "—" },
    { key: "dataset", label: "Dataset", render: (r) => (
      <button onClick={() => onDataset(r.dataset)} style={{ ...linkBtn, fontFamily: "var(--font-mono)", fontSize: "var(--fs-caption)" }}>{r.dataset}</button>) },
    { key: "passed", label: "Passed", align: "right", render: (r) => fmtInt(r.passed) },
    { key: "failed", label: "Failed", align: "right", render: (r) => <span style={{ color: r.failed > 0 ? "var(--warning)" : undefined, fontWeight: r.failed > 0 ? 700 : 400 }}>{fmtInt(r.failed)}</span> },
    { key: "trend", label: `Failed, last ${updates.length} update${updates.length === 1 ? "" : "s"}`, render: (r) => <LineageMiniBars values={r.trend} /> },
  ];
  return <DataTable columns={cols} rows={rows} rowKey={(r) => r.name} dense />;
}

/** Tiny bar trend of failed records per update (oldest to newest). */
function LineageMiniBars({ values }: { values: (number | null)[] }) {
  const max = Math.max(1, ...values.map((v) => v ?? 0));
  const w = 10, gap = 3, h = 22;
  return (
    <svg width={values.length * (w + gap)} height={h} aria-label="failed records per update">
      {values.map((v, i) => {
        const bh = v == null ? 2 : Math.max(2, (v / max) * (h - 2));
        return <rect key={i} x={i * (w + gap)} y={h - bh} width={w} height={bh} rx={1.5}
                     fill={v == null ? "var(--border)" : v > 0 ? "var(--db-yellow-600)" : "var(--db-navy-300)"}>
          <title>{v == null ? "not in this update" : `${v} failed`}</title>
        </rect>;
      })}
    </svg>
  );
}

// ── Run timeline ────────────────────────────────────────────────────────────
const RUN_TONE: Record<string, string> = { SUCCEEDED: "SUCCESS", SUCCESS: "SUCCESS", FAILED: "FAILED", RUNNING: "RUNNING" };

function TimelineTable({ runs, links }: { runs: Row[]; links: LinkTemplates }) {
  const cols: Column<Row>[] = [
    { key: "started_at", label: "Started (UTC)", render: (r) => <Mono style={{ whiteSpace: "nowrap" }}>{fmtTs(r.started_at)}</Mono> },
    { key: "trigger_source", label: "Trigger", render: (r) => (
      <span><Mono>{r.trigger_source ?? r.trigger_type ?? "—"}</Mono>{r.requested_by && <div style={{ ...monoCaption, fontSize: 10 }}>{r.requested_by}</div>}</span>) },
    { key: "status", label: "Run", render: (r) => <StatusBadge status={RUN_TONE[r.status] ?? r.status} label={String(r.status ?? "—").toLowerCase()} small /> },
    { key: "gate_result", label: "Gate", render: (r) => r.gate_result ? <StatusBadge status={r.gate_result} small /> : <Mono dim>pending</Mono> },
    { key: "controls", label: "Failing", align: "right", render: (r) => r.controls_executed == null ? "—" : `${fmtInt(r.controls_failed)} / ${fmtInt(r.controls_executed)}` },
    { key: "changes", label: "Exceptions vs prior run", render: (r) => <ChangeChips c={r.exception_changes ?? {}} /> },
    { key: "rows_written", label: "Rows written", align: "right", render: (r) => r.datasets == null ? "—" : `${compactRows(Number(r.rows_written ?? 0))} / ${fmtInt(r.datasets)} ds` },
    { key: "links", label: "Job run · update", render: (r) => (
      <span style={{ display: "inline-flex", gap: 10, whiteSpace: "nowrap", fontFamily: "var(--font-mono)", fontSize: "var(--fs-caption)" }}>
        <DeepLink href={jobRunHref(links, r.job_id, r.job_run_id)} title={`job run ${r.job_run_id}`}>{shortId(String(r.job_run_id), 6)}…</DeepLink>
        <DeepLink href={updateHref(links, r.test_update_id, r.pipeline_id)} title={`pipeline update ${r.test_update_id ?? ""}`}>{shortId(r.test_update_id)}</DeepLink>
      </span>) },
  ];
  return <DataTable columns={cols} rows={runs} rowKey={(r) => String(r.job_run_id)} dense maxHeight={460} />;
}

function ChangeChips({ c }: { c: Record<string, number> }) {
  const order = ["NEW", "RECURRING", "RESOLVED", "BASELINE"];
  const keys = order.filter((k) => c[k]);
  if (!keys.length) return <Mono dim>—</Mono>;
  return (
    <span style={{ display: "inline-flex", gap: 4, flexWrap: "wrap" }}>
      {keys.map((k) => <StatusBadge key={k} status={k === "RESOLVED" ? "PASS" : k} label={`${k.toLowerCase()} ${c[k]}`} small />)}
    </span>
  );
}

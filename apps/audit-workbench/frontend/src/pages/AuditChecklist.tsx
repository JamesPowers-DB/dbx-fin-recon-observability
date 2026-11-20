// Audit Checklist: every control in the published library, bound to what
// executed it (expectation, pipeline dataset or job task) and to the run that
// recorded its result. Status is the ledger's result for the latest run; a
// sign-off attests one run and is marked superseded when a newer run exists.
import React, { useEffect, useState } from "react";
import type { PageProps } from "../App";
import { getControlDetail, signoffControl } from "../api";
import type { ChecklistResponse, ChecklistRow, ControlDetail, LinkTemplates } from "../types";
import { PageHero } from "../components/layout/PageHero";
import { RunStepper } from "../components/RunStepper";
import { loadChecklist, invalidateChecklist } from "../components/ChecklistSlice";
import { PrimaryBtn, SecondaryBtn } from "../components/Buttons";
import { Icon } from "../components/Icon";
import { RunSparkline } from "../charts/RunSparkline";
import {
  Async, CodeBlock, DataTable, DeepLink, Drawer, EmptyNote, Grid, KV, Mono, Notice, Page, RowsTable, Section, Select, Stack,
  StatusBadge, Tabs, activePeriod, eyebrowStyle, fillLink, monoCaption, periodOptions, runLinks, useApi,
} from "../components/ui";
import { fmtInt, fmtUSD } from "../format";

const MODULES: { id: string; label: string }[] = [
  { id: "ALL", label: "All modules" }, { id: "M1", label: "M1 Cash" }, { id: "M2", label: "M2 Subledger" },
  { id: "M3", label: "M3 Journals" }, { id: "M4", label: "M4 Access" }, { id: "M5", label: "M5 Statements & FP&A" },
  { id: "DQ", label: "Data quality" }, { id: "PLT", label: "Platform" },
];
const LANES = [
  { id: "management", title: "Management monitoring", sub: "First and second line: controls the process owners run and evidence every day." },
  { id: "assurance", title: "Independent assurance", sub: "Internal Audit's own tests over the same data, including the monitoring-integrity gate." },
];
const KIND_LABEL: Record<string, string> = { expectation: "EXP", pipeline_dataset: "DS", job_task: "JOB" };
const pct = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 100)}%`);
const ts = (v: string | null | undefined) => (v ? String(v).replace("T", " ").slice(0, 16) : "—");

export function AuditChecklist({ onNavigate, nav }: PageProps) {
  const [period, setPeriod] = useState(activePeriod());
  const [module, setModule] = useState(nav.filter?.module ?? "ALL");
  const [status, setStatus] = useState<string>("ALL");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(nav.focusId ?? null);
  const st = useApi(() => loadChecklist(period), [period]);

  const reload = () => { invalidateChecklist(); st.reload(); };

  return (
    <Page>
      <PageHero
        eyebrow={`Controls as code · ${period}`}
        title="Audit Checklist"
        subtitle="Each control is a versioned definition in Git, bound to the expectation, pipeline dataset or job task that executes it. Status is the ledger result of the latest control run. A sign-off attests one run."
        right={<Select value={period} onChange={setPeriod} options={periodOptions(activePeriod())} label="Period" />}
      />
      <Stack>
        <Async state={st} height={90}>{(d) => <RunBanner d={d} onComplete={reload} />}</Async>
        <Async state={st} height={300} empty={(d) => d.controls.length === 0}
               emptyText="The control library is not published yet. Run the setup job (publish_controls).">
          {(d) => (
            <>
              <Filters d={d} module={module} setModule={setModule} status={status} setStatus={setStatus} q={q} setQ={setQ} />
              {LANES.map((lane) => (
                <Lane key={lane.id} lane={lane} d={d} module={module} status={status} q={q} onOpen={setOpen} />
              ))}
            </>
          )}
        </Async>
      </Stack>
      <ControlDrawer controlId={open} period={period} links={st.data?.links} row={st.data?.controls.find((c) => c.control_id === open)}
                     latestRun={st.data?.run?.job_run_id ?? null} onClose={() => setOpen(null)} onNavigate={onNavigate} onSigned={reload} />
    </Page>
  );
}

function RunBanner({ d, onComplete }: { d: ChecklistResponse; onComplete: () => void }) {
  const r = d.run;
  const l = r ? runLinks(d.links, { job_id: r.job_id, job_run_id: r.job_run_id, test_update_id: r.test_update_id }) : null;
  return (
    <Section padding="var(--space-4) var(--space-5)">
      <Grid cols="minmax(0, 1.4fr) minmax(320px, 1fr)" gap="var(--space-5)">
        {r ? (
          <div style={{ display: "flex", gap: "var(--space-6)", flexWrap: "wrap", alignItems: "flex-start" }}>
            <Fig label="Latest control run" value={<DeepLink href={l?.run}>{String(r.job_run_id)}</DeepLink>} sub={`${ts(r.started_at)} UTC`} />
            <Fig label="Triggered by" value={r.trigger_source ?? "—"} sub={r.requested_by ?? ""} />
            <Fig label="Pipeline update" value={<DeepLink href={l?.update}>{(r.test_update_id ?? "—").slice(0, 8)}</DeepLink>} sub="tested the controls" />
            <Fig label="Library" value={<Mono>{(r.library_hash ?? "—").slice(0, 10)}</Mono>} sub={`${fmtInt(r.controls_executed)} controls executed`} />
            <Fig label="Integrity gate" value={<StatusBadge status={r.gate_result ?? "NOT_RUN"} label={`PLT-01 ${r.gate_result ?? "not run"}`} />}
                 sub={r.planted_recall != null ? `recall ${Math.round(r.planted_recall * 100)}%` : ""} />
          </div>
        ) : <EmptyNote>No control run recorded yet.</EmptyNote>}
        <RunStepper onComplete={onComplete} />
      </Grid>
    </Section>
  );
}

function Fig({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return (
    <div>
      <div style={eyebrowStyle}>{label}</div>
      <div style={{ fontSize: "var(--fs-body)", fontWeight: 700 }}>{value}</div>
      {sub && <div style={monoCaption}>{sub}</div>}
    </div>
  );
}

function Filters({ d, module, setModule, status, setStatus, q, setQ }: {
  d: ChecklistResponse; module: string; setModule: (m: string) => void; status: string; setStatus: (s: string) => void; q: string; setQ: (s: string) => void;
}) {
  const order = ["FAIL", "STALE", "RESOLVED", "PASS", "INFO", "NOT_RUN", "NO_POPULATION"];
  return (
    <div style={{ display: "flex", gap: "var(--space-3)", alignItems: "center", flexWrap: "wrap" }}>
      <button onClick={() => setStatus("ALL")} style={chip(status === "ALL")}>All {d.controls.length}</button>
      {order.filter((s) => (d.summary[s] ?? 0) > 0).map((s) => (
        <button key={s} onClick={() => setStatus(status === s ? "ALL" : s)} style={chip(status === s)}>
          <StatusBadge status={s} small /> {d.summary[s]}
        </button>
      ))}
      <span style={{ flex: 1 }} />
      <Select value={module} onChange={setModule} options={MODULES.map((m) => ({ value: m.id, label: m.label }))} label="Module" />
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search control, title, owner"
             style={{ fontSize: "var(--fs-body-sm)", padding: "6px 10px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border-strong)",
                      background: "var(--bg-canvas)", width: 220 }} />
    </div>
  );
}

const chip = (on: boolean): React.CSSProperties => ({
  display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 10px", borderRadius: "var(--radius-pill)", cursor: "pointer",
  border: `1px solid ${on ? "var(--db-navy-800)" : "var(--border)"}`, background: on ? "var(--bg-subtle)" : "var(--bg-canvas)",
  fontFamily: "var(--font-mono)", fontSize: "var(--fs-caption)", color: "var(--fg-1)",
});

function bindingName(c: ChecklistRow): string {
  if (c.executed_by_kind === "expectation") return c.executed_by_expectation ?? "";
  if (c.executed_by_kind === "pipeline_dataset") return c.executed_by_dataset ?? "";
  return c.executed_by_task ?? "";
}

function Lane({ lane, d, module, status, q, onOpen }: {
  lane: { id: string; title: string; sub: string }; d: ChecklistResponse; module: string; status: string; q: string; onOpen: (id: string) => void;
}) {
  const ql = q.trim().toLowerCase();
  const rows = d.controls.filter((c) => c.lane === lane.id && (module === "ALL" || c.module === module) && (status === "ALL" || c.status === status)
    && (!ql || `${c.control_id} ${c.title} ${c.owner_role} ${c.module_name}`.toLowerCase().includes(ql)));
  const fails = rows.filter((r) => r.status === "FAIL").length;
  return (
    <Section eyebrow={`${lane.title} · ${rows.length} controls · ${fails} failing`} title={lane.sub}>
      <DataTable rowKey={(c) => c.control_id} rows={rows} onRowClick={(c) => onOpen(c.control_id)} empty="No controls match the filters."
        columns={[
          { key: "status", label: "Status", width: 110, render: (c) => (
            <div>
              <StatusBadge status={c.status} small />
              {c.failed_instances ? <div style={{ ...monoCaption, marginTop: 3 }}>{c.failed_instances}/{c.instances} entities</div> : null}
            </div>
          ) },
          { key: "control", label: "Control", render: (c) => (
            <div style={{ minWidth: 240 }}>
              <div><Mono>{c.control_id}</Mono> <Mono dim>v{c.version}</Mono>{c.key_control && <span style={{ marginLeft: 6, ...keyStyle }}>KEY</span>}</div>
              <div style={{ fontWeight: 600, marginTop: 2 }}>{c.title}</div>
              <div style={monoCaption}>{c.module_name} · {c.owner_role} · {c.frequency}</div>
            </div>
          ) },
          { key: "binding", label: "Executed by", render: (c) => (
            <div style={{ minWidth: 170 }}>
              <span style={kindStyle}>{KIND_LABEL[c.executed_by_kind] ?? c.executed_by_kind}</span>{" "}
              <Mono>{bindingName(c)}</Mono>
              {c.expectation && <div style={monoCaption}>{fmtInt(c.expectation.passed)} pass · {fmtInt(c.expectation.failed)} fail</div>}
            </div>
          ) },
          { key: "population", label: "Population", align: "right", render: (c) => (
            <div>{fmtInt(c.population)}{c.traditional_sample_size ? <div style={monoCaption}>sample was {c.traditional_sample_size}</div> : null}</div>
          ) },
          { key: "exceptions", label: "Exceptions", align: "right", render: (c) => (
            <div>{fmtInt(c.exceptions)}<div style={monoCaption}>{fmtInt(c.open_exceptions)} open</div></div>
          ) },
          { key: "amount", label: "Amount", align: "right", render: (c) => (c.amount_usd ? fmtUSD(c.amount_usd, true) : "—") },
          { key: "ai", label: "Triage / evidence", align: "right", render: (c) => (
            c.exceptions ? <div>{pct(c.triage_pct)}<div style={monoCaption}>{pct(c.evidence_pct)} evid.</div></div> : <span style={monoCaption}>—</span>
          ) },
          { key: "spark", label: "Runs", render: (c) => <RunSparkline points={c.sparkline} /> },
          { key: "run", label: "Last run", render: (c) => (
            <div style={{ whiteSpace: "nowrap" }}>
              <DeepLink href={runLinks(d.links, { job_id: c.job_id, job_run_id: c.task_run_id ?? c.job_run_id }).run}>
                <Mono>{c.job_run_id ? String(c.job_run_id).slice(-6) : "—"}</Mono>
              </DeepLink>
              <div style={monoCaption}>{ts(c.executed_at)}</div>
            </div>
          ) },
          { key: "tasks", label: "Close task", render: (c) => (
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              {c.close_tasks.map((t) => <Mono key={t.task_code} dim>{t.task_code}</Mono>)}
            </div>
          ) },
          { key: "signoff", label: "Sign-off", render: (c) => (
            c.signoff ? (
              <div style={monoCaption}>
                <div style={{ color: "var(--fg-1)" }}>{c.signoff.by.split("@")[0]}</div>
                {c.signoff.superseded ? <span style={{ color: "var(--warning)" }}>superseded by a newer run</span>
                  : c.signoff.pending_sync ? "applies next run" : ts(c.signoff.at)}
              </div>
            ) : <span style={monoCaption}>—</span>
          ) },
        ]} />
    </Section>
  );
}

const keyStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)", fontSize: 9, padding: "1px 5px", borderRadius: 3, background: "var(--db-navy-800)", color: "var(--fg-on-dark)",
};
const kindStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)", fontSize: 9, padding: "1px 5px", borderRadius: 3, border: "1px solid var(--db-navy-400)", color: "var(--db-navy-700)",
};

type DrawerTab = "definition" | "binding" | "results" | "code";

function ControlDrawer({ controlId, period, row, links, latestRun, onClose, onNavigate, onSigned }: {
  controlId: string | null; period: string; row?: ChecklistRow; links?: LinkTemplates; latestRun: number | null;
  onClose: () => void; onNavigate: PageProps["onNavigate"]; onSigned: () => void;
}) {
  const [tab, setTab] = useState<DrawerTab>("definition");
  const st = useApi(() => (controlId ? getControlDetail(controlId, period) : Promise.resolve(null)), [controlId, period]);
  const [msg, setMsg] = useState<{ kind: "success" | "danger"; text: string } | null>(null);
  useEffect(() => { setTab("definition"); setMsg(null); }, [controlId]);
  const sign = async () => {
    if (!controlId) return;
    try {
      const r = await signoffControl(controlId, period);
      setMsg({ kind: "success", text: r.note });
      onSigned();
    } catch (e) {
      setMsg({ kind: "danger", text: e instanceof Error ? e.message : String(e) });
    }
  };
  return (
    <Drawer open={!!controlId} onClose={onClose} width={900}
            title={<span><Mono style={{ fontSize: "var(--fs-h4)" }}>{controlId}</Mono> {row?.title ?? ""}</span>}
            subtitle={row ? `${row.module_name} · ${row.owner_role} · ${row.frequency} · version ${row.version}` : undefined}
            right={row && <StatusBadge status={row.status} />}>
      <Stack gap="var(--space-4)">
        {msg && <Notice kind={msg.kind} onClose={() => setMsg(null)}>{msg.text}</Notice>}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <PrimaryBtn onClick={sign}><Icon name="check" size={14} /> Sign off this control for {period}</PrimaryBtn>
          <SecondaryBtn onClick={() => onNavigate("exceptions", { filter: { control: controlId ?? "" } })}>
            <Icon name="warn" size={14} /> Open its exceptions
          </SecondaryBtn>
          {latestRun && <span style={{ ...monoCaption, alignSelf: "center" }}>A sign-off attests run {latestRun}.</span>}
        </div>
        <Tabs<DrawerTab> value={tab} onChange={setTab} tabs={[
          { id: "definition", label: "Definition" }, { id: "binding", label: "Binding and runs" },
          { id: "results", label: "Results" }, { id: "code", label: "Control as code" },
        ]} />
        <Async state={st} height={240}>
          {(d) => d && (tab === "definition" ? <Definition d={d} /> : tab === "binding" ? <Binding d={d} row={row} links={links} />
            : tab === "results" ? <Results d={d} /> : <Code d={d} links={links} />)}
        </Async>
      </Stack>
    </Drawer>
  );
}

function Definition({ d }: { d: ControlDetail }) {
  const c = d.control;
  const params = c.parameters && typeof c.parameters === "object" ? Object.entries(c.parameters as Record<string, string>) : [];
  return (
    <Stack gap="var(--space-4)">
      <Section title="Objective"><div style={{ fontSize: "var(--fs-body)", lineHeight: 1.55 }}>{c.objective}</div></Section>
      <Section title="Classification">
        <KV items={[
          ["Key control", c.key_control ? "yes" : "no"], ["Lane", c.lane], ["Nature", `${c.nature_type} · ${c.automation}`],
          ["Line of defense", c.line_of_defense], ["Assertions", (c.assertions ?? []).join(", ")], ["Frequency", c.frequency],
          ["Owner", c.owner_role], ["Sign-off", `${c.signoff_preparer_role ?? "—"} prepares, ${c.signoff_reviewer_role ?? "—"} reviews${c.four_eyes ? " (four-eyes)" : ""}`],
          ["Tolerance", c.max_exceptions == null ? "INFO (no tolerance)" : `${c.max_exceptions} exceptions${c.max_amount_usd != null ? `, ${fmtUSD(c.max_amount_usd)}` : ""}`],
          ["Population", `${c.population_description ?? ""} (${c.population_unit ?? ""})`],
        ]} />
      </Section>
      {params.length > 0 && (
        <Section title="Parameters"><KV items={params.map(([k, v]) => [k, String(v)] as [string, string])} /></Section>
      )}
      <Section title="Risks mitigated">
        {d.risks.length ? d.risks.map((r) => (
          <div key={r.risk_id} style={{ fontSize: "var(--fs-body-sm)", marginBottom: 4 }}><Mono>{r.risk_id}</Mono> {r.title} <Mono dim>{r.category}</Mono></div>
        )) : <span style={monoCaption}>Not linked in the risk register.</span>}
      </Section>
      {d.policy && (
        <Section title={`Policy ${d.policy.policy_ref}`}>
          <div style={{ fontSize: "var(--fs-body-sm)", lineHeight: 1.55, color: "var(--fg-2)", whiteSpace: "pre-wrap" }}>{d.policy.clause_text}</div>
          <div style={{ ...monoCaption, marginTop: 6 }}>Parsed from the policy PDF with ai_parse_document (silver_policy_section).</div>
        </Section>
      )}
    </Stack>
  );
}

function Binding({ d, row, links }: { d: ControlDetail; row?: ChecklistRow; links?: LinkTemplates }) {
  const c = d.control;
  const kind = c.executed_by_kind as string;
  const l = runLinks(links, { job_id: row?.job_id, job_run_id: row?.job_run_id, test_update_id: row?.test_update_id, dataset: c.exceptions_dataset ?? c.executed_by_dataset });
  const taskLink = fillLink(links?.job_run, { job_id: row?.job_id, run_id: row?.task_run_id });
  return (
    <Stack gap="var(--space-4)">
      <Section title="What executes this control">
        <KV items={[
          ["Kind", kind === "expectation" ? "Pipeline expectation (WARN, counted in the event log)" : kind === "pipeline_dataset" ? "Pipeline dataset (test SQL in the lakehouse pipeline)" : "Job task"],
          ["Job", c.executed_by_job], ["Task", c.executed_by_task], ["Dataset", c.executed_by_dataset],
          ["Expectation", c.executed_by_expectation], ["Exceptions dataset", c.exceptions_dataset], ["Test SQL", c.test_sql_file],
          ["Definition hash", <Mono key="h">{String(c.definition_hash ?? "").slice(0, 16)}</Mono>], ["Published", String(c.published_at ?? "").slice(0, 19)],
        ]} />
      </Section>
      <Section title="Latest execution">
        <div style={{ display: "flex", gap: "var(--space-5)", flexWrap: "wrap", fontSize: "var(--fs-body-sm)" }}>
          <DeepLink href={l.run}>Job run {row?.job_run_id ?? ""}</DeepLink>
          <DeepLink href={taskLink}>record_results task run</DeepLink>
          <DeepLink href={l.update}>Pipeline update {(row?.test_update_id ?? "").slice(0, 8)}</DeepLink>
          <DeepLink href={l.table}>Exceptions table in Unity Catalog</DeepLink>
        </div>
        {row?.expectation && (
          <div style={{ ...monoCaption, marginTop: 8 }}>
            Expectation {c.executed_by_expectation} on {row.expectation.dataset}: {fmtInt(row.expectation.passed)} records passed, {fmtInt(row.expectation.failed)} failed in this update.
          </div>
        )}
      </Section>
      <Section title="Run history (this period)">
        <DataTable rows={d.run_history} rowKey={(r) => String(r.job_run_id)} dense maxHeight={300} empty="No runs recorded for this period."
          columns={[
            { key: "job_run_id", label: "Run", mono: true, render: (r) => <DeepLink href={fillLink(links?.job_run, { job_id: r.job_id, run_id: r.job_run_id })}>{String(r.job_run_id)}</DeepLink> },
            { key: "started_at", label: "Started", mono: true, render: (r) => ts(r.started_at) },
            { key: "trigger_source", label: "Trigger" },
            { key: "requested_by", label: "Requested by" },
            { key: "result", label: "Result", render: (r) => <StatusBadge status={r.any_fail ? "FAIL" : "PASS"} small label={r.any_fail ? "FAIL" : "OK"} /> },
            { key: "exceptions", label: "Exceptions", align: "right" },
            { key: "test_update_id", label: "Update", mono: true, render: (r) => <DeepLink href={fillLink(links?.pipeline_update, { update_id: r.test_update_id })}>{String(r.test_update_id ?? "").slice(0, 8)}</DeepLink> },
          ]} />
      </Section>
    </Stack>
  );
}

function Results({ d }: { d: ControlDetail }) {
  return (
    <Stack gap="var(--space-4)">
      <Section title={`By entity · ${d.period} · latest run`}>
        <RowsTable rows={d.entities} empty="No results for this period." />
      </Section>
      <Section title="By period · latest run">
        <DataTable rows={d.periods} rowKey={(r) => String(r.period)} dense columns={[
          { key: "period", label: "Period", mono: true },
          { key: "result", label: "Result", render: (r) => <StatusBadge status={r.result} small /> },
          { key: "exceptions", label: "Exceptions", align: "right" },
        ]} />
      </Section>
    </Stack>
  );
}

function Code({ d, links }: { d: ControlDetail; links?: LinkTemplates }) {
  const src = d.control.source_file as string | undefined;
  return (
    <Stack gap="var(--space-4)">
      <div style={monoCaption}>
        The control definition and the test SQL as deployed with the bundle. Changing a definition without a version bump fails publish_controls.
      </div>
      {d.definition_yaml ? <CodeBlock code={d.definition_yaml} label={src ?? "definition"} maxHeight={360} />
        : <EmptyNote>Definition file not in the app's snapshot. Rebuild with apps/build_frontends.sh.</EmptyNote>}
      <div style={{ display: "flex", gap: 16 }}>
        {src && <DeepLink href={fillLink(links?.workspace_file, { path: src })}>Open definition in the workspace</DeepLink>}
        {d.test_sql_file && <DeepLink href={fillLink(links?.workspace_file, { path: d.test_sql_file })}>Open test SQL in the workspace</DeepLink>}
      </div>
      {d.test_sql ? <CodeBlock code={d.test_sql} label={d.test_sql_file ?? "test SQL"} maxHeight={480} />
        : <EmptyNote>Test SQL not in the app's snapshot.</EmptyNote>}
    </Stack>
  );
}

// Close Cockpit (home): days to close is the outcome, continuous close the
// north star. Every number is a governed measure or a recorded run; every task
// status comes from run_controls (controls green + sign-off), never set by hand.
import React, { useState } from "react";
import type { PageProps } from "../App";
import { getBurndown, getCloseSummary, getCloseTasks, getCloseTrend, signoffCloseTask } from "../api";
import type { CloseSummary, CloseTask, CloseTrendPoint } from "../types";
import { PageHero } from "../components/layout/PageHero";
import { StatTile } from "../components/StatTile";
import { RunStepper } from "../components/RunStepper";
import { SecondaryBtn } from "../components/Buttons";
import { Icon } from "../components/Icon";
import { METRICS } from "../components/metricDefinitions";
import { BurndownChart } from "../charts/BurndownChart";
import { DaysToCloseChart } from "../charts/DaysToCloseChart";
import {
  Async, DataTable, Grid, Mono, Notice, Page, Section, Stack, StatusBadge, eyebrowStyle, monoCaption, useApi, type ApiState,
} from "../components/ui";
import { fmtInt, fmtUSD } from "../format";

const tLabel = (t: number | null | undefined) => (t == null ? "—" : t === 0 ? "T" : t > 0 ? `T+${t}` : `T${t}`);
const pct = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 100)}%`);

export function CloseCockpit({ onNavigate }: PageProps) {
  const summary = useApi(getCloseSummary);
  const burndown = useApi(() => getBurndown());
  const trend = useApi(getCloseTrend);
  const tasks = useApi(() => getCloseTasks());
  const reloadAll = () => { summary.reload(); burndown.reload(); trend.reload(); tasks.reload(); };
  const s = summary.data;

  return (
    <Page>
      <PageHero
        eyebrow={`Continuous close · ${s?.active_period ?? "active period"}`}
        title="Close Cockpit"
        subtitle="Days to close is the outcome. A close task completes when its controls pass in a recorded control run and its sign-off exists. Nothing on this page is set by hand."
      />
      <Stack>
        <NorthStar summary={summary} trend={trend} />

        <Async state={summary} height={110}>
          {(d) => (
            <div style={{ display: "flex", gap: "var(--space-4)", flexWrap: "wrap" }}>
              <StatTile label="Days to close (last)" value={tLabel(d.days_to_close_last)} tooltip={METRICS.days_to_close}
                        sub={`${d.last_closed_period} · target ${tLabel(d.target_days_to_close)}`} accent="var(--db-navy-700)" />
              <StatTile label="Projected this close" value={tLabel(d.projected_days_to_close)} tooltip={METRICS.projected_days_to_close}
                        sub={`today is ${tLabel(d.today_close_day)}`} accent="var(--db-lava-600)" />
              <StatTile label="Done before month end" value={pct(d.pre_close_completion_pct)} tooltip={METRICS.pre_close}
                        sub={`${fmtInt(d.tasks_complete)} of ${fmtInt(d.tasks_total)} close tasks complete`} />
              <StatTile label="Control pass rate" value={pct(d.control_pass_rate)} tooltip={METRICS.control_pass_rate}
                        sub={`${fmtInt(d.key_controls_failed)} key controls failing`} />
              <StatTile label="Open exceptions" value={fmtInt(d.open_exceptions)} tooltip={METRICS.open_exceptions}
                        sub={`${fmtInt(d.critical_open_exceptions)} critical · ${pct(d.ai_triage_coverage_pct)} AI-triaged`} />
              <StatTile label="Unreconciled" value={fmtUSD(d.unreconciled_amount_usd, true)} tooltip={METRICS.unreconciled}
                        sub={`${fmtInt(d.records_tested)} records tested vs ${fmtInt(d.traditional_sample)} sampled`} />
            </div>
          )}
        </Async>

        <Async state={summary} height={70}>{(d) => <Lifecycle summary={d} onNavigate={onNavigate} />}</Async>

        <Grid cols="minmax(0, 2.2fr) minmax(300px, 1fr)" style={{ alignItems: "start" }}>
          <Section eyebrow={`Close burndown · ${burndown.data?.period ?? ""}`}
                   title={burndown.data ? `${burndown.data.remaining} of ${burndown.data.total} close tasks remaining` : "Close burndown"}
                   right={burndown.data && (
                     <StatusBadge status={burndown.data.on_track ? "PASS" : "FAIL"}
                                  label={burndown.data.on_track ? `On track for ${tLabel(burndown.data.projected_t)}` : `Projected ${tLabel(burndown.data.projected_t)}`} />
                   )}>
            <Async state={burndown} height={340}>
              {(b) => (
                <>
                  <BurndownChart points={b.points} total={b.total} todayT={b.today_t} targetT={b.target_t} projectedT={b.projected_t} />
                  <div style={{ ...monoCaption, marginTop: 8 }}>
                    Plan = close calendar due days. Traditional = average completion day per task in FY2025 (T+{b.traditional_t}).
                    Actual = completions recorded by control runs and sign-offs. Projection recomputed on every run.
                  </div>
                </>
              )}
            </Async>
          </Section>
          <Stack>
            <Section eyebrow="Controls" title="Run the controls">
              <RunStepper onComplete={reloadAll} />
              <Async state={summary} height={60}>{(d) => <LatestRun summary={d} />}</Async>
            </Section>
            <Async state={tasks} height={160}>{(t) => <GoNoGo tasks={t} onNavigate={onNavigate} />}</Async>
          </Stack>
        </Grid>

        <Section eyebrow="Close calendar" title="Close tasks"
                 right={<SecondaryBtn onClick={() => onNavigate("checklist")}><Icon name="check" size={14} /> Audit checklist</SecondaryBtn>}>
          <Async state={tasks} height={200} empty={(t) => t.length === 0}
                 emptyText="No close status yet. Run the controls to derive the active close from the control results.">
            {(t) => <TaskTable tasks={t} onNavigate={onNavigate} onSigned={reloadAll} />}
          </Async>
        </Section>
      </Stack>
    </Page>
  );
}

function NorthStar({ summary, trend }: { summary: ApiState<CloseSummary>; trend: ApiState<CloseTrendPoint[]> }) {
  const s = summary.data;
  const fig = (label: string, value: string, sub: string, color: string) => (
    <div style={{ minWidth: 96 }}>
      <div style={eyebrowStyle}>{label}</div>
      <div style={{ fontSize: 34, fontWeight: 700, letterSpacing: "var(--tracking-tight)", color, lineHeight: 1.05 }}>{value}</div>
      <div style={monoCaption}>{sub}</div>
    </div>
  );
  return (
    <Section padding="var(--space-5) var(--space-6)" style={{ borderTop: "4px solid var(--db-lava-600)" }}>
      <Grid cols="minmax(460px, 1fr) minmax(0, 1.5fr)" gap="var(--space-6)" style={{ alignItems: "center" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
          <div>
            <div style={eyebrowStyle}>North star: continuous close</div>
            <div style={{ fontSize: "var(--fs-h3)", fontWeight: 700, lineHeight: 1.25 }}>
              {s && s.days_to_close_traditional != null && s.days_to_close_last != null
                ? `From T+${s.days_to_close_traditional.toFixed(0)} to T+${s.days_to_close_last}, heading for T+${s.north_star_days_to_close}`
                : "Days to close"}
            </div>
          </div>
          <div style={{ display: "flex", gap: "var(--space-5)", flexWrap: "nowrap" }}>
            {fig("Traditional", s?.days_to_close_traditional != null ? `T+${s.days_to_close_traditional.toFixed(1)}` : "—", "FY2025 average", "var(--db-navy-400)")}
            {fig("Last close", tLabel(s?.days_to_close_last), s?.last_closed_period ?? "", "var(--db-navy-800)")}
            {fig("This close", tLabel(s?.projected_days_to_close), "projected", "var(--db-lava-600)")}
            {fig("North star", tLabel(s?.north_star_days_to_close ?? 1), "next", "var(--db-green-700)")}
          </div>
          <div style={{ fontSize: "var(--fs-body-sm)", color: "var(--fg-2)", lineHeight: 1.5 }}>
            Controls run on the full population every day, so reconciliations, journal testing and the access review finish
            before month end. What remains after month end is the work that needs the final ledger.
          </div>
        </div>
        <Async state={trend} height={220} empty={(t) => t.length === 0} emptyText="No close history yet.">
          {(t) => <DaysToCloseChart points={t} target={s?.target_days_to_close ?? 3} northStar={s?.north_star_days_to_close ?? 1}
                                    traditional={s?.days_to_close_traditional} />}
        </Async>
      </Grid>
    </Section>
  );
}

function Lifecycle({ summary, onNavigate }: { summary: CloseSummary; onNavigate: PageProps["onNavigate"] }) {
  return (
    <div style={{ display: "flex", alignItems: "stretch", gap: 0, background: "var(--bg-canvas)", border: "1px solid var(--border)",
                  borderRadius: "var(--radius-lg)", overflow: "hidden" }}>
      {summary.lifecycle.map((st, i) => (
        <button key={st.stage} onClick={() => onNavigate(st.page as Parameters<PageProps["onNavigate"]>[0])}
                style={{ flex: 1, padding: "12px 14px", border: "none", borderRight: i < summary.lifecycle.length - 1 ? "1px solid var(--border)" : "none",
                         background: "transparent", textAlign: "left", cursor: "pointer", position: "relative", fontFamily: "var(--font-sans)" }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-subtle)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}>
          <div style={{ ...eyebrowStyle, display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 16, height: 16, borderRadius: "50%", background: "var(--db-navy-800)", color: "var(--fg-on-dark)",
                           display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 9 }}>{i + 1}</span>
            {st.stage}
          </div>
          <div style={{ fontSize: "var(--fs-h3)", fontWeight: 700, color: "var(--fg-1)" }}>{st.value}</div>
          <div style={monoCaption}>{st.caption}</div>
        </button>
      ))}
    </div>
  );
}

function LatestRun({ summary }: { summary: CloseSummary }) {
  const r = summary.latest_run;
  if (!r) return <div style={{ ...monoCaption, marginTop: 10 }}>No control run recorded yet.</div>;
  return (
    <div style={{ marginTop: "var(--space-4)", paddingTop: "var(--space-3)", borderTop: "1px solid var(--border)",
                  display: "grid", gridTemplateColumns: "max-content 1fr", gap: "4px 12px", fontSize: "var(--fs-body-sm)" }}>
      <span style={monoCaption}>LAST RUN</span>
      <span><Mono>{String(r.job_run_id)}</Mono> <StatusBadge status={r.status ?? ""} small /></span>
      <span style={monoCaption}>STARTED</span><span>{String(r.started_at ?? "").replace("T", " ").slice(0, 16)} UTC</span>
      <span style={monoCaption}>TRIGGER</span><span>{r.trigger_source ?? "—"} · {r.requested_by ?? "—"}</span>
      <span style={monoCaption}>GATE PLT-01</span>
      <span><StatusBadge status={r.gate_result ?? "NOT_RUN"} small />{r.planted_recall != null && <Mono dim style={{ marginLeft: 6 }}>recall {Math.round(r.planted_recall * 100)}%</Mono>}</span>
      <span style={monoCaption}>EXCEPTIONS</span>
      <span>{fmtInt(r.exceptions_found)} found · {fmtInt(r.new_exceptions)} new · {fmtInt(r.resolved_exceptions)} resolved</span>
    </div>
  );
}

function blockers(t: CloseTask): string {
  if (t.status === "COMPLETE") return `Done ${tLabel(t.completed_close_day)}`;
  if (t.failing_controls?.length) return `Failing: ${t.failing_controls.join(", ")}`;
  if (t.status === "WAITING") return `Waiting on ${t.depends_on.join(", ")}`;
  if (t.status === "READY_FOR_SIGNOFF") return `Needs ${t.signoff_role} sign-off`;
  if (t.status === "NOT_STARTED" && t.today_close_day != null && t.today_close_day < t.earliest_offset_bd) return `Opens ${tLabel(t.earliest_offset_bd)}`;
  if (t.signoff_role && !t.signed_off_by) return `Needs ${t.signoff_role} sign-off`;
  return t.status;
}

function GoNoGo({ tasks, onNavigate }: { tasks: CloseTask[]; onNavigate: PageProps["onNavigate"] }) {
  const go = tasks.find((t) => t.task_code === "CLS-12");
  const open = tasks.filter((t) => t.status !== "COMPLETE" && t.task_code !== "CLS-12");
  return (
    <Section eyebrow="Controller GO / NO-GO" title={go?.status === "COMPLETE" ? "GO: close complete" : `NO-GO: ${open.length} tasks open`}
             right={<StatusBadge status={go?.status === "COMPLETE" ? "PASS" : "FAIL"} label={go?.status === "COMPLETE" ? "GO" : "NO-GO"} />}>
      <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 300, overflow: "auto" }}>
        {tasks.filter((t) => t.task_code !== "CLS-12").map((t) => (
          <div key={t.task_code} style={{ display: "grid", gridTemplateColumns: "14px 1fr", gap: 8, alignItems: "start" }}>
            <span style={{ width: 10, height: 10, borderRadius: "50%", marginTop: 4,
                           background: t.status === "COMPLETE" ? "var(--success)" : t.status === "BLOCKED" || t.status === "REOPENED" ? "var(--danger)" : "var(--border-strong)" }} />
            <div>
              <div style={{ fontSize: "var(--fs-body-sm)", fontWeight: 600 }}>{t.task_code} {t.task_name}</div>
              <div style={monoCaption}>
                {t.failing_controls?.length ? (
                  <>Failing: {t.failing_controls.map((c, i) => (
                    <React.Fragment key={c}>{i > 0 && ", "}<button onClick={() => onNavigate("checklist", { focusId: c })}
                      style={{ background: "none", border: "none", padding: 0, color: "var(--fg-link)", cursor: "pointer", fontFamily: "var(--font-mono)", fontSize: "var(--fs-caption)" }}>{c}</button></React.Fragment>
                  ))}</>
                ) : blockers(t)}
              </div>
            </div>
          </div>
        ))}
      </div>
    </Section>
  );
}

function TaskTable({ tasks, onNavigate, onSigned }: { tasks: CloseTask[]; onNavigate: PageProps["onNavigate"]; onSigned: () => void }) {
  const [msg, setMsg] = useState<{ kind: "success" | "danger"; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const sign = async (t: CloseTask) => {
    setBusy(t.task_code);
    try {
      const r = await signoffCloseTask(t.task_code, t.period, "", t.signoff_role ?? "reviewer");
      setMsg({ kind: "success", text: `${t.task_code} signed off. ${r.note}` });
      onSigned();
    } catch (e) {
      setMsg({ kind: "danger", text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  };
  return (
    <Stack gap="var(--space-3)">
      {msg && <Notice kind={msg.kind} onClose={() => setMsg(null)}>{msg.text}</Notice>}
      <DataTable rowKey={(t) => t.task_code} rows={tasks} columns={[
        { key: "task_code", label: "Task", width: 70, mono: true },
        { key: "task_name", label: "Close task", render: (t) => (
          <div>
            <div style={{ fontWeight: 600 }}>{t.task_name}</div>
            <div style={monoCaption}>{t.workstream} · {t.owner_role}{t.pre_close ? " · pre-close" : ""}</div>
          </div>
        ) },
        { key: "status", label: "Status", render: (t) => <StatusBadge status={t.status} small /> },
        { key: "due", label: "Due", align: "right", render: (t) => tLabel(t.due_offset_bd) },
        { key: "trad", label: "Traditional", align: "right", render: (t) => tLabel(t.traditional_due_bd) },
        { key: "done", label: "Done / proj.", align: "right", render: (t) => (
          t.completed_close_day != null ? <span style={{ color: "var(--success)" }}>{tLabel(t.completed_close_day)}</span>
            : <span style={{ color: t.is_overdue ? "var(--danger)" : "var(--fg-2)" }}>{tLabel(t.projected_close_day)} proj.</span>
        ) },
        { key: "controls", label: "Bound controls", render: (t) => (
          t.controls.length ? (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {t.controls.map((c) => {
                const failing = t.failing_controls?.includes(c);
                return (
                  <button key={c} onClick={() => onNavigate("checklist", { focusId: c })}
                          style={{ fontFamily: "var(--font-mono)", fontSize: 10, padding: "1px 6px", borderRadius: "var(--radius-pill)", cursor: "pointer",
                                   border: `1px solid ${failing ? "var(--danger)" : "var(--success)"}`,
                                   background: failing ? "var(--danger-bg)" : "var(--success-bg)", color: "var(--fg-1)" }}>{c}</button>
                );
              })}
            </div>
          ) : <span style={monoCaption}>{t.task_code === "CLS-08" ? "manual (sign-off)" : "depends on tasks"}</span>
        ) },
        { key: "signoff", label: "Sign-off", render: (t) => (
          t.signed_off_by ? (
            <div style={monoCaption}>{t.signed_off_by}<br />{String(t.signed_off_at ?? "").replace("T", " ").slice(0, 16)}</div>
          ) : t.signoff_role ? (
            <div>
              <SecondaryBtn onClick={() => sign(t)} disabled={busy === t.task_code} style={{ padding: "3px 10px" }}>
                {busy === t.task_code ? "Signing…" : `Sign off (${t.signoff_role})`}
              </SecondaryBtn>
              {t.status !== "READY_FOR_SIGNOFF" && (
                <div style={{ ...monoCaption, marginTop: 3 }}>
                  {t.controls.length ? "completes once controls pass" : t.depends_on.length ? "completes after its dependencies" : "applies on the next run"}
                </div>
              )}
            </div>
          ) : <span style={monoCaption}>automated</span>
        ) },
        { key: "run", label: "Run", align: "right", render: (t) => (
          t.last_job_run_id ? <Mono dim>{String(t.last_job_run_id).slice(-6)}</Mono> : <span style={monoCaption}>{t.source}</span>
        ) },
      ]} />
    </Stack>
  );
}

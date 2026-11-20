// Re-run controls / Simulate activity, with a live stepper of the run_controls
// tasks. Any viewer sees a run in flight (started from the app, the schedule or
// setup). When the run ends the page reloads its data.
import React, { useCallback, useEffect, useRef, useState } from "react";
import { getActiveRuns, getRunStatus, triggerRunControls, triggerSimulate } from "../api";
import type { RunStatusResponse } from "../types";
import { PrimaryBtn, SecondaryBtn } from "./Buttons";
import { Icon } from "./Icon";
import { invalidateChecklist } from "./ChecklistSlice";
import { DeepLink, monoCaption, Notice } from "./ui";

const STEPS: { key: string; label: string; stage: string }[] = [
  { key: "open_run", label: "Open run", stage: "ledger row" },
  { key: "publish_controls", label: "Publish library", stage: "versioned controls" },
  { key: "snapshot_review_state", label: "Sync reviews", stage: "Lakebase to UC" },
  { key: "test_update", label: "Test controls", stage: "pipeline update" },
  { key: "record_results", label: "Record results", stage: "checklist + close" },
  { key: "triage_exceptions", label: "AI triage", stage: "ai_query" },
  { key: "gate_controls", label: "Integrity gate", stage: "PLT-01" },
];
const ACTIVE = new Set(["PENDING", "QUEUED", "RUNNING", "TERMINATING", "BLOCKED", "WAITING_FOR_RETRY"]);

function stepState(run: RunStatusResponse | null, key: string): "done" | "running" | "failed" | "pending" | "skipped" {
  const t = run?.tasks.find((x) => x.task_key === key);
  if (!t) return "pending";
  if (t.result_state === "SUCCESS") return "done";
  if (t.result_state && t.result_state !== "SUCCESS") return t.result_state === "EXCLUDED" || t.result_state === "UPSTREAM_FAILED" ? "skipped" : "failed";
  if (t.state === "RUNNING" || t.state === "TERMINATING") return "running";
  return "pending";
}

export function RunStepper({ onComplete, compact }: { onComplete?: () => void; compact?: boolean }) {
  const [runId, setRunId] = useState<number | null>(null);
  const [kind, setKind] = useState<"run_controls" | "simulate" | null>(null);
  const [run, setRun] = useState<RunStatusResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [finished, setFinished] = useState<string | null>(null);
  const done = useRef(onComplete);
  done.current = onComplete;

  useEffect(() => {
    getActiveRuns()
      .then((a) => {
        if (a.run_controls) { setRunId(a.run_controls); setKind("run_controls"); }
        else if (a.simulate) { setRunId(a.simulate); setKind("simulate"); }
      })
      .catch((e) => console.error("active runs", e));
  }, []);

  useEffect(() => {
    if (!runId) return;
    let live = true;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const r = await getRunStatus(runId);
        if (!live) return;
        setRun(r);
        if (ACTIVE.has(r.life_cycle_state)) {
          timer = window.setTimeout(tick, 5000);
        } else {
          setFinished(r.result_state === "SUCCESS" ? "Run complete. Results, checklist and close status are updated."
                      : `Run ended: ${r.result_state ?? r.life_cycle_state}. ${r.state_message ?? ""}`);
          setRunId(null);
          invalidateChecklist();
          done.current?.();
        }
      } catch (e) {
        console.error(e);
        if (live) timer = window.setTimeout(tick, 8000);
      }
    };
    tick();
    return () => { live = false; if (timer) window.clearTimeout(timer); };
  }, [runId]);

  const start = useCallback(async (k: "run_controls" | "simulate") => {
    setBusy(true); setError(null); setFinished(null);
    try {
      const r = k === "run_controls" ? await triggerRunControls("Re-run from Audit Workbench") : await triggerSimulate();
      setKind(k); setRun(null); setRunId(r.run_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  const running = runId != null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <PrimaryBtn onClick={() => start("run_controls")} disabled={busy || running}>
          <Icon name="refresh" size={14} /> {running && kind === "run_controls" ? "Controls running…" : "Re-run controls"}
        </PrimaryBtn>
        <SecondaryBtn onClick={() => start("simulate")} disabled={busy || running}
                      title="Append an intraday batch of source activity (with new anomalies), then run the controls">
          <Icon name="lightning" size={14} /> {running && kind === "simulate" ? "Simulating…" : "Simulate activity"}
        </SecondaryBtn>
        {run?.run_page_url && <span style={monoCaption}><DeepLink href={run.run_page_url}>run {run.run_id}</DeepLink></span>}
      </div>
      {error && <Notice kind="danger" onClose={() => setError(null)}>{error}</Notice>}
      {finished && !running && <Notice kind={finished.startsWith("Run complete") ? "success" : "warning"} onClose={() => setFinished(null)}>{finished}</Notice>}
      {running && !compact && (
        <div style={{ display: "flex", gap: 4, alignItems: "stretch", flexWrap: "wrap" }}>
          {kind === "simulate" && run && !run.tasks.some((t) => STEPS.some((s) => s.key === t.task_key)) ? (
            run.tasks.map((t) => <Step key={t.task_key} label={t.task_key.replace(/_/g, " ")} stage={t.state.toLowerCase()}
                                       state={t.result_state === "SUCCESS" ? "done" : t.state === "RUNNING" ? "running" : "pending"} />)
          ) : (
            STEPS.map((s) => <Step key={s.key} label={s.label} stage={s.stage} state={stepState(run, s.key)} />)
          )}
        </div>
      )}
    </div>
  );
}

function Step({ label, stage, state }: { label: string; stage: string; state: "done" | "running" | "failed" | "pending" | "skipped" }) {
  const color = state === "done" ? "var(--success)" : state === "running" ? "var(--db-lava-600)" : state === "failed" ? "var(--danger)" : "var(--border-strong)";
  return (
    <div style={{ flex: "1 1 110px", minWidth: 110, padding: "6px 8px", borderRadius: "var(--radius-sm)", background: "var(--bg-canvas)",
                  border: `1px solid ${color}`, opacity: state === "pending" || state === "skipped" ? 0.6 : 1 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "var(--fs-caption)", fontWeight: 600 }}>
        <span style={{ width: 8, height: 8, borderRadius: "50%", background: color,
                       animation: state === "running" ? "home-pulse 1.6s ease-in-out infinite" : undefined }} />
        {label}
      </div>
      <div style={{ ...monoCaption, fontSize: 10, marginTop: 2 }}>{stage}</div>
    </div>
  );
}

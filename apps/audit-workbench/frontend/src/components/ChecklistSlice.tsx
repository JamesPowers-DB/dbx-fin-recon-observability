// The audit checklist, filtered to a module or a set of controls. One component
// reused on the module tabs, the statements integrity panel and the DQ page, so
// every page shows the same ledger result for a control (latest run_controls run).
import React from "react";
import { getChecklist } from "../api";
import type { ChecklistResponse, ChecklistRow } from "../types";
import type { NavOpts, PageId } from "../App";
import { Async, DeepLink, Mono, StatusBadge, runLinks, useApi, monoCaption } from "./ui";
import { fmtInt, fmtUSD } from "../format";

// One shared fetch per page load: several slices on a page reuse the promise.
let cache: { period: string; at: number; p: Promise<ChecklistResponse> } | null = null;
export function loadChecklist(period?: string): Promise<ChecklistResponse> {
  const key = period ?? "";
  if (cache && cache.period === key && Date.now() - cache.at < 15000) return cache.p;
  const p = getChecklist(period);
  cache = { period: key, at: Date.now(), p };
  p.catch(() => { cache = null; });
  return p;
}
export function invalidateChecklist() { cache = null; }

export function ChecklistSlice({ module, controlIds, period, onNavigate, title, compact }: {
  module?: string; controlIds?: string[]; period?: string; onNavigate: (p: PageId, o?: NavOpts) => void; title?: string; compact?: boolean;
}) {
  const st = useApi(() => loadChecklist(period), [period]);
  const pick = (d: ChecklistResponse): ChecklistRow[] =>
    d.controls.filter((c) => (module ? c.module === module : true) && (controlIds ? controlIds.includes(c.control_id) : true));
  return (
    <Async state={st} empty={(d) => pick(d).length === 0} emptyText="No controls in this slice of the library.">
      {(d) => {
        const rows = pick(d);
        const fails = rows.filter((r) => r.status === "FAIL").length;
        return (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
              <span style={{ ...monoCaption, textTransform: "uppercase" }}>
                {title ?? "Checklist"} · {rows.length} controls · {fails} failing
              </span>
              {d.run && (
                <span style={monoCaption}>
                  run <DeepLink href={runLinks(d.links, { job_id: d.run.job_id, job_run_id: d.run.job_run_id }).run}>{String(d.run.job_run_id)}</DeepLink>
                </span>
              )}
            </div>
            <div style={{ display: "flex", flexDirection: "column", border: "1px solid var(--border)", borderRadius: "var(--radius-md)", overflow: "hidden" }}>
              {rows.map((r) => (
                <button key={r.control_id} onClick={() => onNavigate("checklist", { focusId: r.control_id })}
                        style={{ display: "grid", gridTemplateColumns: compact ? "86px 1fr auto" : "96px 70px 1fr 120px 110px",
                                 gap: 10, alignItems: "center", padding: "8px 12px", background: "var(--bg-canvas)", border: "none",
                                 borderBottom: "1px solid var(--border)", cursor: "pointer", textAlign: "left", fontFamily: "var(--font-sans)" }}
                        onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-subtle)"; }}
                        onMouseLeave={(e) => { e.currentTarget.style.background = "var(--bg-canvas)"; }}>
                  <StatusBadge status={r.status} small />
                  {!compact && <Mono>{r.control_id}</Mono>}
                  <span style={{ fontSize: "var(--fs-body-sm)", color: "var(--fg-1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {compact && <Mono style={{ marginRight: 6 }}>{r.control_id}</Mono>}{r.title}
                    {r.key_control && <Mono dim style={{ marginLeft: 6 }}>KEY</Mono>}
                  </span>
                  {!compact && <Mono dim>{fmtInt(r.exceptions ?? 0)} exc / {fmtInt(r.population ?? 0)}</Mono>}
                  <Mono dim style={{ textAlign: "right" }}>{r.amount_usd ? fmtUSD(r.amount_usd, true) : compact ? `${fmtInt(r.exceptions ?? 0)} exc` : ""}</Mono>
                </button>
              ))}
            </div>
          </div>
        );
      }}
    </Async>
  );
}

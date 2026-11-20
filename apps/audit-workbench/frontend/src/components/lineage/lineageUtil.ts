// Small helpers for the observability pages (lineage, reporting).
import type { LinkTemplates } from "../../types";
import { fillLink } from "../ui";

/** "2026-11-19T05:30:54.859" -> "2026-11-19 05:30" (UTC as recorded). */
export function fmtTs(iso: string | null | undefined): string {
  if (!iso) return "—";
  const s = String(iso).replace("T", " ");
  return s.length >= 16 ? s.slice(0, 16) : s;
}

/** Pipeline-update link. The template carries the app's pipeline id; fall back to the ledger's pipeline id. */
export function updateHref(links: LinkTemplates | undefined, updateId: string | null | undefined, pipelineId?: string | null): string | null {
  if (!links || !updateId) return null;
  let tpl = links.pipeline_update;
  if (tpl.includes("/pipelines//")) {
    if (!pipelineId) return null;
    tpl = tpl.replace("/pipelines//", `/pipelines/${pipelineId}/`);
  }
  return fillLink(tpl, { update_id: updateId });
}

export function jobRunHref(links: LinkTemplates | undefined, jobId: number | null | undefined, runId: number | null | undefined): string | null {
  return fillLink(links?.job_run, { job_id: jobId, run_id: runId });
}

export function tableHref(links: LinkTemplates | undefined, table: string | null | undefined): string | null {
  return fillLink(links?.table, { table });
}

export const shortId = (s: string | null | undefined, n = 8) => (s ? String(s).slice(0, n) : "—");

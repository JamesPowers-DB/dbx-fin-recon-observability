import type {
  AppConfigResponse, MeResponse, RunStatusResponse, RunTriggerResponse,
  CloseSummary, CloseBurndown, CloseTrendPoint, CloseTask, ChecklistResponse, ControlDetail,
  ExceptionsResponse, ExceptionDetail, StatementResponse, IntegrityResponse, VariancesResponse, DrillResponse,
  SankeyResponse, LineageDatasets, LineageFeeds, LineageExpectations, FailingRecords, LineageTimeline,
  ModuleResponse, RisksResponse, SoxPack, ReportSummary, ArchitectureStatus, ChatSession, ChatMessage, Row,
} from "./types";

const API = "/api";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, init);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    let detail = text;
    try { detail = (JSON.parse(text) as { detail?: string }).detail ?? text; } catch { /* plain text */ }
    throw new ApiError(res.status, detail || `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

const get = <T>(path: string) => request<T>(path);
const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const put = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const del = <T>(path: string) => request<T>(path, { method: "DELETE" });

/** Query string from defined, non-empty params only. */
export const qs = (params?: Record<string, string | number | boolean | null | undefined>) => {
  if (!params) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
};

// ── System ──────────────────────────────────────────────────────────────────
export const getMe = () => get<MeResponse>("/me");
export const getAppConfig = () => get<AppConfigResponse>("/config");

// ── Runs (control execution via the app service principal) ─────────────────
export const triggerRunControls = (reason: string) => post<RunTriggerResponse>("/runs", { kind: "run_controls", reason });
export const triggerSimulate = (scenario = "auto") => post<RunTriggerResponse>("/runs", { kind: "simulate", scenario });
export const getRunStatus = (runId: number) => get<RunStatusResponse>(`/runs/${runId}`);
export const getActiveRuns = () => get<{ run_controls: number | null; simulate: number | null }>("/runs/active");

// ── Close Cockpit ───────────────────────────────────────────────────────────
export const getCloseSummary = () => get<CloseSummary>("/close/summary");
export const getCloseTrend = () => get<CloseTrendPoint[]>("/close/trend");
export const getCloseTasks = (period?: string) => get<CloseTask[]>(`/close/tasks${qs({ period })}`);
export const getBurndown = (period?: string) => get<CloseBurndown>(`/close/burndown${qs({ period })}`);
export const signoffCloseTask = (taskCode: string, period: string, comment = "", role = "reviewer") =>
  post<{ status: string; note: string }>(`/close/tasks/${encodeURIComponent(taskCode)}/signoff`, { period, comment, role });

// ── Audit Checklist ─────────────────────────────────────────────────────────
export const getChecklist = (period?: string) => get<ChecklistResponse>(`/checklist${qs({ period })}`);
export const getControlDetail = (controlId: string, period?: string) =>
  get<ControlDetail>(`/checklist/${encodeURIComponent(controlId)}${qs({ period })}`);
export const signoffControl = (controlId: string, period: string, comment = "") =>
  post<{ status: string; attested_job_run_id: number; note: string }>(`/checklist/${encodeURIComponent(controlId)}/signoff`, { period, comment });

// ── Exceptions & Review ─────────────────────────────────────────────────────
export const getExceptions = (p?: { period?: string; module?: string; control?: string; status?: string; limit?: number }) =>
  get<ExceptionsResponse>(`/exceptions${qs(p)}`);
export const getException = (id: string) => get<ExceptionDetail>(`/exceptions/${encodeURIComponent(id)}`);
export const actOnException = (id: string, body: { action: "propose" | "approve" | "reject" | "reopen"; disposition?: string; comment?: string; role?: string }) =>
  post<{ status: string; note: string }>(`/exceptions/${encodeURIComponent(id)}/actions`, body);
export const saveWorkingPaper = (id: string, body: { title: string; body_md: string; ai_draft_md?: string | null; agent_session_id?: string | null }) =>
  put<{ status: string }>(`/exceptions/${encodeURIComponent(id)}/working-paper`, body);
export const evidenceDocumentUrl = (path: string) => `${API}/exceptions/evidence/document${qs({ path })}`;

// ── Financial Statements ────────────────────────────────────────────────────
export const getStatement = (statement: "IS" | "BS" | "CF", entity = "ALL", period?: string) =>
  get<StatementResponse>(`/statements${qs({ statement, entity, period })}`);
export const getIntegrity = (period?: string) => get<IntegrityResponse>(`/statements/integrity${qs({ period })}`);
export const getVariances = (p?: { period?: string; entity?: string; material_only?: boolean }) =>
  get<VariancesResponse>(`/statements/variances${qs(p)}`);
export const explainVariance = (variance_key: string, explanation: string, ai_draft?: string | null) =>
  post<{ status: string }>("/statements/variances/explain", { variance_key, explanation, ai_draft });
export const acknowledgeVariance = (variance_key: string, comment = "") =>
  post<{ status: string }>("/statements/variances/acknowledge", { variance_key, comment });
export const draftVarianceExplanation = (variance_key: string) =>
  post<{ draft: string; drivers: Row[]; model: string; label: string }>("/statements/variances/ai-draft", { variance_key });
export const drillLine = (line: string, entity = "ALL", period?: string) =>
  get<DrillResponse>(`/statements/drill${qs({ line, entity, period })}`);

// ── Data Quality & Lineage ──────────────────────────────────────────────────
export const getSankey = (level: "domain" | "dataset" = "domain", update_id?: string) =>
  get<SankeyResponse>(`/lineage/sankey${qs({ level, update_id })}`);
export const getLineageDatasets = (update_id?: string) => get<LineageDatasets>(`/lineage/datasets${qs({ update_id })}`);
export const getFeeds = () => get<LineageFeeds>("/lineage/feeds");
export const getExpectations = () => get<LineageExpectations>("/lineage/expectations");
export const getFailingRecords = (dataset: string, expectation?: string) =>
  get<FailingRecords>(`/lineage/failing-records${qs({ dataset, expectation })}`);
export const getLineageTimeline = () => get<LineageTimeline>("/lineage/timeline");

// ── Recons & Testing ────────────────────────────────────────────────────────
export const getModule = (name: "cash" | "subledger" | "journals" | "access", period?: string) =>
  get<ModuleResponse>(`/modules/${name}${qs({ period })}`);

// ── Risk & Reporting ────────────────────────────────────────────────────────
export const getRisks = (period?: string) => get<RisksResponse>(`/reporting/risks${qs({ period })}`);
export const getSoxPack = (period?: string) => get<SoxPack>(`/reporting/sox-pack${qs({ period })}`);
export const draftReportSummary = (period?: string) => post<ReportSummary>(`/reporting/summary${qs({ period })}`, {});

// ── Architecture ────────────────────────────────────────────────────────────
export const getArchitectureStatus = () => get<ArchitectureStatus>("/architecture/status");

// ── Audit Assistant (SSE) ───────────────────────────────────────────────────
export const createChatSession = (title?: string) => post<ChatSession>("/assistant/sessions", { title });
export const listChatSessions = () => get<ChatSession[]>("/assistant/sessions");
export const getChatMessages = (id: string) => get<ChatMessage[]>(`/assistant/sessions/${encodeURIComponent(id)}/messages`);
export const deleteChatSession = (id: string) => del<{ deleted: string }>(`/assistant/sessions/${encodeURIComponent(id)}`);

export type ChatEvent =
  | { type: "content"; text: string }
  | { type: "tool_start"; id: string; name: string; args: Record<string, unknown> }
  | { type: "tool_result"; id: string; name: string; summary: string; ok: boolean; sql?: string[] | string | null; preview?: Row[]; extra?: Record<string, unknown> }
  | { type: "error"; message: string }
  | { type: "done"; model?: string };

export async function streamChat(sessionId: string, content: string, context: Record<string, unknown> | null,
                                 onEvent: (e: ChatEvent) => void): Promise<void> {
  const res = await fetch(`${API}/assistant/sessions/${encodeURIComponent(sessionId)}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, context }),
  });
  if (!res.ok || !res.body) throw new ApiError(res.status, await res.text().catch(() => ""));
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop() ?? "";
    for (const p of parts) {
      const line = p.trim();
      if (line.startsWith("data: ")) {
        try { onEvent(JSON.parse(line.slice(6)) as ChatEvent); } catch (e) { console.error("bad SSE frame", e, line); }
      }
    }
  }
}

export { post, put, del };

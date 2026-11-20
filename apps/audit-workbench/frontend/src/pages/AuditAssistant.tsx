// Audit Assistant: the investigator agent. Answers come from tool calls over the
// same governed tables and metric views the pages use; each tool card shows the
// SQL it ran. The agent drafts and explains; dispositions stay human (four-eyes).
import React, { useCallback, useEffect, useRef, useState } from "react";
import type { PageProps } from "../App";
import {
  createChatSession, deleteChatSession, getChatMessages, listChatSessions, streamChat, type ChatEvent,
} from "../api";
import type { ChatMessage, ChatSession } from "../types";
import { AiBadge, ErrorNote, Mono, Notice, Page, linkBtn, monoCaption } from "../components/ui";
import { PageHero } from "../components/layout/PageHero";
import { PrimaryBtn, SecondaryBtn } from "../components/Buttons";
import { Icon } from "../components/Icon";
import { Markdown } from "../components/Markdown";
import { ThinkingLine, ToolCard, TOOL_LABEL, type ToolCall } from "../components/assistant/ToolCard";

type Part = { kind: "text"; text: string } | { kind: "tool"; call: ToolCall };
interface UiMsg { key: string; role: "user" | "assistant"; parts: Part[]; model?: string; error?: string; pending?: boolean; }

const SUGGESTIONS = [
  "Where are we in the close?",
  "Which key controls failed in the latest run?",
  "Investigate the largest open cash exception.",
  "Draft a working paper for a JET-01 exception.",
  "Ask Genie: days to close by month for the last 12 months.",
];

let seq = 0;
const nextKey = () => `m${Date.now()}-${seq++}`;

function fromStored(m: ChatMessage): UiMsg {
  const parts: Part[] = [];
  if (m.role === "assistant" && Array.isArray(m.tool_calls)) {
    m.tool_calls.forEach((t, i) => parts.push({ kind: "tool", call: {
      id: `${m.message_id}-${i}`, name: String(t.name ?? "tool"), args: (t.args ?? {}) as Record<string, unknown>, done: true,
      ok: t.ok !== false, summary: t.summary as string | undefined, sql: t.sql as string[] | string | null,
    } }));
  }
  if (m.content && m.content !== "(no text)") parts.push({ kind: "text", text: m.content });
  return { key: m.message_id, role: m.role === "user" ? "user" : "assistant", parts };
}

export function AuditAssistant({ nav, onNavigate }: PageProps) {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<UiMsg[]>([]);
  const [loadingMsgs, setLoadingMsgs] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [input, setInput] = useState("");
  const [context, setContext] = useState<Record<string, unknown> | null>(null);
  const handoffDone = useRef(false);
  const scroller = useRef<HTMLDivElement>(null);

  const refreshSessions = useCallback(() => {
    listChatSessions()
      .then((s) => { setSessions(Array.isArray(s) ? s : []); setSessionsError(null); })
      .catch((e) => { console.error(e); setSessionsError(e instanceof Error ? e.message : String(e)); });
  }, []);

  useEffect(() => { refreshSessions(); }, [refreshSessions]);
  useEffect(() => { scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" }); }, [msgs]);

  const patchLast = (key: string, f: (m: UiMsg) => UiMsg) =>
    setMsgs((prev) => prev.map((m) => (m.key === key ? f(m) : m)));

  const send = useCallback(async (text: string, ctx?: Record<string, unknown> | null, forceNew = false) => {
    const q = text.trim();
    if (!q || streaming) return;
    setStreaming(true);
    setInput("");
    let sid = forceNew ? null : activeId;
    const aKey = nextKey();
    if (forceNew) setMsgs([]);
    setMsgs((prev) => [...(forceNew ? [] : prev), { key: nextKey(), role: "user", parts: [{ kind: "text", text: q }] },
                       { key: aKey, role: "assistant", parts: [], pending: true }]);
    try {
      if (!sid) {
        const s = await createChatSession(q.slice(0, 70));
        sid = s.session_id;
        setActiveId(sid);
        setSessions((prev) => [s, ...prev.filter((x) => x.session_id !== s.session_id)]);
      }
      await streamChat(sid, q, ctx ?? null, (e: ChatEvent) => {
        patchLast(aKey, (m) => {
          const parts = [...m.parts];
          switch (e.type) {
            case "content": {
              const last = parts[parts.length - 1];
              if (last && last.kind === "text") parts[parts.length - 1] = { kind: "text", text: last.text + e.text };
              else parts.push({ kind: "text", text: e.text });
              return { ...m, parts };
            }
            case "tool_start":
              parts.push({ kind: "tool", call: { id: e.id, name: e.name, args: e.args ?? {}, done: false } });
              return { ...m, parts };
            case "tool_result":
              return { ...m, parts: parts.map((p) => p.kind === "tool" && p.call.id === e.id
                ? { kind: "tool", call: { ...p.call, done: true, ok: e.ok, summary: e.summary, sql: e.sql, preview: e.preview, extra: e.extra } }
                : p) };
            case "error":
              return { ...m, error: e.message, pending: false };
            case "done":
              return { ...m, model: e.model, pending: false };
            default:
              return m;
          }
        });
      });
    } catch (e) {
      console.error(e);
      patchLast(aKey, (m) => ({ ...m, error: e instanceof Error ? e.message : String(e), pending: false }));
    } finally {
      patchLast(aKey, (m) => ({ ...m, pending: false }));
      setStreaming(false);
      refreshSessions();
    }
  }, [activeId, streaming, refreshSessions]);

  // Investigate handoff from Exceptions & Review: new session, question sent with the exception as context.
  useEffect(() => {
    const eid = nav.context?.exception_id;
    if (handoffDone.current || typeof eid !== "string" || !eid) return;
    handoffDone.current = true;
    const ctx = { exception_id: eid };
    setContext(ctx);
    setActiveId(null);
    send(`Investigate exception ${eid.slice(0, 10)}: what is the likely root cause, what evidence supports it, and what should the reviewer request?`, ctx, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openSession = async (id: string) => {
    if (streaming) return;
    setActiveId(id); setContext(null); setLoadingMsgs(true);
    try {
      const rows = await getChatMessages(id);
      setMsgs(rows.filter((m) => m.role !== "tool").map(fromStored));
    } catch (e) {
      console.error(e);
      setMsgs([{ key: nextKey(), role: "assistant", parts: [], error: `Could not load this conversation: ${e instanceof Error ? e.message : String(e)}` }]);
    } finally {
      setLoadingMsgs(false);
    }
  };

  const newSession = () => { if (!streaming) { setActiveId(null); setMsgs([]); setContext(null); setInput(""); } };
  const removeSession = async (id: string) => {
    try { await deleteChatSession(id); } catch (e) { console.error(e); }
    if (id === activeId) newSession();
    refreshSessions();
  };

  return (
    <Page>
      <PageHero eyebrow="Insights · Audit Assistant" title="Audit Assistant"
                subtitle="An investigator agent over the governed data: close status, checklist results, exceptions, source records, evidence and Genie. Every tool call shows the SQL it ran. It drafts and explains; it never approves a disposition."
                right={<SecondaryBtn onClick={newSession} disabled={streaming}><Icon name="plus" size={14} /> New investigation</SecondaryBtn>} />

      <div style={{ display: "grid", gridTemplateColumns: "260px minmax(0, 1fr)", gap: "var(--space-5)", height: "calc(100vh - 250px)", minHeight: 520 }}>
        {/* Sessions */}
        <aside style={{ background: "var(--bg-canvas)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--border)", ...monoCaption, textTransform: "uppercase" }}>Investigations</div>
          <div style={{ flex: 1, overflow: "auto" }}>
            {sessionsError && <div style={{ padding: 12, ...monoCaption }}>History unavailable (review store offline). Chat still works.</div>}
            {!sessionsError && sessions.length === 0 && <div style={{ padding: 12, ...monoCaption }}>No saved investigations yet.</div>}
            {sessions.map((s) => (
              <div key={s.session_id}
                   style={{ display: "flex", alignItems: "flex-start", gap: 6, padding: "10px 12px", borderBottom: "1px solid var(--border)",
                            background: s.session_id === activeId ? "var(--bg-subtle)" : undefined,
                            boxShadow: s.session_id === activeId ? "inset 3px 0 0 var(--db-lava-600)" : undefined }}>
                <button onClick={() => openSession(s.session_id)} disabled={streaming}
                        style={{ flex: 1, minWidth: 0, background: "none", border: "none", padding: 0, textAlign: "left", cursor: streaming ? "default" : "pointer", fontFamily: "var(--font-sans)" }}>
                  <div style={{ fontSize: "var(--fs-body-sm)", color: "var(--fg-1)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.title || "Investigation"}</div>
                  <div style={{ ...monoCaption, fontSize: 11 }}>{String(s.updated_at ?? s.created_at ?? "").replace("T", " ").slice(0, 16)}</div>
                </button>
                <button onClick={() => removeSession(s.session_id)} aria-label="Delete investigation" title="Delete"
                        style={{ ...linkBtn, color: "var(--fg-3)" }}><Icon name="x" size={12} /></button>
              </div>
            ))}
          </div>
        </aside>

        {/* Conversation */}
        <section style={{ background: "var(--bg-canvas)", border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", display: "flex", flexDirection: "column", overflow: "hidden" }}>
          {context?.exception_id != null && (
            <div style={{ padding: "10px 16px", borderBottom: "1px solid var(--border)" }}>
              <Notice kind="info">
                Investigating exception <Mono>{String(context.exception_id).slice(0, 10)}</Mono>.{" "}
                <button style={linkBtn} onClick={() => onNavigate("exceptions", { focusId: String(context.exception_id) })}>Back to the exception</button>
              </Notice>
            </div>
          )}
          <div ref={scroller} style={{ flex: 1, overflow: "auto", padding: "var(--space-5)", display: "flex", flexDirection: "column", gap: "var(--space-5)" }}>
            {loadingMsgs && <div style={monoCaption}>loading conversation…</div>}
            {!loadingMsgs && msgs.length === 0 && <Empty onPick={(q) => send(q)} disabled={streaming} />}
            {msgs.map((m) => (m.role === "user" ? <UserBubble key={m.key} m={m} /> : <AssistantMsg key={m.key} m={m} />))}
          </div>
          <Composer value={input} onChange={setInput} onSend={() => send(input, context)} disabled={streaming} />
        </section>
      </div>
    </Page>
  );
}

function Empty({ onPick, disabled }: { onPick: (q: string) => void; disabled: boolean }) {
  return (
    <div style={{ margin: "auto", maxWidth: 620, textAlign: "center" }}>
      <Icon name="bot" size={28} color="var(--db-navy-400)" />
      <div style={{ fontSize: "var(--fs-h4)", fontWeight: 700, margin: "8px 0 4px" }}>Start an investigation</div>
      <div style={{ fontSize: "var(--fs-body-sm)", color: "var(--fg-2)", marginBottom: 16 }}>
        Ask about the close, a control, an exception or a trend. Tools: {Object.values(TOOL_LABEL).join(", ")}.
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center" }}>
        {SUGGESTIONS.map((s) => (
          <button key={s} disabled={disabled} onClick={() => onPick(s)}
                  style={{ padding: "8px 12px", borderRadius: "var(--radius-pill)", border: "1px solid var(--border-strong)", background: "var(--bg-canvas)",
                           cursor: disabled ? "default" : "pointer", fontSize: "var(--fs-body-sm)", fontFamily: "var(--font-sans)", color: "var(--fg-1)" }}>
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

function UserBubble({ m }: { m: UiMsg }) {
  const text = m.parts.map((p) => (p.kind === "text" ? p.text : "")).join("").replace(/^\[Context: [^\]]+\]\n/, "");
  return (
    <div style={{ alignSelf: "flex-end", maxWidth: "75%", background: "var(--db-navy-800)", color: "var(--fg-on-dark)",
                  padding: "10px 14px", borderRadius: "var(--radius-lg)", fontSize: "var(--fs-body-sm)", whiteSpace: "pre-wrap", lineHeight: 1.5 }}>
      {text}
    </div>
  );
}

function AssistantMsg({ m }: { m: UiMsg }) {
  const last = m.parts[m.parts.length - 1];
  const runningTool = m.parts.find((p) => p.kind === "tool" && !p.call.done) as { kind: "tool"; call: ToolCall } | undefined;
  const thinking = m.pending && (!last || last.kind === "tool");
  return (
    <div style={{ alignSelf: "stretch", display: "flex", flexDirection: "column", gap: 8, maxWidth: "92%" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Icon name="bot" size={16} color="var(--db-navy-700)" />
        <span style={{ fontSize: "var(--fs-body-sm)", fontWeight: 600 }}>Audit Investigator</span>
        <AiBadge model={m.model} text={m.model ? `AI-generated · ${m.model}` : "AI-generated"} />
      </div>
      {m.parts.map((p, i) => (p.kind === "tool"
        ? <ToolCard key={p.call.id || i} t={p.call} />
        : <div key={i} style={{ paddingLeft: 24 }}><Markdown text={p.text} /></div>))}
      {thinking && <div style={{ paddingLeft: 24 }}><ThinkingLine text={runningTool ? `Running ${TOOL_LABEL[runningTool.call.name] ?? runningTool.call.name}…` : "Thinking…"} /></div>}
      {m.error && <div style={{ paddingLeft: 24 }}><ErrorNote message={m.error} /></div>}
    </div>
  );
}

function Composer({ value, onChange, onSend, disabled }: { value: string; onChange: (v: string) => void; onSend: () => void; disabled: boolean }) {
  return (
    <div style={{ borderTop: "1px solid var(--border)", padding: "12px 16px", display: "flex", gap: 10, alignItems: "flex-end" }}>
      <textarea value={value} onChange={(e) => onChange(e.target.value)} rows={2} disabled={disabled}
                placeholder="Ask about the close, a control or an exception. Enter to send, Shift+Enter for a new line."
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (!disabled) onSend(); } }}
                style={{ flex: 1, resize: "none", fontFamily: "var(--font-sans)", fontSize: "var(--fs-body-sm)", padding: "9px 12px",
                         borderRadius: "var(--radius-md)", border: "1px solid var(--border-strong)", background: "var(--bg-canvas)", lineHeight: 1.5 }} />
      <PrimaryBtn onClick={onSend} disabled={disabled || !value.trim()}><Icon name="send" size={14} /> Send</PrimaryBtn>
      <span style={{ ...monoCaption, maxWidth: 170, fontSize: 10 }}>AI-generated answers from governed data. Verify before use.</span>
    </div>
  );
}

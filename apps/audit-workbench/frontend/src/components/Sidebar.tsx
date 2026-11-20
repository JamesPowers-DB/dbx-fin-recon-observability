import React from "react";
import { Icon, type IconName } from "./Icon";
import type { PageId } from "../App";
import type { MeResponse } from "../types";

interface NavItem {
  id: PageId;
  label: string;
  icon: IconName;
}

interface NavSection {
  title: string;
  items: readonly NavItem[];
}

// Four sections mirror the story: run the close, test the modules, get
// insight, and see the platform underneath.
export const NAV_SECTIONS: readonly NavSection[] = [
  {
    title: "Close",
    items: [
      { id: "close",      label: "Close Cockpit",        icon: "cal" },
      { id: "checklist",  label: "Audit Checklist",      icon: "check" },
      { id: "exceptions", label: "Exceptions & Review",  icon: "warn" },
    ],
  },
  {
    title: "Modules",
    items: [
      { id: "modules",    label: "Recons & Testing",     icon: "table" },
      { id: "statements", label: "Financial Statements", icon: "doc" },
    ],
  },
  {
    title: "Insights",
    items: [
      { id: "assistant",  label: "Audit Assistant",      icon: "bot" },
      { id: "reporting",  label: "Risk & Reporting",     icon: "shield" },
    ],
  },
  {
    title: "Platform",
    items: [
      { id: "lineage",      label: "Data Quality & Lineage", icon: "data" },
      { id: "architecture", label: "Architecture",           icon: "build" },
    ],
  },
];

export const NAV: readonly NavItem[] = NAV_SECTIONS.flatMap((s) => s.items);

interface SidebarProps {
  page: PageId;
  onNavigate: (p: PageId) => void;
  user: MeResponse | null;
  searchQuery: string;
  onSearch: (q: string) => void;
}

export function Sidebar({ page, onNavigate, user, searchQuery, onSearch }: SidebarProps) {
  return (
    <aside
      style={{
        width: 232,
        minWidth: 232,
        background: "var(--bg-inverse-deep)",
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        borderRight: "1px solid var(--border-dark)",
        flexShrink: 0,
      }}
    >
      {/* Brand mark + title */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "var(--space-3)",
          padding: "var(--space-5) var(--space-5) var(--space-4)",
          borderBottom: "1px solid var(--border-dark)",
        }}
      >
        <img
          src="/ds/assets/databricks-symbol-light.svg"
          alt="Databricks"
          style={{ height: 22, width: 22 }}
        />
        <div>
          <div style={{ color: "var(--fg-on-dark)", fontWeight: 700, fontSize: 13, lineHeight: 1.2 }}>
            Audit Workbench
          </div>
          <div
            style={{
              color: "var(--fg-on-dark-2)",
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              letterSpacing: "0.04em",
            }}
          >
            Continuous Close
          </div>
        </div>
      </div>

      {/* Search input */}
      <div
        style={{
          margin: "var(--space-3) var(--space-4)",
          background: "var(--bg-inverse)",
          border: `1px solid ${searchQuery ? "var(--db-lava-600)" : "var(--border-dark)"}`,
          borderRadius: "var(--radius-sm)",
          padding: "var(--space-2) var(--space-3)",
          display: "flex",
          alignItems: "center",
          gap: "var(--space-2)",
          transition: "border-color var(--dur-fast)",
        }}
      >
        <Icon name="search" size={13} color={searchQuery ? "var(--db-lava-600)" : "var(--fg-on-dark-2)"} />
        <input
          value={searchQuery}
          onChange={(e) => onSearch(e.target.value)}
          placeholder="Search…"
          style={{
            flex: 1,
            background: "transparent",
            border: "none",
            outline: "none",
            color: "var(--fg-on-dark)",
            fontSize: 13,
            fontFamily: "var(--font-sans)",
            padding: 0,
          }}
        />
        {searchQuery ? (
          <button
            onClick={() => onSearch("")}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: 0,
              display: "flex",
              alignItems: "center",
            }}
          >
            <Icon name="x" size={12} color="var(--fg-on-dark-2)" />
          </button>
        ) : (
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              color: "var(--db-navy-400)",
              background: "var(--bg-inverse-deep)",
              border: "1px solid var(--border-dark)",
              borderRadius: "var(--radius-xs)",
              padding: "0 4px",
              flexShrink: 0,
            }}
          >
            ⌘K
          </span>
        )}
      </div>

      {/* Nav items */}
      <nav style={{ flex: 1, padding: "var(--space-2) 0", overflowY: "auto" }}>
        {NAV_SECTIONS.map((section) => (
          <div key={section.title} style={{ marginBottom: "var(--space-2)" }}>
            <div
              style={{
                padding: "var(--space-3) var(--space-5) var(--space-1)",
                fontFamily: "var(--font-mono)",
                fontSize: 10,
                letterSpacing: "var(--tracking-eyebrow)",
                textTransform: "uppercase",
                color: "var(--db-navy-400)",
              }}
            >
              {section.title}
            </div>
            {section.items.map((item) => {
              const active = page === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => onNavigate(item.id)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "var(--space-3)",
                    width: "100%",
                    padding: "8px var(--space-5)",
                    background: active ? "rgba(255,54,33,0.12)" : "transparent",
                    color: active ? "var(--fg-on-dark)" : "var(--fg-on-dark-2)",
                    border: "none",
                    borderLeft: `2px solid ${active ? "var(--db-lava-600)" : "transparent"}`,
                    fontSize: 13.5,
                    fontWeight: active ? 600 : 400,
                    cursor: "pointer",
                    transition: "background var(--dur-fast), color var(--dur-fast)",
                    textAlign: "left",
                  }}
                >
                  <Icon name={item.icon} size={15} color={active ? "var(--db-lava-600)" : "var(--fg-on-dark-2)"} />
                  {item.label}
                </button>
              );
            })}
          </div>
        ))}
      </nav>

      {/* Persona footer */}
      <div
        style={{
          padding: "var(--space-3) var(--space-5)",
          borderTop: "1px solid var(--border-dark)",
          display: "flex",
          flexDirection: "column",
          gap: "var(--space-1)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--fg-on-dark-2)" }}>
            Company
          </span>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--db-lava-600)" }}>
            Corvane Tech
          </span>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--fg-on-dark-2)" }}>
            Data
          </span>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--fg-on-dark-2)" }}>
            Synthetic
          </span>
        </div>
      </div>

      {/* User chip */}
      {user && (
        <div
          style={{
            padding: "var(--space-3) var(--space-4)",
            borderTop: "1px solid var(--border-dark)",
            display: "flex",
            alignItems: "center",
            gap: "var(--space-3)",
          }}
        >
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: "50%",
              background: "var(--db-lava-600)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              fontWeight: 700,
              color: "var(--fg-on-dark)",
              flexShrink: 0,
            }}
          >
            {user.initials}
          </div>
          <div style={{ overflow: "hidden" }}>
            <div
              style={{
                color: "var(--fg-on-dark)",
                fontSize: 12,
                fontWeight: 600,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {user.display_name}
            </div>
            <div
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10,
                color: "var(--fg-on-dark-2)",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {user.email}
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}

# Databricks notebook source
# MAGIC %md
# MAGIC # 09: prior close-tool history export
# MAGIC
# MAGIC The close-management history migrated from the tool used before Databricks.
# MAGIC It covers closed periods only; the active close is run live by `run_controls`
# MAGIC and the Audit Workbench.
# MAGIC
# MAGIC | File | Grain | Used for |
# MAGIC |---|---|---|
# MAGIC | `close_tool/close_task_history.csv` | period x task | days-to-close trend, historical burndowns |
# MAGIC | `close_tool/review_history.csv` | control x period x record | dispositions of past exceptions (RESOLVED results) |
# MAGIC | `close_tool/variance_commentary_history.csv` | period x entity x FSLI | flux explanations and acknowledgements |
# MAGIC
# MAGIC Storyline: FY2025 is a traditional close at T+7 to T+9. From 2026, continuous
# MAGIC monitoring moves pre-close tasks before month end and days to close falls
# MAGIC toward T+3.
# MAGIC
# MAGIC Every planted closed-period exception is dispositioned here, except the gaps
# MAGIC Internal Audit should find:
# MAGIC * an unexplained material variance whose flux task the close tool still marked
# MAGIC   complete (FPA-03);
# MAGIC * an explanation acknowledged by its own author (FPA-04).

# COMMAND ----------
# MAGIC %run ./_lib

# COMMAND ----------
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "fin_recon_observability")
dbutils.widgets.text("raw_volume", "files")
catalog, schema, raw_volume = get_widget("catalog"), get_widget("schema"), get_widget("raw_volume", "files")
as_of = load_as_of(catalog, schema, raw_volume)
ay, am = active_period(as_of)
ACTIVE = period_key(ay, am)
CT = volume_dir(catalog, schema, raw_volume, "close_tool")
wipe_family(CT, "")
rng = rng_for("close_tool")
cal = load_yaml("controls/close_calendar.yml")
tasks = cal["tasks"]
fin = read_scratch(catalog, schema, raw_volume, "finance_people")
workers = read_scratch(catalog, schema, raw_volume, "workers")
email = dict(zip(workers["Worker_ID"].to_list(), workers["Email_Address"].to_list()))
users = read_scratch(catalog, schema, raw_volume, "erp_users")
uid_email = dict(zip(users["user_id"].to_list(), users["email_address"].to_list()))
fin = fin.with_columns(pl.col("user_id").replace_strict(uid_email, default=None).alias("email"))
by_role = {r: fin.filter(pl.col("job") == r)["email"].to_list() for r in fin["job"].unique().to_list()}
controllers = by_role["Controller"]
DTC_2025 = [9, 8, 8, 9, 8, 8, 8, 7, 8, 8, 7, 9]
DTC_2026 = [7, 6, 6, 5, 5, 4, 4, 4, 3, 3, 3, 3]


def person(role, k=0):
    pool_ = by_role.get(role) or controllers
    return pool_[k % len(pool_)]

# COMMAND ----------
# MAGIC %md ## Close task history (closed periods)

# COMMAND ----------
closed = [(y, m) for (y, m) in periods_through(as_of) if (y, m) < (ay, am)]
hist, dtc_by_period = [], {}
for i, (y, m) in enumerate(closed):
    dtc = DTC_2025[m - 1] if y == 2025 else DTC_2026[min(m - 1, len(DTC_2026) - 1)]
    continuous = (y, m) >= (2026, 4)
    dtc_by_period[period_key(y, m)] = dtc
    done = {}
    for k, t in enumerate(tasks):
        if t["task_code"] == "CLS-12":
            off = dtc
        elif continuous and t.get("pre_close"):
            off = int(rng.integers(-3, 1))
        else:
            plan = t["traditional_due_bd"] if y == 2025 else t["due_offset_bd"]
            scale = dtc / (cal["traditional_days_to_close"] if y == 2025 else max(cal["target_days_to_close"], 1))
            off = int(round(max(1, plan) * scale + rng.normal(0, 0.6)))
            off = max(1, min(dtc - (1 if t["task_code"] == "CLS-11" else 0), off))
        for dep in t.get("depends_on", []):
            off = max(off, done.get(dep, off))
        done[t["task_code"]] = off
        due = t["traditional_due_bd"] if y == 2025 else t["due_offset_bd"]
        comp_d = date_for_close_offset(y, m, off)
        comp = ts(comp_d, int(rng.integers(10, 18)), int(rng.integers(0, 59)))
        prep = person(t["owner_role"], i + k)
        rev = person("Controller", i + k + 1)
        if rev == prep:
            rev = person("Controller", i + k + 2)
        hist.append({"period": period_key(y, m), "task_code": t["task_code"], "task_name": t["name"],
                     "workstream": t["workstream"], "preparer": prep,
                     "reviewer": rev if t.get("signoff") else "automated",
                     "due_date": date_for_close_offset(y, m, due), "completed_at": comp,
                     "completed_close_day": off,
                     "signed_off_by": rev if t.get("signoff") else None,
                     "signed_off_at": comp + timedelta(minutes=int(rng.integers(20, 240))) if t.get("signoff") else None,
                     "status": "Complete", "source_tool": "Legacy close management"})
hist_df = frame(hist)
write_csv(hist_df, f"{CT}/close_task_history.csv")
print(f"close task history rows={hist_df.height}; days to close: {dtc_by_period}")

# COMMAND ----------
# MAGIC %md ## Review history: dispositions of planted closed-period exceptions

# COMMAND ----------
pe = (spark.table(f"`{catalog}`.`{schema}`.meta_planted_exceptions")
      .where(f"period < '{ACTIVE}' AND expected_disposition <> 'open'").toPandas())
COMMENT = {
    "explained": "Investigated; business rationale documented and supported. No adjustment required.",
    "adjusted": "Root cause confirmed; correcting entry posted and evidence attached.",
    "remediated": "Access removed and ticket closed; compensating review performed for the exposure window.",
    "false_positive": "Rule matched a legitimate pattern; no issue.",
}
rev_rows = []
for k, r in enumerate(pe.to_dict("records")):
    y, m = int(r["period"][:4]), int(r["period"][5:7])
    dtc = dtc_by_period.get(r["period"], 4)
    p_at = ts(date_for_close_offset(y, m, max(1, dtc - 1)), 11, int(rng.integers(0, 59)))
    prep = person("Senior Accountant", k)
    rev = person("Controller", k + 3)
    rev_rows.append({"control_id": r["control_id"], "record_key": r["record_key"], "period": r["period"],
                     "disposition": r["expected_disposition"], "prepared_by": prep, "prepared_at": p_at,
                     "reviewed_by": rev, "reviewed_at": p_at + timedelta(hours=3),
                     "comment": COMMENT.get(r["expected_disposition"], "Reviewed."),
                     "source_tool": "Legacy close management"})
write_csv(frame(rev_rows) if rev_rows else pl.DataFrame(schema={"control_id": pl.Utf8}), f"{CT}/review_history.csv")
print(f"review history rows={len(rev_rows)}")

# COMMAND ----------
# MAGIC %md ## Variance commentary history

# COMMAND ----------
vp = read_scratch(catalog, schema, raw_volume, "variance_plan")
EXPL = {"61000": "Campaign spend deferred to next quarter; budget phasing assumed launch this month.",
        "50000": "Unplanned capacity for two large customer migrations; recovered through usage billing next quarter.",
        "60000": "Engineering contractor ramp ahead of plan for the platform release.",
        "62000": "Legal and advisory fees for an entity restructuring not in the budget.",
        "40000": "Two renewals slipped into the following month; pipeline unchanged."}
com = []
for k, v in enumerate(vp.iter_rows(named=True)):
    if v["treatment"] == "unexplained":
        continue
    y, m = int(v["period"][:4]), int(v["period"][5:7])
    author = controllers[k % len(controllers)]
    ack = author if v["treatment"] == "self_acknowledged" else controllers[(k + 4) % len(controllers)]
    a_at = ts(date_for_close_offset(y, m, 2), 15, 10)
    com.append({"period": v["period"], "entity_code": v["entity_code"], "fsli_code": v["fsli_code"],
                "explanation": EXPL.get(v["account"], "Variance reviewed."), "author": author, "authored_at": a_at,
                "acknowledged_by": ack, "acknowledged_at": a_at + timedelta(hours=20), "ai_draft_used": False,
                "source_tool": "Legacy close management"})
write_csv(frame(com), f"{CT}/variance_commentary_history.csv")
print(f"variance commentary rows={len(com)}")

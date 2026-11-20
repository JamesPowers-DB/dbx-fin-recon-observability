# Databricks notebook source
# MAGIC %md
# MAGIC # 40: simulate activity (one intraday batch, live demo driver)
# MAGIC
# MAGIC Appends ONE batch of new source files to the active close, then the job runs
# MAGIC `run_controls`. Streaming bronze picks the new files up incrementally (no
# MAGIC full refresh). Nothing is future-dated: journals carry yesterday's
# MAGIC accounting date (the data cutoff) and are created minutes before now.
# MAGIC
# MAGIC | Scenario | Files | What the next control run shows |
# MAGIC |---|---|---|
# MAGIC | `self_approved_journal` | `oracle/gl_je_headers_<YYYY>M<MM>_b<NNN>.csv` + lines | NEW JET-01 (preparer approved own journal) and JET-05 (round amount) exceptions, AI-triaged; routine journals flow through the Sankey |
# MAGIC | `bank_feed_catch_up` | `bank/camt053_<account>_<YYYYMM>_b001.xml` | the withheld BR01 statements arrive: DQ-01 (stale feed) and CASH-01 (continuity) resolve; the data-quality close task can complete |
# MAGIC
# MAGIC `auto` plays the deck in order (the bank catch-up first, then a self-approved
# MAGIC journal, then further journals in other entities). Planted items are registered in
# MAGIC `meta_planted_exceptions` (generator `40_simulate_activity`) so the PLT-01
# MAGIC recall check covers them; delivered outage items are retired from the
# MAGIC registry. The daily refresh regenerates everything and removes batch files.

# COMMAND ----------
# MAGIC %run ./_lib

# COMMAND ----------
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "fin_recon_observability")
dbutils.widgets.text("raw_volume", "files")
dbutils.widgets.text("scenario", "auto")
dbutils.widgets.text("job_run_id", "")
catalog, schema, raw_volume = get_widget("catalog"), get_widget("schema"), get_widget("raw_volume", "files")
scenario = (get_widget("scenario", "auto") or "auto").strip()
FQ = f"`{catalog}`.`{schema}`"
as_of = load_as_of(catalog, schema, raw_volume)
ay, am = active_period(as_of)
ACTIVE = period_key(ay, am)
cutoff = data_cutoff(as_of)
now = datetime.now(timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
ORA = volume_dir(catalog, schema, raw_volume, "oracle")
BANK = volume_dir(catalog, schema, raw_volume, "bank")
WH = os.path.join(scratch_dir(catalog, schema, raw_volume), "withheld_bank")
OUTAGE_ACCOUNT = "BR01-OPS-0001"

journal_batches = sorted(glob.glob(f"{ORA}/gl_je_headers_{ay:04d}M{am:02d}_b*.csv"))
bank_delivered = bool(glob.glob(f"{BANK}/camt053_*_b001.xml"))
if scenario == "auto":
    # Deck order for the run-of-show: the bank feed catches up first (DQ-01 and
    # CASH-01 resolve, the data-quality task can complete), then new journal
    # activity with a self-approved journal (JET-01 fails again, the journal
    # review task reopens), then further journals in other entities.
    scenario = ("bank_feed_catch_up" if not bank_delivered and glob.glob(f"{WH}/*.xml")
                else "self_approved_journal")
assert scenario in ("self_approved_journal", "bank_feed_catch_up"), f"unknown scenario {scenario}"
print(f"active close {ACTIVE}, cutoff {cutoff}, scenario {scenario}, prior journal batches {len(journal_batches)}")

# Planted registry for this generator accumulates across batches.
prior = (spark.table(f"{FQ}.meta_planted_exceptions").where("generator = '40_simulate_activity'").toPandas()
         if spark.catalog.tableExists(f"{catalog}.{schema}.meta_planted_exceptions") else None)
planted = PlantedRegistry("40_simulate_activity")
if prior is not None:
    for r in prior.to_dict("records"):
        planted.add(r["module"], r["control_id"], r["record_key"], r["entity_code"], r["period"], r["amount_usd"],
                    r["description"], r["expected_disposition"])
result = {"scenario": scenario, "period": ACTIVE}

# COMMAND ----------
# MAGIC %md ## Scenario: self-approved round-dollar journal (+ routine journals)

# COMMAND ----------
if scenario == "self_approved_journal":
    batch = len(journal_batches) + 1
    rng = rng_for(f"simulate:{ACTIVE}:{batch}")
    ent = ["DE01", "US02", "CA01", "SG01", "IE01", "GB01"][(batch - 1) % 6]
    e = ENTITY_BY_CODE[ent]
    users = read_scratch(catalog, schema, raw_volume, "finance_people")
    fin = users.filter(pl.col("entity") == ent)
    preparers = fin.filter(pl.col("job").is_in(["Senior Accountant", "Accountant"]))["user_id"].to_list()
    controllers = fin.filter(pl.col("job") == "Controller")["user_id"].to_list()
    ghosts = set(read_scratch(catalog, schema, raw_volume, "erp_users").filter(pl.col("end_date").is_not_null())["user_id"].to_list()) \
        if "end_date" in read_scratch(catalog, schema, raw_volume, "erp_users").columns else set()
    preparers = [u for u in preparers if u not in ghosts] or preparers
    assert preparers and controllers, f"no finance users for {ent}"
    max_id = spark.sql(f"SELECT max(CAST(je_header_id AS BIGINT)) AS m FROM {FQ}.bronze_oracle_gl_je_headers").collect()[0]["m"] or 1_000_000
    for f_ in journal_batches:
        max_id = max(max_id, int(pl.read_csv(f_, infer_schema_length=0)["je_header_id"].cast(pl.Int64).max()))
    rate = fx_rate(e["currency"], cutoff.year, cutoff.month)
    H, L = [], []
    jid = int(max_id)

    def journal(name, desc, lines, created_by, approved_by, created_at, category="Reclass"):
        global jid
        jid += 1
        approved_at = created_at + timedelta(minutes=12)
        posted_at = approved_at + timedelta(minutes=6)
        H.append({"je_header_id": jid, "ledger_id": e["ledger_id"], "period_name": oracle_period_name(cutoff.year, cutoff.month),
                  "je_source": "Manual", "je_category": category, "name": name, "description": desc, "status": "P",
                  "actual_flag": "A", "default_effective_date": cutoff, "posted_date": posted_at, "created_by": int(created_by),
                  "creation_date": created_at, "approval_status_code": "A", "approved_by": int(approved_by),
                  "approval_date": approved_at, "currency_code": e["currency"]})
        dr_tot = cr_tot = 0.0
        for i, (acct, dr, cr, ldesc) in enumerate(lines, start=1):
            adr, acr = round(dr * rate, 2), round(cr * rate, 2)
            dr_tot += adr
            cr_tot += acr
            L.append({"je_header_id": jid, "je_line_num": i, "code_combination_id": f"{ent}-COR-{acct}", "entered_dr": round(dr, 2),
                      "entered_cr": round(cr, 2), "accounted_dr": adr, "accounted_cr": acr, "description": ldesc,
                      "reference_1": None, "reference_2": None, "currency_conversion_rate": rate, "effective_date": cutoff})
        diff = round(dr_tot - cr_tot, 2)
        if diff:   # keep accounted amounts balanced after FX rounding
            last = L[-1]
            if last["accounted_cr"]:
                last["accounted_cr"] = round(last["accounted_cr"] + diff, 2)
            else:
                last["accounted_dr"] = round(last["accounted_dr"] - diff, 2)
        H[-1]["running_total_dr"] = round(sum(x["accounted_dr"] for x in L if x["je_header_id"] == jid), 2)
        H[-1]["running_total_cr"] = round(sum(x["accounted_cr"] for x in L if x["je_header_id"] == jid), 2)
        return jid

    # Routine activity: approved by the entity controller, non-round amounts, opex reclasses only (no balance-sheet effect).
    t0 = now - timedelta(minutes=55)
    for k in range(4):
        a = float(round(rng.uniform(4_000, 38_000), 2))
        src, dst = [("62000", "60000"), ("61000", "62000"), ("60000", "61000"), ("62000", "61000")][k]
        journal(f"Cost center reclass {cutoff:%Y%m%d}-{batch}{k}", "Reclass between cost centers per allocation review",
                [(dst, a, 0.0, "Reclass"), (src, 0.0, a, "Reclass")],
                created_by=preparers[k % len(preparers)], approved_by=controllers[0], created_at=t0 + timedelta(minutes=7 * k))
    # The anomaly: a round-dollar reclass the preparer approved themselves.
    prep = preparers[(batch + 1) % len(preparers)]
    fc = 400_000.0 if e["currency"] in ("USD", "EUR", "GBP", "CAD", "SGD") else 2_000_000.0
    je = journal(f"Reclass shared services {cutoff:%Y%m%d}-{batch}", "Year-to-date shared services true-up",
                 [("62000", fc, 0.0, "Shared services true-up"), ("61000", 0.0, fc, "Shared services true-up")],
                 created_by=prep, approved_by=prep, created_at=now - timedelta(minutes=18))
    amt_usd = round(fc * rate, 2)
    planted.add("M3", "JET-01", str(je), ent, ACTIVE, amt_usd,
                f"Simulated batch {batch}: journal {je} created and approved by the same user ({prep})")
    planted.add("M3", "JET-05", str(je), ent, ACTIVE, amt_usd,
                f"Simulated batch {batch}: round-amount manual journal {je}")

    hdr_cols = ["je_header_id", "ledger_id", "period_name", "je_source", "je_category", "name", "description", "status",
                "actual_flag", "default_effective_date", "posted_date", "created_by", "creation_date", "approval_status_code",
                "approved_by", "approval_date", "currency_code", "running_total_dr", "running_total_cr"]
    line_cols = ["je_header_id", "je_line_num", "code_combination_id", "entered_dr", "entered_cr", "accounted_dr", "accounted_cr",
                 "description", "reference_1", "reference_2", "currency_conversion_rate", "effective_date"]
    hdr = frame(H).select(hdr_cols)
    lin = frame(L).select(line_cols)
    write_csv(hdr, os.path.join(ORA, month_file("gl_je_headers", ay, am, "csv", batch)))
    write_csv(lin, os.path.join(ORA, month_file("gl_je_lines", ay, am, "csv", batch)))
    result.update({"batch": batch, "entity": ent, "journals": hdr.height, "lines": lin.height, "planted_journal": je,
                   "planted_amount_usd": amt_usd, "preparer_user_id": int(prep)})
    print(f"batch {batch}: {hdr.height} journals ({lin.height} lines) in {ent}; planted self-approved journal {je} (USD {amt_usd:,.0f})")

# COMMAND ----------
# MAGIC %md ## Scenario: the bank feed catches up (withheld BR01 statements delivered)

# COMMAND ----------
if scenario == "bank_feed_catch_up":
    files = sorted(glob.glob(f"{WH}/*.xml"))
    assert files, "no withheld statements (the outage only exists when the active month has enough business days)"
    for f_ in files:
        name = os.path.basename(f_).replace(".xml", "_b001.xml")
        with open(f_) as src, open(os.path.join(BANK, name), "w") as dst:
            dst.write(src.read())
    # The outage is over: those planted items are no longer expected to be detected.
    spark.sql(f"""DELETE FROM {FQ}.meta_planted_exceptions
                  WHERE generator = '07_bank_camt053' AND period = '{ACTIVE}'
                    AND ((control_id = 'CASH-01' AND record_key LIKE '{OUTAGE_ACCOUNT}|%')
                         OR (control_id = 'DQ-01' AND record_key = 'bank:{OUTAGE_ACCOUNT}'))""")
    result.update({"delivered_files": [os.path.basename(x) for x in files]})
    print(f"delivered {len(files)} withheld statement file(s) for {OUTAGE_ACCOUNT}")

# COMMAND ----------
planted.save(spark, catalog, schema)
dbutils.notebook.exit(json.dumps(result, default=str))

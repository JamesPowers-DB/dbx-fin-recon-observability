# Databricks notebook source
# MAGIC %md
# MAGIC # 02: reference masters (Oracle, Workday, Salesforce)
# MAGIC
# MAGIC Writes the stable master files every module reads:
# MAGIC
# MAGIC | Folder | File | Native table |
# MAGIC |---|---|---|
# MAGIC | `oracle/` | `gl_ledgers.csv` | GL_LEDGERS (one ledger per legal entity) |
# MAGIC | `oracle/` | `gl_code_combinations.csv` | GL_CODE_COMBINATIONS (entity-segment-account) |
# MAGIC | `oracle/` | `gl_account_hierarchy.csv` | FND_FLEX_VALUES natural-account hierarchy with FSLI mapping |
# MAGIC | `oracle/` | `poz_suppliers.csv` | POZ_SUPPLIERS |
# MAGIC | `oracle/` | `fnd_user.csv` | FND_USER (ERP users, employee_id = Workday Worker_ID) |
# MAGIC | `oracle/` | `per_user_roles.csv` | PER_USER_ROLES (role grant history) |
# MAGIC | `oracle/` | `per_user_role_requests.csv` | provisioning requests (requester, approver) |
# MAGIC | `workday/` | `workers.parquet` | Workers (RaaS), with hire and termination dates |
# MAGIC | `salesforce/` | `Account.json` | Account |
# MAGIC
# MAGIC Planted access exceptions (M4, registered in `meta_planted_exceptions`):
# MAGIC SoD conflicts (PAM-01), late access removal after termination (PAM-02),
# MAGIC privileged grants without an approved request (PAM-04). Post-termination
# MAGIC postings (PAM-03) are planted by 06_oracle_gl using the users flagged here.

# COMMAND ----------
# MAGIC %run ./_lib

# COMMAND ----------
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "fin_recon_observability")
dbutils.widgets.text("raw_volume", "files")
catalog, schema, raw_volume = get_widget("catalog"), get_widget("schema"), get_widget("raw_volume", "files")
as_of = load_as_of(catalog, schema, raw_volume)
cutoff = data_cutoff(as_of)
ay, am = active_period(as_of)
ACTIVE = period_key(ay, am)
ORA = volume_dir(catalog, schema, raw_volume, "oracle")
WD = volume_dir(catalog, schema, raw_volume, "workday")
SF = volume_dir(catalog, schema, raw_volume, "salesforce")
planted = PlantedRegistry("02_reference_masters")
rng = rng_for("masters")
for folder, prefixes in ((ORA, ["gl_ledgers", "gl_code_combinations", "gl_account_hierarchy", "poz_suppliers",
                                "fnd_user", "per_user_roles", "per_user_role_requests"]),
                         (WD, ["workers"]), (SF, ["Account"])):
    for p in prefixes:
        wipe_family(folder, p)
print(f"as_of={as_of} active={ACTIVE}")

# COMMAND ----------
# MAGIC %md ## Oracle: ledgers, accounts, code combinations

# COMMAND ----------
ledgers = frame([{
    "ledger_id": e["ledger_id"], "name": f"{e['code']} Primary Ledger", "short_name": e["code"],
    "legal_entity_name": e["name"], "country_code": e["country"], "region": e["region"],
    "currency_code": e["currency"], "chart_of_accounts_id": 50101, "period_set_name": "CORVANE_MONTHLY",
    "bank_name": e["bank"],
} for e in ENTITIES])
write_csv(ledgers, f"{ORA}/gl_ledgers.csv")

hier = frame([dict(zip(COA_DF_COLUMNS, row)) for row in COA]).rename({"account": "flex_value"})
hier = hier.with_columns(
    pl.lit("CORVANE_ACCOUNT").alias("flex_value_set_name"),
    pl.lit("Y").alias("enabled_flag"),
    pl.when(pl.col("control_subledger").is_not_null()).then(pl.lit("Y")).otherwise(pl.lit("N")).alias("is_control_account"),
    pl.when(pl.col("account_type").is_in(["A", "X"])).then(pl.lit("D")).otherwise(pl.lit("C")).alias("normal_balance"),
)
write_csv(hier, f"{ORA}/gl_account_hierarchy.csv")

ccid_rows = []
for e in ENTITIES:
    for (acct, *_rest) in COA:
        segs = SEGMENT_CODES if acct in ("40000", "41000", "42000", "50000", "51000", "52000", "11000") else [CORPORATE_SEGMENT]
        for s in segs:
            ccid_rows.append({"code_combination_id": f"{e['code']}-{s}-{acct}", "segment1": e["code"],
                              "segment2": s, "segment3": acct, "enabled_flag": "Y", "chart_of_accounts_id": 50101})
ccids = frame(ccid_rows)
write_csv(ccids, f"{ORA}/gl_code_combinations.csv")
print(f"ledgers={ledgers.height} accounts={hier.height} ccids={ccids.height}")

# COMMAND ----------
# MAGIC %md ## Workday workers
# MAGIC
# MAGIC Headcount weights for payroll allocation. Salaries are weights only; payroll
# MAGIC totals are anchored to the opex targets in 04_workday_payroll.

# COMMAND ----------
HEADCOUNT = 1800
DEPT_MIX = [("RND", 0.40), ("SNM", 0.35), ("GNA", 0.15), ("SVC", 0.10)]
JOB_BY_DEPT = {"RND": ["Software Engineer", "Senior Software Engineer", "Staff Engineer", "Product Manager"],
               "SNM": ["Account Executive", "Solutions Engineer", "Marketing Manager", "Customer Success Manager"],
               "GNA": ["Accountant", "HR Business Partner", "Legal Counsel", "IT Engineer"],
               "SVC": ["Implementation Consultant", "Technical Architect"]}
ent_codes = np.array(ENTITY_CODES)
ent_w = np.array([e["mix"] for e in ENTITIES])
ent_w = ent_w / ent_w.sum()
workers = []
for i in range(HEADCOUNT):
    ent = str(rng.choice(ent_codes, p=ent_w))
    dept = str(rng.choice([d for d, _ in DEPT_MIX], p=[w for _, w in DEPT_MIX]))
    fn, ln = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
    hire = date(2016, 1, 4) + timedelta(days=int(rng.integers(0, 365 * 9)))
    term = None
    if rng.random() < 0.13:     # ~6%/yr attrition over the generated window
        t = date(2025, 1, 6) + timedelta(days=int(rng.integers(0, max(1, (cutoff - date(2025, 1, 6)).days))))
        term = t if t > hire else None
    workers.append({
        "Worker_ID": f"W{100001 + i}", "Legal_Name": f"{fn} {ln}",
        "Email_Address": f"{fn.lower()}.{ln.lower()}{i % 97}@corvane.example",
        "Company": ent, "Cost_Center": f"CC-{dept}-{ent}", "Supervisory_Org": dept,
        "Job_Profile": str(rng.choice(JOB_BY_DEPT[dept])), "Hire_Date": hire, "Termination_Date": term,
        "Worker_Status": "Terminated" if term and term <= cutoff else "Active",
        "Annual_Base_Salary": float(round(rng.lognormal(11.7, 0.35), -2)),
        "Currency": ENTITY_BY_CODE[ent]["currency"],
    })

# Finance and IT people who hold ERP access (also Workday workers).
FIN_ROLES = [("Accountant", 18), ("Senior Accountant", 8), ("Controller", 8), ("AP Specialist", 6),
             ("AR Specialist", 4), ("Treasury Analyst", 3), ("Payroll Accountant", 3),
             ("Financial Analyst", 6), ("IT Security Engineer", 2)]
fin_people = []
idx = HEADCOUNT
for job, n in FIN_ROLES:
    for k in range(n):
        ent = ENTITY_CODES[k % len(ENTITY_CODES)] if job != "IT Security Engineer" else "US01"
        fn, ln = FIRST_NAMES[(idx * 7) % len(FIRST_NAMES)], LAST_NAMES[(idx * 11) % len(LAST_NAMES)]
        wid = f"W{100001 + idx}"
        workers.append({
            "Worker_ID": wid, "Legal_Name": f"{fn} {ln}", "Email_Address": f"{fn.lower()}.{ln.lower()}@corvane.example",
            "Company": ent, "Cost_Center": f"CC-GNA-{ent}", "Supervisory_Org": "GNA", "Job_Profile": job,
            "Hire_Date": date(2017, 3, 1) + timedelta(days=int(rng.integers(0, 2200))), "Termination_Date": None,
            "Worker_Status": "Active", "Annual_Base_Salary": float(round(rng.lognormal(11.9, 0.25), -2)),
            "Currency": ENTITY_BY_CODE[ent]["currency"],
        })
        fin_people.append({"worker_idx": len(workers) - 1, "job": job, "entity": ent, "first": fn, "last": ln})
        idx += 1

# COMMAND ----------
# MAGIC %md ## Oracle users, role grants, provisioning requests

# COMMAND ----------
ROLES_BY_JOB = {
    "Accountant": ["GL_JOURNAL_ENTRY"], "Senior Accountant": ["GL_JOURNAL_ENTRY"],
    "Controller": ["GL_JOURNAL_APPROVER", "GL_PERIOD_CLOSE"], "AP Specialist": ["AP_INVOICE_ENTRY"],
    "AR Specialist": ["AR_RECEIPT_ENTRY"], "Treasury Analyst": ["AP_PAYMENT_RELEASE"],
    "Payroll Accountant": ["PAYROLL_INTERFACE"], "Financial Analyst": ["FINANCIAL_ANALYST"],
    "IT Security Engineer": ["SECURITY_ADMIN"],
}
users, grants, requests = [], [], []
for (uid, uname, desc, _use) in SYSTEM_USERS:
    users.append({"user_id": uid, "user_name": uname, "description": desc, "employee_id": None,
                  "email_address": None, "start_date": date(2019, 1, 1), "end_date": None,
                  "is_system_account": "Y", "last_logon_date": ts(cutoff, 23, 50)})
req_seq = 70000
for k, p in enumerate(fin_people):
    w = workers[p["worker_idx"]]
    uid = 5001 + k
    p["user_id"] = uid
    start = max(w["Hire_Date"], date(2022, 1, 3))
    users.append({"user_id": uid, "user_name": f"{p['first'].upper()}.{p['last'].upper()}",
                  "description": f"{p['job']}, {p['entity']}", "employee_id": w["Worker_ID"],
                  "email_address": w["Email_Address"], "start_date": start, "end_date": None,
                  "is_system_account": "N", "last_logon_date": ts(cutoff, 17, int(rng.integers(0, 59)))})
    for role in ROLES_BY_JOB[p["job"]]:
        grants.append({"user_id": uid, "role_name": role, "role_common_name": ERP_ROLES[role][0],
                       "privileged_flag": "Y" if ERP_ROLES[role][1] else "N", "start_date": start, "end_date": None,
                       "assigned_by": "SECURITY_ADMIN_WF"})
        if ERP_ROLES[role][1]:
            req_seq += 1
            requests.append({"request_id": req_seq, "user_id": uid, "role_name": role,
                             "requested_by": "MANAGER_SELF_SERVICE", "requested_date": start - timedelta(days=3),
                             "approved_by": "ACCESS_GOVERNANCE_BOARD", "approval_date": start - timedelta(days=1),
                             "status": "APPROVED"})

by_job = {}
for p in fin_people:
    by_job.setdefault(p["job"], []).append(p)

# PAM-01: SoD conflicts in the active period (grant starts in the active month).
act_start = month_start(ay, am)
conflicts = [
    (by_job["Senior Accountant"][0], "GL_JOURNAL_APPROVER", ("GL_JOURNAL_ENTRY", "GL_JOURNAL_APPROVER")),
    (by_job["AP Specialist"][0], "AP_PAYMENT_RELEASE", ("AP_INVOICE_ENTRY", "AP_PAYMENT_RELEASE")),
    (by_job["Treasury Analyst"][0], "VENDOR_MASTER_MAINT", ("VENDOR_MASTER_MAINT", "AP_PAYMENT_RELEASE")),
]
for person, extra_role, pair in conflicts:
    start = act_start + timedelta(days=int(rng.integers(1, 6)))
    start = min(start, cutoff)
    grants.append({"user_id": person["user_id"], "role_name": extra_role, "role_common_name": ERP_ROLES[extra_role][0],
                   "privileged_flag": "Y" if ERP_ROLES[extra_role][1] else "N", "start_date": start,
                   "end_date": None, "assigned_by": "SECURITY_ADMIN_WF"})
    if ERP_ROLES[extra_role][1]:
        req_seq += 1
        requests.append({"request_id": req_seq, "user_id": person["user_id"], "role_name": extra_role,
                         "requested_by": "MANAGER_SELF_SERVICE", "requested_date": start - timedelta(days=2),
                         "approved_by": "ACCESS_GOVERNANCE_BOARD", "approval_date": start - timedelta(days=1),
                         "status": "APPROVED"})
    planted.add("M4", "PAM-01", f"{person['user_id']}|{pair[0]}+{pair[1]}", person["entity"], ACTIVE, 0.0,
                f"User {person['user_id']} ({person['job']}) granted {extra_role}, creating SoD conflict {pair[0]} + {pair[1]}")
# The self-approving senior accountant is used by 06_oracle_gl for JET-01 scenarios.
sod_journal_user = conflicts[0][0]["user_id"]

# PAM-02 / PAM-03: finance users terminated in Workday whose Oracle access lingered.
ghost_users = []
ghost_specs = [  # (job, months before active, removal lag business days, posts after termination)
    ("Accountant", 2, 9, False),       # closed period, dispositioned in close-tool history
    ("Accountant", 0, None, True),     # active period, never removed, keeps posting
    ("AR Specialist", 0, None, False), # active period, never removed
    ("Senior Accountant", 1, 6, True), # previous month, removed late, posted once after termination
]
used = set()
for job, back, lag, posts in ghost_specs:
    person = next(p for p in by_job[job] if p["user_id"] not in used and p["user_id"] != sod_journal_user)
    used.add(person["user_id"])
    y, m = ay, am
    for _ in range(back):
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    bds = [d for d in business_days(y, m) if d <= cutoff]
    term = bds[min(len(bds) - 1, max(1, len(bds) // 3))]
    w = workers[person["worker_idx"]]
    w["Termination_Date"], w["Worker_Status"] = term, "Terminated"
    u = next(u for u in users if u["user_id"] == person["user_id"])
    u["end_date"] = add_business_days(term, lag) if lag is not None else None
    per = period_key(y, m)
    planted.add("M4", "PAM-02", f"{person['user_id']}", person["entity"], per, 0.0,
                f"{job} terminated in Workday {term}; Oracle access " +
                (f"removed {lag} business days later" if lag is not None else "still active"),
                expected_disposition="remediated" if back >= 2 else "open")
    ghost_users.append({"user_id": person["user_id"], "entity": person["entity"], "termination_date": term,
                        "access_end": u["end_date"], "posts_after_termination": posts, "period": per})

# Properly offboarded finance user (control works): access removed the next business day.
ok_person = next(p for p in by_job["Financial Analyst"] if p["user_id"] not in used)
ok_term = [d for d in business_days(ay, am) if d <= cutoff][0]
workers[ok_person["worker_idx"]]["Termination_Date"] = ok_term
workers[ok_person["worker_idx"]]["Worker_Status"] = "Terminated"
next(u for u in users if u["user_id"] == ok_person["user_id"])["end_date"] = add_business_days(ok_term, 1)

# PAM-04: privileged grants with no approved provisioning request.
pam4 = [(by_job["Controller"][3], "AP_PAYMENT_RELEASE", 0), (by_job["IT Security Engineer"][1], "GL_PERIOD_CLOSE", 0),
        (by_job["Controller"][5], "SECURITY_ADMIN", 3)]
for person, role, back in pam4:
    y, m = ay, am
    for _ in range(back):
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    start = min(month_start(y, m) + timedelta(days=int(rng.integers(2, 9))), cutoff)
    end = month_end(y, m) if back else None
    grants.append({"user_id": person["user_id"], "role_name": role, "role_common_name": ERP_ROLES[role][0],
                   "privileged_flag": "Y", "start_date": start, "end_date": end, "assigned_by": "DIRECT_ASSIGNMENT"})
    planted.add("M4", "PAM-04", f"{person['user_id']}|{role}|{start.isoformat()}", person["entity"],
                period_key(y, m), 0.0, f"Privileged role {role} assigned directly to user {person['user_id']} without an approved request",
                expected_disposition="remediated" if back else "open")

workers_df = frame(workers)
users_df = frame(users)
grants_df = frame(grants)
requests_df = frame(requests)
write_parquet(workers_df, f"{WD}/workers.parquet")
write_csv(users_df, f"{ORA}/fnd_user.csv")
write_csv(grants_df, f"{ORA}/per_user_roles.csv")
write_csv(requests_df, f"{ORA}/per_user_role_requests.csv")
print(f"workers={workers_df.height} erp_users={users_df.height} grants={grants_df.height} requests={requests_df.height}")

# COMMAND ----------
# MAGIC %md ## Counterparties: Salesforce accounts and Oracle suppliers

# COMMAND ----------
cust = []
seen = set()
for i in range(600):
    ent = str(rng.choice(ent_codes, p=ent_w))
    country = ENTITY_BY_CODE[ent]["country"]
    while True:
        name = f"{rng.choice(NAME_PREFIX)} {rng.choice(CUSTOMER_INDUSTRY)} {rng.choice(LEGAL_SUFFIX[country])}"
        if name not in seen:
            seen.add(name)
            break
    cust.append({"Id": "001" + stable_id("acct", i)[:15], "Name": name, "BillingCountry": country,
                 "Type": str(rng.choice(["Customer - Direct", "Customer - Channel"], p=[0.8, 0.2])),
                 "CurrencyIsoCode": ENTITY_BY_CODE[ent]["currency"], "Corvane_Entity__c": ent,
                 "Industry": name.split(" ")[-2] if len(name.split(" ")) > 2 else "Other",
                 "CreatedDate": f"{date(2018, 1, 1) + timedelta(days=int(rng.integers(0, 2500)))}T10:00:00.000+0000"})
cust_df = frame(cust)
write_jsonl(cust_df, f"{SF}/Account.json")

SUPPLIER_TYPES = [
    # category, name stem, expense account, segment, share of non-payroll spend
    ("hosting", "Cloud Services", "50000", "CLD", None),
    ("hosting", "Data Centers", "50000", "ENT", None),
    ("components", "Components", "51000", "DEV", None),
    ("contractors", "Consulting", "52000", "SVC", None),
    ("rnd_tools", "Software", "60000", CORPORATE_SEGMENT, None),
    ("marketing", "Media", "61000", CORPORATE_SEGMENT, None),
    ("gna_services", "Advisory", "62000", CORPORATE_SEGMENT, None),
    ("facilities", "Properties", "62000", CORPORATE_SEGMENT, None),
    ("capex", "Equipment", "15000", CORPORATE_SEGMENT, None),
    ("prepaid", "Insurance Brokers", "12000", CORPORATE_SEGMENT, None),
]
sup, seen = [], set()
for i in range(320):
    cat = SUPPLIER_TYPES[i % len(SUPPLIER_TYPES)]
    ent = str(rng.choice(ent_codes, p=ent_w))
    country = ENTITY_BY_CODE[ent]["country"]
    while True:
        name = f"{rng.choice(NAME_PREFIX)} {cat[1]} {rng.choice(LEGAL_SUFFIX[country])}"
        if name not in seen:
            seen.add(name)
            break
    sup.append({"vendor_id": 30001 + i, "vendor_name": name, "segment1": f"S{30001 + i}", "vendor_type_lookup_code":
                cat[0], "default_expense_account": cat[2], "default_segment": cat[3], "country": country,
                "home_entity": ent, "enabled_flag": "Y", "creation_date": date(2019, 6, 1) + timedelta(days=i)})
sup_df = frame(sup)
write_csv(sup_df, f"{ORA}/poz_suppliers.csv")
print(f"customers={cust_df.height} suppliers={sup_df.height}")

# COMMAND ----------
# MAGIC %md ## Scratch hand-off and planted registry

# COMMAND ----------
write_scratch(workers_df, catalog, schema, raw_volume, "workers")
write_scratch(users_df, catalog, schema, raw_volume, "erp_users")
write_scratch(frame(fin_people).drop("worker_idx"), catalog, schema, raw_volume, "finance_people")
write_scratch(frame(ghost_users), catalog, schema, raw_volume, "ghost_users")
write_scratch(frame([{"sod_journal_user": sod_journal_user}]), catalog, schema, raw_volume, "scenario_users")
write_scratch(cust_df, catalog, schema, raw_volume, "customers")
write_scratch(sup_df, catalog, schema, raw_volume, "suppliers")
planted.save(spark, catalog, schema)

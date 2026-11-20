-- ============================================================================
-- SILVER (M2): conformed subledger documents
-- ============================================================================
CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_supplier
COMMENT "Suppliers (Oracle POZ_SUPPLIERS)."
AS SELECT 'Oracle Fusion ERP' AS source_system, 'poz_suppliers' AS source_table, vendor_id AS source_primary_key,
  CAST(vendor_id AS BIGINT) AS vendor_id, vendor_name, vendor_type_lookup_code AS vendor_type, country, home_entity
FROM ${schema}.bronze_oracle_poz_suppliers;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_ap_invoice
COMMENT "AP invoices (Oracle Payables), functional currency. account_code from the distribution."
AS SELECT 'Oracle Fusion ERP' AS source_system, 'ap_invoices_all' AS source_table, i.invoice_id AS source_primary_key,
  CAST(i.invoice_id AS BIGINT) AS invoice_id, i.invoice_num, CAST(i.vendor_id AS BIGINT) AS vendor_id, i.vendor_name,
  e.entity_code, CAST(i.invoice_date AS DATE) AS invoice_date, CAST(i.gl_date AS DATE) AS gl_date,
  CAST(i.invoice_amount AS DECIMAL(18,2)) AS invoice_amount, i.invoice_currency_code AS currency_code,
  i.terms_name, CAST(i.due_date AS DATE) AS due_date, i.approval_status, i.payment_status_flag, i.description,
  i.dist_code_combination_id, split_part(i.dist_code_combination_id, '-', 3) AS account_code,
  CAST(i.created_by AS BIGINT) AS created_by_user_id, i._source_file
FROM ${schema}.bronze_oracle_ap_invoices_all i
JOIN ${schema}.silver_entity e ON e.ledger_id = CAST(i.org_id AS BIGINT);

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_ap_payment
COMMENT "AP payments (Oracle AP_CHECKS_ALL)."
AS SELECT 'Oracle Fusion ERP' AS source_system, 'ap_checks_all' AS source_table, c.check_id AS source_primary_key,
  CAST(c.check_id AS BIGINT) AS check_id, c.check_number, CAST(c.invoice_id AS BIGINT) AS invoice_id,
  CAST(c.vendor_id AS BIGINT) AS vendor_id, e.entity_code, CAST(c.amount AS DECIMAL(18,2)) AS amount,
  c.currency_code, CAST(c.check_date AS DATE) AS check_date, c.bank_account_name, c.payment_method_code
FROM ${schema}.bronze_oracle_ap_checks_all c
JOIN ${schema}.silver_entity e ON e.ledger_id = CAST(c.org_id AS BIGINT);

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_customer
COMMENT "Customers (Salesforce Account)."
AS SELECT 'Salesforce' AS source_system, 'Account' AS source_table, Id AS source_primary_key,
  Id AS customer_id, Name AS customer_name, BillingCountry AS country, Type AS customer_type, Corvane_Entity__c AS entity_code
FROM ${schema}.bronze_sfdc_account;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_ar_invoice
COMMENT "Customer invoices (Salesforce Billing). is_opening = carried in the GL opening balance."
AS SELECT 'Salesforce' AS source_system, 'blng__Invoice__c' AS source_table, Id AS source_primary_key,
  Id AS ar_invoice_id, Name AS invoice_number, blng__Account__c AS customer_id, Corvane_Entity__c AS entity_code,
  Corvane_Segment__c AS segment_code, CAST(blng__InvoiceDate__c AS DATE) AS invoice_date, CAST(blng__DueDate__c AS DATE) AS due_date,
  CAST(blng__TotalAmount__c AS DECIMAL(18,2)) AS amount, CAST(blng__Balance__c AS DECIMAL(18,2)) AS balance,
  CurrencyIsoCode AS currency_code, CAST(Corvane_Opening_Balance__c AS BOOLEAN) AS is_opening, _source_file
FROM ${schema}.bronze_sfdc_blng__invoice__c;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_ar_payment
COMMENT "Customer receipts (Salesforce Billing). bank_reference is echoed by the bank as EndToEndId."
AS SELECT 'Salesforce' AS source_system, 'blng__Payment__c' AS source_table, Id AS source_primary_key,
  Id AS ar_payment_id, Name AS payment_number, blng__Invoice__c AS ar_invoice_id, blng__Account__c AS customer_id,
  Corvane_Entity__c AS entity_code, CAST(blng__Amount__c AS DECIMAL(18,2)) AS amount,
  CAST(blng__PaymentDate__c AS DATE) AS payment_date, blng__PaymentType__c AS payment_type, CurrencyIsoCode AS currency_code,
  Bank_Reference__c AS bank_reference, _rescued_data, _source_file
FROM ${schema}.bronze_sfdc_blng__payment__c;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_payroll_result
COMMENT "Workday payroll results per worker per run. cost = gross pay + employer taxes (functional currency)."
AS SELECT 'Workday' AS source_system, 'Payroll_Results' AS source_table, Payroll_Result_ID AS source_primary_key,
  Payroll_Result_ID AS payroll_result_id, Payroll_Run_ID AS payroll_run_id, Worker_ID AS worker_id, Company AS entity_code,
  Supervisory_Org AS department, Pay_Group AS pay_group, Run_Type AS run_type, CAST(Payment_Date AS DATE) AS payment_date,
  CAST(Gross_Pay AS DECIMAL(18,2)) AS gross_pay, CAST(Employer_Taxes AS DECIMAL(18,2)) AS employer_taxes,
  CAST(Gross_Pay + Employer_Taxes AS DECIMAL(18,2)) AS payroll_cost, Currency AS currency_code
FROM ${schema}.bronze_workday_payroll_results;

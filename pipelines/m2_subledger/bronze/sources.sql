-- ============================================================================
-- BRONZE (M2): Oracle Payables, Salesforce Billing, Workday payroll
-- ============================================================================
-- Salesforce payments have an explicit contract schema: fields the contract
-- does not know land in _rescued_data (schema drift, control DQ-02) instead of
-- silently widening the table.
-- ============================================================================

CREATE OR REFRESH STREAMING TABLE ${schema}.bronze_oracle_ap_invoices_all
COMMENT "Oracle AP_INVOICES_ALL: supplier invoices (AP subledger). dist_code_combination_id is the expense or asset distribution."
TBLPROPERTIES ('source_system' = 'Oracle Fusion ERP')
AS SELECT *, _metadata.file_path AS _source_file, _metadata.file_modification_time AS _ingested_at
FROM STREAM read_files("/Volumes/${catalog}/${schema}/${raw_volume}/oracle/ap_invoices_all_*.csv",
  format => "csv", header => true, inferColumnTypes => false, rescuedDataColumn => "_rescued_data");

CREATE OR REFRESH STREAMING TABLE ${schema}.bronze_oracle_ap_checks_all
COMMENT "Oracle AP_CHECKS_ALL: supplier payments. check_number is echoed by the bank as EndToEndId."
TBLPROPERTIES ('source_system' = 'Oracle Fusion ERP')
AS SELECT *, _metadata.file_path AS _source_file, _metadata.file_modification_time AS _ingested_at
FROM STREAM read_files("/Volumes/${catalog}/${schema}/${raw_volume}/oracle/ap_checks_all_*.csv",
  format => "csv", header => true, inferColumnTypes => false, rescuedDataColumn => "_rescued_data");

CREATE OR REFRESH STREAMING TABLE ${schema}.bronze_oracle_poz_suppliers
COMMENT "Oracle POZ_SUPPLIERS: supplier master."
TBLPROPERTIES ('source_system' = 'Oracle Fusion ERP')
AS SELECT *, _metadata.file_path AS _source_file, _metadata.file_modification_time AS _ingested_at
FROM STREAM read_files("/Volumes/${catalog}/${schema}/${raw_volume}/oracle/",
  pathGlobFilter => "poz_suppliers.csv", format => "csv", header => true, inferColumnTypes => false, rescuedDataColumn => "_rescued_data");

CREATE OR REFRESH STREAMING TABLE ${schema}.bronze_sfdc_account
COMMENT "Salesforce Account: customers, with the billing entity (Corvane_Entity__c)."
TBLPROPERTIES ('source_system' = 'Salesforce')
AS SELECT *, _metadata.file_path AS _source_file, _metadata.file_modification_time AS _ingested_at
FROM STREAM read_files("/Volumes/${catalog}/${schema}/${raw_volume}/salesforce/",
  pathGlobFilter => "Account.json", format => "json", rescuedDataColumn => "_rescued_data");

CREATE OR REFRESH STREAMING TABLE ${schema}.bronze_sfdc_blng__invoice__c
COMMENT "Salesforce Billing blng__Invoice__c: customer invoices (AR subledger)."
TBLPROPERTIES ('source_system' = 'Salesforce')
AS SELECT *, _metadata.file_path AS _source_file, _metadata.file_modification_time AS _ingested_at
FROM STREAM read_files("/Volumes/${catalog}/${schema}/${raw_volume}/salesforce/blng__Invoice__c_*.json",
  format => "json", rescuedDataColumn => "_rescued_data");

CREATE OR REFRESH STREAMING TABLE ${schema}.bronze_sfdc_blng__payment__c
COMMENT "Salesforce Billing blng__Payment__c: customer receipts. Explicit contract schema: unknown fields go to _rescued_data (DQ-02)."
TBLPROPERTIES ('source_system' = 'Salesforce')
AS SELECT *, _metadata.file_path AS _source_file, _metadata.file_modification_time AS _ingested_at
FROM STREAM read_files("/Volumes/${catalog}/${schema}/${raw_volume}/salesforce/blng__Payment__c_*.json",
  format => "json",
  schema => "Id STRING, Name STRING, blng__Invoice__c STRING, blng__Account__c STRING, blng__Amount__c DOUBLE, blng__PaymentDate__c STRING, blng__PaymentType__c STRING, blng__Status__c STRING, CurrencyIsoCode STRING, Corvane_Entity__c STRING, Bank_Reference__c STRING",
  rescuedDataColumn => "_rescued_data");

CREATE OR REFRESH STREAMING TABLE ${schema}.bronze_workday_payroll_results
COMMENT "Workday payroll results (RaaS): gross pay and employer taxes per worker per pay run."
TBLPROPERTIES ('source_system' = 'Workday')
AS SELECT *, _metadata.file_path AS _source_file, _metadata.file_modification_time AS _ingested_at
FROM STREAM read_files("/Volumes/${catalog}/${schema}/${raw_volume}/workday/payroll_results_*.parquet",
  format => "parquet", rescuedDataColumn => "_rescued_data");

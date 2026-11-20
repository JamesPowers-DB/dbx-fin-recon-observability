"""Runtime settings from environment variables.

Values come from `config.env` in resources/apps.yml (bundle variables are
substituted there) and from app resource bindings (`value_from`). The
Lakebase `postgres` binding injects PGHOST / PGDATABASE / PGUSER / PGPORT /
PGSSLMODE for the app service principal.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Single schema; the layer lives in the table-name prefix at the query site.
    catalog: str = Field(default="main", validation_alias="DATABRICKS_CATALOG")
    schema: str = Field(default="fin_recon_observability", validation_alias="DATABRICKS_SCHEMA")
    raw_volume: str = Field(default="files", validation_alias="DATABRICKS_RAW_VOLUME")
    warehouse_id: str = Field(default="", validation_alias="DATABRICKS_WAREHOUSE_ID")
    databricks_host: str = Field(default="", validation_alias="DATABRICKS_HOST")

    genie_space_id: str = Field(default="", validation_alias="GENIE_SPACE_ID")
    genie_space_title: str = Field(default="Fin Recon Observability - Audit & Controls",
                                   validation_alias="GENIE_SPACE_TITLE")
    serving_endpoint_name: str = Field(default="databricks-claude-sonnet-5-5",
                                       validation_alias="DATABRICKS_SERVING_ENDPOINT_NAME")

    # Jobs the app may trigger with its service principal (CAN_MANAGE_RUN via
    # app resource bindings). Ids arrive through value_from.
    run_controls_job_id: str = Field(default="", validation_alias="RUN_CONTROLS_JOB_ID")
    simulate_job_id: str = Field(default="", validation_alias="SIMULATE_ACTIVITY_JOB_ID")
    refresh_job_id: str = Field(default="", validation_alias="REFRESH_JOB_ID")
    pipeline_id: str = Field(default="", validation_alias="LAKEHOUSE_PIPELINE_ID")
    dashboard_id: str = Field(default="", validation_alias="DASHBOARD_ID")
    bundle_file_path: str = Field(default="", validation_alias="BUNDLE_FILE_PATH")
    triage_endpoint_name: str = Field(default="databricks-claude-haiku-5-5", validation_alias="TRIAGE_ENDPOINT_NAME")

    # Stashed by main.py before the originals are cleared.
    sp_client_id: str = Field(default="", validation_alias="APP_SP_CLIENT_ID")
    sp_client_secret: str = Field(default="", validation_alias="APP_SP_CLIENT_SECRET")

    # Lakebase Autoscaling (bundle-managed project, default database binding).
    pg_host: str = Field(default="", validation_alias="PGHOST")
    pg_port: int = Field(default=5432, validation_alias="PGPORT")
    pg_database: str = Field(default="databricks_postgres", validation_alias="PGDATABASE")
    pg_user: str = Field(default="", validation_alias="PGUSER")
    pg_sslmode: str = Field(default="require", validation_alias="PGSSLMODE")
    lakebase_endpoint: str = Field(default="", validation_alias="LAKEBASE_ENDPOINT")

    dev_allow_anonymous: bool = Field(default=False, validation_alias="APP_DEV_ALLOW_ANONYMOUS")
    dev_user_email: str = Field(default="local-dev@example.com", validation_alias="APP_DEV_USER_EMAIL")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def fq(self) -> str:
        """catalog.schema; append the layer-prefixed table name: f"{s.fq}.gold_mv_close"."""
        return f"`{self.catalog}`.`{self.schema}`"

    @property
    def workspace_url(self) -> str:
        h = self.databricks_host
        if h and not h.startswith("http"):
            h = f"https://{h}"
        return h.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()

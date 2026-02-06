from datetime import timedelta
from typing import Any, Dict, List

import pendulum
from airflow.sdk import DAG, task

from utils.helpers.openmetadata_helpers import OpenMetadataQualityFramework

# --- Global configuration ---
TEAM_NAME = "O&M"
COMMENT_USER = "dataquality_bot"
MENTION_USER = "joannes.terme"

BQ_PROJECT_ID = "warehouse-390509"
BQ_DATASET_ID = "jouleyes"
BQ_LOCATION = "EU"
OMD_SERVICE_NAME = "Warehouse"

MIN_COVERAGE_BOUND = 99
NUM_DAYS_IN_WINDOW = 3

CREATE_BQ_TABLES = True
CREATE_INCIDENTS = True
ADD_COMMENTS = True
ADD_MENTION = True

TRINO_CONN_ID = "trino_lakehouse"
BQ_CONN_ID = "bigquery"
BQ_TEST_CONN_ID = "bigquery_standard"

ASSET_TABLE = "warehouse.jouleyes.jouleyes_public_assets"
ASSET_INFO_TABLE = "warehouse.jouleyes.jouleyes_public_asset_infos"

DEFAULT_BQ_SCHEMA_FIELDS = [
    {"name": "day", "type": "DATE", "mode": "REQUIRED"},
    {"name": "site_id", "type": "STRING", "mode": "REQUIRED"},
    {"name": "data_coverage", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "is_missing", "type": "BOOLEAN", "mode": "REQUIRED"},
]

DEVICE_CONFIG: Dict[str, Dict[str, Any]] = {
    "JBOX1": {
        "source_table": "lakehouse.ems.ems_banktelemetry_bu_battery_unit_id_bbms_bbms_id_vendor_lg_warranty_bank",
        "bq_table_name": "JBOX1_coverage_quality_test",
        "join_key": "nw_asset_id",
        "trino_filter_clause": "controller_id is null",
        "expected_nb_messages": 60 * 60 * 24,
    },
    "JBOX2": {
        "source_table": "lakehouse.ems.ems_telemetryseries_gc",
        "bq_table_name": "JBOX2_coverage_quality_test",
        "join_key": "controller_id",
        "trino_filter_clause": "controller_id is not null",
        "expected_nb_messages": 0.95 * 60 * 60 * 24,
    },
}

TRINO_COVERAGE_SQL_TEMPLATE = """
SELECT
    assets.nw_asset_id,
    coverage.data_coverage
FROM (
    SELECT
        {join_key} AS site_id,
        100 * CAST(COUNT(*) AS DOUBLE) / ({expected_nb_messages}) AS data_coverage
    FROM {source_table}
    WHERE ts >= TIMESTAMP '{start_ts}' AND ts < TIMESTAMP '{end_ts}'
    {filter_predicate}
    GROUP BY {join_key}
) AS coverage
JOIN {asset_table} AS assets
  ON coverage.site_id = assets.{join_key}
WHERE assets.available = TRUE
"""

TRINO_MISSING_SQL_TEMPLATE = """
SELECT assets.nw_asset_id AS site_id
FROM {asset_table} AS assets
JOIN {asset_info_table} AS info
  ON assets.id = info.asset_id
WHERE info.product_type = '{device}'
  AND assets.available = TRUE
  AND assets.{join_key} NOT IN (
      SELECT DISTINCT {join_key}
      FROM {source_table}
      WHERE ts >= TIMESTAMP '{start_ts}' AND ts < TIMESTAMP '{end_ts}'
      {filter_predicate}
  )
"""

SQL_DAILY_COVERAGE = """
SELECT site_id
FROM `{bq_table_fqn}`
WHERE day = '{test_date}'
  AND is_missing = FALSE
  AND data_coverage < {min_coverage}
"""

SQL_DAILY_MISSING = """
SELECT site_id
FROM `{bq_table_fqn}`
WHERE day = '{test_date}'
  AND is_missing = TRUE
"""

SQL_3D_COVERAGE = """
WITH site_history AS (
    SELECT
        site_id,
        COUNT(DISTINCT day) AS days_present,
        COUNTIF(is_missing = FALSE AND data_coverage < {min_coverage}) AS low_coverage_days
    FROM `{bq_table_fqn}`
    WHERE day BETWEEN '{start_date}' AND '{end_date}'
    GROUP BY site_id
)
SELECT site_id
FROM site_history
WHERE days_present = {window_days}
  AND low_coverage_days = {window_days}
"""

SQL_3D_MISSING = """
WITH site_history AS (
    SELECT
        site_id,
        COUNT(DISTINCT day) AS days_present,
        COUNTIF(is_missing = TRUE) AS missing_days
    FROM `{bq_table_fqn}`
    WHERE day BETWEEN '{start_date}' AND '{end_date}'
    GROUP BY site_id
)
SELECT site_id
FROM site_history
WHERE days_present = {window_days}
  AND missing_days = {window_days}
"""


def build_test_cases(device: str, bq_table_fqn: str, omd_table_fqn: str) -> List[Dict[str, Any]]:
    return [
        {
            "test_case_name": f"{device}_daily_coverage",
            "table_fqn": omd_table_fqn,
            "sql_template": SQL_DAILY_COVERAGE,
            "sql_params": {"bq_table_fqn": bq_table_fqn, "min_coverage": MIN_COVERAGE_BOUND},
            "result_value_name": "failed_site_count",
            "failure_message": "Low coverage detected on site IDs:",
        },
        {
            "test_case_name": f"{device}_daily_missing",
            "table_fqn": omd_table_fqn,
            "sql_template": SQL_DAILY_MISSING,
            "sql_params": {"bq_table_fqn": bq_table_fqn},
            "result_value_name": "missing_site_count",
            "failure_message": "Missing data detected on site IDs:",
        },
        {
            "test_case_name": f"{device}_3days_coverage",
            "table_fqn": omd_table_fqn,
            "sql_template": SQL_3D_COVERAGE,
            "sql_params": {"bq_table_fqn": bq_table_fqn, "min_coverage": MIN_COVERAGE_BOUND},
            "window_days": NUM_DAYS_IN_WINDOW,
            "result_value_name": "failed_site_count",
            "failure_message": "Low coverage detected over 3 days on site IDs:",
        },
        {
            "test_case_name": f"{device}_3days_missing",
            "table_fqn": omd_table_fqn,
            "sql_template": SQL_3D_MISSING,
            "sql_params": {"bq_table_fqn": bq_table_fqn},
            "window_days": NUM_DAYS_IN_WINDOW,
            "result_value_name": "missing_site_count",
            "failure_message": "Missing data detected over 3 days on site IDs:",
        },
    ]


with DAG(
    dag_id="sdk_OMD_JBOX_Coverage_and_Missing_Data_Tests",
    description=(
        "Daily and 3-day coverage/missing data tests for JBOX1 & JBOX2. "
        "Incidents are created on first failure then comments are added."
    ),
    schedule="30 1 * * *",
    start_date=pendulum.datetime(2025, 9, 24, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "mael.nedellec",
        "retries": 0,
        "retry_delay": timedelta(minutes=5),
        "retry_exponential_backoff": True,
    },
    tags=["openmetadata", "test-case", "data-quality"],
) as dag:

    @task
    def run_device_quality(device: str, data_interval_start=None):
        dq = OpenMetadataQualityFramework.from_airflow_variables(comment_user=COMMENT_USER)
        try:
            config = DEVICE_CONFIG[device]
            bq_table_name = config["bq_table_name"]
            bq_table_fqn = f"{BQ_PROJECT_ID}.{BQ_DATASET_ID}.{bq_table_name}"
            omd_table_fqn = f"{OMD_SERVICE_NAME}.{BQ_PROJECT_ID}.{BQ_DATASET_ID}.{bq_table_name}"

            dq.ensure_bq_table(
                project_id=BQ_PROJECT_ID,
                dataset_id=BQ_DATASET_ID,
                table_id=bq_table_name,
                schema_fields=DEFAULT_BQ_SCHEMA_FIELDS,
                time_partitioning={"type_": "DAY", "field": "day"},
                create_if_missing=CREATE_BQ_TABLES,
                gcp_conn_id=BQ_CONN_ID,
            )

            dq.load_daily_data_from_trino(
                device=device,
                source_table=config["source_table"],
                join_key=config["join_key"],
                expected_nb_messages=config["expected_nb_messages"],
                asset_table=ASSET_TABLE,
                asset_info_table=ASSET_INFO_TABLE,
                coverage_sql_template=TRINO_COVERAGE_SQL_TEMPLATE,
                missing_sql_template=TRINO_MISSING_SQL_TEMPLATE,
                bq_project_id=BQ_PROJECT_ID,
                bq_dataset_id=BQ_DATASET_ID,
                bq_table_id=bq_table_name,
                bq_conn_id=BQ_CONN_ID,
                trino_conn_id=TRINO_CONN_ID,
                trino_filter_clause=config.get("trino_filter_clause"),
                data_interval_start=data_interval_start,
            )

            tests = build_test_cases(device, bq_table_fqn, omd_table_fqn)
            dq.run_bq_test_cases(
                test_cases=tests,
                data_interval_start=data_interval_start,
                bq_conn_id=BQ_TEST_CONN_ID,
                bq_location=BQ_LOCATION,
                create_incident=CREATE_INCIDENTS,
                incident_owner=TEAM_NAME,
                comment_on_failure=ADD_COMMENTS,
                mention_user=MENTION_USER if ADD_MENTION else None,
            )
        finally:
            dq.close()

    run_device_quality.override(task_id="run_jbox1")(device="JBOX1")
    run_device_quality.override(task_id="run_jbox2")(device="JBOX2")

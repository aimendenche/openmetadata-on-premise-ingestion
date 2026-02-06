import logging
from typing import Any, Dict, List, Literal, Optional, Sequence, Type
from urllib.parse import quote
from uuid import UUID

import pendulum
import requests
from metadata.generated.schema.api.lineage.addLineage import AddLineageRequest
from metadata.generated.schema.entity.data.dashboard import Dashboard
from metadata.generated.schema.entity.data.pipeline import Pipeline
from metadata.generated.schema.entity.data.table import Table
from metadata.generated.schema.entity.data.topic import Topic
from metadata.generated.schema.entity.services.connections.metadata.openMetadataConnection import (
    AuthProvider,
    OpenMetadataConnection,
)
from metadata.generated.schema.entity.services.dashboardService import DashboardService
from metadata.generated.schema.entity.services.databaseService import DatabaseService
from metadata.generated.schema.entity.services.messagingService import MessagingService
from metadata.generated.schema.entity.services.pipelineService import PipelineService
from metadata.generated.schema.security.client.openMetadataJWTClientConfig import (
    OpenMetadataJWTClientConfig,
)
from metadata.generated.schema.tests.basic import (
    TestCaseResult,
    TestCaseStatus,
    TestResultValue,
)
from metadata.generated.schema.tests.testCase import TestCaseParameterValue
from metadata.generated.schema.type.basic import Timestamp, Uuid
from metadata.generated.schema.type.entityLineage import EntitiesEdge, LineageDetails
from metadata.generated.schema.type.entityReference import EntityReference
from metadata.ingestion.ometa.ometa_api import OpenMetadata

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _extract_jwt_token(token: str) -> str:
    raw = (token or "").strip().strip('"').strip("'")
    if raw.lower().startswith("bearer "):
        raw = raw.split(" ", 1)[1].strip()
    if not raw:
        raise ValueError("OpenMetadata auth token is empty")
    return raw


def _normalize_bearer_token(token: str) -> str:
    return f"Bearer {_extract_jwt_token(token)}"


def _sdk_hostport_from_api_v1(api_v1_url: str) -> str:
    base = (api_v1_url or "").rstrip("/")
    if base.endswith("/api/v1"):
        return base[: -len("/v1")]
    if base.endswith("/api"):
        return base
    return f"{base}/api"


def load_omd_config_from_airflow() -> Dict[str, str]:
    try:
        from airflow.sdk import Variable
    except Exception as exc:  # pragma: no cover - Airflow only
        raise RuntimeError("Airflow Variable API is not available") from exc

    try:
        omd_api_url = Variable.get("OMD_API_V1_URL")
        omd_url = Variable.get("OMD_URL")
        jwt_token = Variable.get("Quality_token")
    except KeyError as exc:
        raise RuntimeError(f"Airflow Variable {exc} not set. Configure it in Airflow UI.") from exc

    return {
        "OMD_API_URL": omd_api_url,
        "OMD_URL": omd_url,
        "JWT_TOKEN": jwt_token,
    }


class OpenMetadataHelper:
    def __init__(self, omd_url: str, auth_token: str):
        jwt_raw = _extract_jwt_token(auth_token)

        self.server_config = OpenMetadataConnection(
            type="OpenMetadata",
            hostPort=omd_url,
            authProvider=AuthProvider.openmetadata,
            securityConfig=OpenMetadataJWTClientConfig(jwtToken=jwt_raw),
            verifySSL="no-ssl",
            secretsManagerProvider="db",
        )

        self._auth_token = f"Bearer {jwt_raw}"

        base = omd_url.rstrip("/")
        if base.endswith("/api/v1"):
            self._omd_api_v1 = base
        elif base.endswith("/api"):
            self._omd_api_v1 = f"{base}/v1"
        else:
            self._omd_api_v1 = f"{base}/api/v1"

        try:
            self.metadata = OpenMetadata(self.server_config)
            assert self.metadata.health_check()
        except Exception as exc:
            raise RuntimeError(f"Failed to connect to OpenMetadata: {exc}") from exc

    # -------------------- Internal helpers --------------------

    def _unwrap_name(self, value) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        for attr in ("root", "__root__", "value"):
            if hasattr(value, attr):
                inner = getattr(value, attr)
                if inner is not None:
                    return inner
        return str(value)

    def _get_entity_id_by_fqn(self, entity_class: Type, fqn: str) -> Optional[str]:
        try:
            entity = self.metadata.get_by_name(entity=entity_class, fqn=fqn)
            if entity:
                return str(entity.id.root)
            logger.warning("%s with FQN '%s' not found.", entity_class.__name__, fqn)
            return None
        except Exception as exc:
            logger.error("Error fetching %s with FQN '%s': %s", entity_class.__name__, fqn, exc)
            return None

    def _collect_all_entities(self, entity_class: Type) -> Dict[str, str]:
        entities: Dict[str, str] = {}
        try:
            for p in self.metadata.list_all_entities(entity=entity_class, limit=10000):
                name = self._unwrap_name(getattr(p, "name", None))
                fqn = self._unwrap_name(getattr(p, "fullyQualifiedName", None))
                if name and fqn:
                    entities[name] = fqn
        except Exception as exc:
            logger.error("Failed to retrieve %s via SDK: %s", entity_class.__name__, exc)
        return entities

    # -------------------- Public getters by FQN --------------------

    def get_table_id_by_fqn(self, fqn: str) -> Optional[str]:
        return self._get_entity_id_by_fqn(Table, fqn)

    def get_pipeline_id_by_fqn(self, fqn: str) -> Optional[str]:
        return self._get_entity_id_by_fqn(Pipeline, fqn)

    def get_topic_id_by_fqn(self, fqn: str) -> Optional[str]:
        return self._get_entity_id_by_fqn(Topic, fqn)

    def get_dashboard_id_by_fqn(self, fqn: str) -> Optional[str]:
        return self._get_entity_id_by_fqn(Dashboard, fqn)

    def collect_all_pipelines(self) -> Dict[str, str]:
        return self._collect_all_entities(Pipeline)

    def collect_all_tables(self) -> Dict[str, str]:
        return self._collect_all_entities(Table)

    def collect_all_topics(self) -> Dict[str, str]:
        return self._collect_all_entities(Topic)

    # -------------------- Service discovery --------------------

    def get_service_fqn(self, service_type: str) -> Optional[str]:
        service_class_map = {
            "messaging": MessagingService,
            "database": DatabaseService,
            "pipeline": PipelineService,
            "dashboard": DashboardService,
        }

        desired_engine_by_type: Dict[str, str] = {
            "messaging": "Kafka",
            "database": "Trino",
        }

        service_cls = service_class_map.get(service_type)
        if not service_cls:
            logger.error("Unsupported service_type '%s'", service_type)
            return None

        try:
            resp = self.metadata.list_entities(entity=service_cls, limit=100)
            services = resp.entities or []
            if not services:
                logger.warning("No services of type '%s' found", service_type)
                return None

            desired_engine = desired_engine_by_type.get(service_type)

            selected = None
            if desired_engine:
                for svc in services:
                    st = getattr(svc, "serviceType", None)
                    if st is None:
                        continue
                    st_val = getattr(st, "value", str(st))
                    if st_val == desired_engine:
                        selected = svc
                        break

            if selected is None:
                selected = services[0]

            fqn = self._unwrap_name(getattr(selected, "fullyQualifiedName", None)) or self._unwrap_name(
                getattr(selected, "name", None)
            )
            logger.info("Using %s service FQN: %s", service_type, fqn)
            return fqn

        except Exception as exc:
            logger.error("Error retrieving %s services: %s", service_type, exc)
            return None

    # -------------------- Pipelines mapping --------------------

    def map_pipeline_name_to_fqn(self, limit: int = 1000) -> Dict[str, str]:
        try:
            resp = self.metadata.list_entities(entity=Pipeline, limit=limit)
            pipelines = resp.entities or []

            mapping: Dict[str, str] = {}
            for p in pipelines:
                name = self._unwrap_name(p.name)
                fqn = self._unwrap_name(p.fullyQualifiedName)
                if name and fqn:
                    mapping[name] = fqn

            logger.info("Built pipeline name -> FQN map with %s entries", len(mapping))
            return mapping
        except Exception as exc:
            logger.error("Error mapping pipelines: %s", exc)
            return {}

    # -------------------- Lineage creation --------------------

    def add_lineage_by_fqn(
        self,
        from_fqn: str,
        to_fqn: str,
        from_entity_type: Literal["table", "topic", "pipeline", "dashboard"],
        to_entity_type: Literal["table", "topic", "pipeline", "dashboard"],
        pipeline_fqn: Optional[str] = None,
        dry_run: bool = False,
    ) -> bool:
        entity_type_map = {
            "table": Table,
            "topic": Topic,
            "pipeline": Pipeline,
            "dashboard": Dashboard,
        }

        from_entity = self._get_entity_id_by_fqn(entity_type_map[from_entity_type], from_fqn)
        to_entity = self._get_entity_id_by_fqn(entity_type_map[to_entity_type], to_fqn)

        if not from_entity or not to_entity:
            logger.error(
                "Could not add lineage %s -> %s: one or both entities not found.",
                from_fqn,
                to_fqn,
            )
            return False

        pipeline_ref = None
        if pipeline_fqn:
            try:
                pipeline_entity = self.metadata.get_by_name(entity_type_map["pipeline"], pipeline_fqn)
                if pipeline_entity:
                    pipeline_ref = EntityReference(
                        id=pipeline_entity.id.root,
                        type="pipeline",
                        name=None,
                        fullyQualifiedName=None,
                        description=None,
                        displayName=None,
                        deleted=None,
                        inherited=None,
                        href=None,
                    )
            except Exception as exc:
                logger.error("Error resolving pipeline '%s' for lineage: %s", pipeline_fqn, exc)

        try:
            if dry_run:
                logger.info("Dry run: would create lineage from '%s' to '%s'", from_fqn, to_fqn)
            else:
                from_entity_ref = EntityReference(
                    id=Uuid(root=UUID(from_entity)),
                    type=from_entity_type,
                    name=None,
                    fullyQualifiedName=None,
                    description=None,
                    displayName=None,
                    deleted=None,
                    inherited=None,
                    href=None,
                )
                to_entity_ref = EntityReference(
                    id=Uuid(root=UUID(to_entity)),
                    type=to_entity_type,
                    name=None,
                    fullyQualifiedName=None,
                    description=None,
                    displayName=None,
                    deleted=None,
                    inherited=None,
                    href=None,
                )
                lineage_request = AddLineageRequest(
                    edge=EntitiesEdge(
                        fromEntity=from_entity_ref,
                        toEntity=to_entity_ref,
                        lineageDetails=LineageDetails(
                            pipeline=pipeline_ref,
                            sqlQuery=None,
                            columnsLineage=None,
                            description=None,
                            source=None,
                            createdAt=None,
                            createdBy=None,
                            updatedAt=None,
                            updatedBy=None,
                            assetEdges=None,
                        ),
                    )
                )
                self.metadata.add_lineage(lineage_request)

            logger.info("Lineage created: %s -> %s", from_fqn, to_fqn)
            return True
        except Exception as exc:
            logger.error("Error creating lineage %s -> %s: %s", from_fqn, to_fqn, exc)
            return False

    # -------------------- Data Quality --------------------

    def ensure_executable_test_suite(self, table_fqn: str) -> str:
        """
        Ensure an executable TestSuite exists for the given table and return its FQN.
        """
        suite = self.metadata.get_or_create_executable_test_suite(table_fqn)
        suite_fqn = self._unwrap_name(getattr(suite, "fullyQualifiedName", None)) or self._unwrap_name(
            getattr(suite, "name", None)
        )
        if not suite_fqn:
            raise RuntimeError(f"Could not resolve executable TestSuite FQN for {table_fqn}")
        return suite_fqn

    def create_table_custom_sql_test_case(
        self,
        table_fqn: str,
        test_case_name: str,
        sql_expression: str,
        strategy: Literal["ROWS", "COUNT"] = "ROWS",
        threshold: int = 0,
    ) -> str:
        """
        Table-level Custom SQL test case using SDK only.
        """
        if not table_fqn or not test_case_name:
            raise ValueError("table_fqn and test_case_name are required.")
        if not sql_expression.strip():
            raise ValueError("sql_expression must not be empty.")

        self.ensure_executable_test_suite(table_fqn)

        test_case_fqn = f"{table_fqn}.{test_case_name}"
        entity_link = f"<#E::table::{table_fqn}>"

        params = [
            TestCaseParameterValue(name="sqlExpression", value=sql_expression),
            TestCaseParameterValue(name="strategy", value=strategy),
            TestCaseParameterValue(name="threshold", value=str(int(threshold))),
        ]

        self.metadata.get_or_create_test_case(
            test_case_fqn=test_case_fqn,
            entity_link=entity_link,
            test_definition_fqn="tableCustomSQLQuery",
            test_case_parameter_values=params,
        )

        logger.info("TestCase ensured: %s", test_case_fqn)
        return test_case_fqn

    def create_column_custom_sql_test_case(
        self,
        table_fqn: str,
        column: str,
        test_case_name: str,
        sql_expression: str,
        strategy: Literal["ROWS", "COUNT"] = "ROWS",
        threshold: int = 0,
    ) -> str:
        """
        Column-level Custom SQL test case using SDK only.
        """
        if not table_fqn or not column or not test_case_name:
            raise ValueError("table_fqn, column and test_case_name are required.")
        if not sql_expression.strip():
            raise ValueError("sql_expression must not be empty.")
        if strategy not in ("ROWS", "COUNT"):
            raise ValueError("strategy must be either 'ROWS' or 'COUNT'.")

        self.ensure_executable_test_suite(table_fqn)

        test_case_fqn = f"{table_fqn}.{column}.{test_case_name}"
        entity_link = f"<#E::table::{table_fqn}::columns::{column}>"

        params = [
            TestCaseParameterValue(name="sqlExpression", value=sql_expression),
            TestCaseParameterValue(name="strategy", value=strategy),
            TestCaseParameterValue(name="threshold", value=str(int(threshold))),
        ]

        self.metadata.get_or_create_test_case(
            test_case_fqn=test_case_fqn,
            entity_link=entity_link,
            test_definition_fqn="columnCustomSQLQuery",
            test_case_parameter_values=params,
        )

        logger.info("TestCase ensured: %s", test_case_fqn)
        return test_case_fqn

    # -------------------- Data Quality: results + optional comment --------------------

    def add_test_case_result(
        self,
        test_case_fqn: str,
        status: Literal["Success", "Failed"],
        timestamp_ms: int,
        values: Dict[str, str],
        result: Optional[str] = None,
    ) -> None:
        """
        Push a TestCaseResult using the OpenMetadata SDK.
        """
        test_status = TestCaseStatus.Success if status == "Success" else TestCaseStatus.Failed
        test_result_values = [TestResultValue(name=k, value=str(v), predictedValue=None) for k, v in values.items()]

        payload = TestCaseResult(
            timestamp=Timestamp(root=timestamp_ms),
            testCaseStatus=test_status,
            result=result or "",
            testResultValue=test_result_values,
            id=None,
            testCaseFQN=None,
            sampleData=None,
            passedRows=None,
            failedRows=None,
            passedRowsPercentage=None,
            failedRowsPercentage=None,
            incidentId=None,
            maxBound=None,
            minBound=None,
            testCase=None,
            testDefinition=None,
            dimensionResults=None,
        )

        try:
            self.metadata.add_test_case_results(test_results=payload, test_case_fqn=test_case_fqn)
            logger.info("TestCaseResult pushed for %s", test_case_fqn)
        except Exception as exc:
            msg = str(exc).lower()
            if "409" in msg or "already exists" in msg or "conflict" in msg:
                logger.info(
                    "TestCaseResult already exists for %s at %s",
                    test_case_fqn,
                    timestamp_ms,
                )
                return
            raise

    def comment_on_test_case(
        self,
        test_case_fqn: str,
        message_html: str,
        author: str = "dataquality_bot",
    ) -> None:
        """
        Add a comment to the TestCase feed thread (REST for feed).
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": self._auth_token,
        }
        entity_link = quote(f"<#E::testCase::{test_case_fqn}>", safe="")

        r = requests.get(
            f"{self._omd_api_v1}/feed?entityLink={entity_link}",
            headers=headers,
            timeout=30,
        )
        r.raise_for_status()
        threads = (r.json() or {}).get("data", []) or []

        if threads:
            thread_id = threads[-1]["id"]
            rp = requests.post(
                f"{self._omd_api_v1}/feed/{thread_id}/posts",
                json={"from": author, "message": message_html},
                headers=headers,
                timeout=30,
            )
            rp.raise_for_status()
            logger.info("Comment added on TestCase %s", test_case_fqn)
            return

        rc = requests.post(
            f"{self._omd_api_v1}/feed",
            json={
                "from": author,
                "message": message_html,
                "about": f"<#E::testCase::{test_case_fqn}>",
            },
            headers=headers,
            timeout=30,
        )
        rc.raise_for_status()
        logger.info("Thread created and comment added for TestCase %s", test_case_fqn)

    def close(self):
        self.metadata.close()
        logger.info("OpenMetadata connection closed.")


class OpenMetadataQualityFramework:
    def __init__(
        self,
        omd_api_url: str,
        omd_url: str,
        jwt_token: str,
        comment_user: str = "dataquality_bot",
    ):
        self._omd_api_url = omd_api_url
        self._omd_url = omd_url
        self._comment_user = comment_user
        self._headers = {
            "Content-Type": "application/json",
            "Authorization": _normalize_bearer_token(jwt_token),
        }
        self._omd = OpenMetadataHelper(
            omd_url=_sdk_hostport_from_api_v1(omd_api_url),
            auth_token=jwt_token,
        )

    @classmethod
    def from_airflow_variables(cls, comment_user: str = "dataquality_bot") -> "OpenMetadataQualityFramework":
        config = load_omd_config_from_airflow()
        return cls(
            omd_api_url=config["OMD_API_URL"],
            omd_url=config["OMD_URL"],
            jwt_token=config["JWT_TOKEN"],
            comment_user=comment_user,
        )

    def close(self) -> None:
        self._omd.close()

    # -------------------- BigQuery helpers --------------------

    def ensure_bq_table(
        self,
        project_id: str,
        dataset_id: str,
        table_id: str,
        schema_fields: Sequence[Dict[str, Any]],
        time_partitioning: Optional[Dict[str, Any]] = None,
        create_if_missing: bool = True,
        gcp_conn_id: str = "bigquery",
    ) -> None:
        if not create_if_missing:
            return

        try:
            from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook
        except Exception as exc:  # pragma: no cover - Airflow only
            raise RuntimeError("BigQueryHook is not available") from exc

        bq_hook = BigQueryHook(gcp_conn_id=gcp_conn_id)
        client = bq_hook.get_client()
        table_fqn = f"{project_id}.{dataset_id}.{table_id}"
        try:
            client.get_table(table_fqn)
            logger.info("BQ table exists: %s", table_fqn)
        except Exception as exc:
            if "Not found" in str(exc):
                logger.info("BQ table missing, creating: %s", table_fqn)
                bq_hook.create_empty_table(
                    project_id=project_id,
                    dataset_id=dataset_id,
                    table_id=table_id,
                    schema_fields=list(schema_fields),
                    time_partitioning=time_partitioning,
                )
                logger.info("BQ table created: %s", table_fqn)
            else:
                raise

    def load_daily_data_from_trino(
        self,
        device: str,
        source_table: str,
        join_key: str,
        expected_nb_messages: float,
        asset_table: str,
        asset_info_table: str,
        coverage_sql_template: str,
        missing_sql_template: str,
        bq_project_id: str,
        bq_dataset_id: str,
        bq_table_id: str,
        bq_conn_id: str = "bigquery",
        trino_conn_id: str = "trino_lakehouse",
        trino_filter_clause: Optional[str] = None,
        data_interval_start: Optional[pendulum.DateTime] = None,
    ) -> List[Dict[str, Any]]:
        try:
            from airflow.providers.trino.hooks.trino import TrinoHook
            from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook
        except Exception as exc:  # pragma: no cover - Airflow only
            raise RuntimeError("TrinoHook or BigQueryHook is not available") from exc

        interval_end = pendulum.instance(data_interval_start or pendulum.now("UTC"))
        interval_start = interval_end.subtract(days=1)
        filter_predicate = f"AND {trino_filter_clause}" if trino_filter_clause else ""

        coverage_sql = coverage_sql_template.format(
            device=device,
            source_table=source_table,
            join_key=join_key,
            expected_nb_messages=expected_nb_messages,
            start_ts=interval_start.to_datetime_string(),
            end_ts=interval_end.to_datetime_string(),
            asset_table=asset_table,
            asset_info_table=asset_info_table,
            filter_predicate=filter_predicate,
        )
        missing_sql = missing_sql_template.format(
            device=device,
            source_table=source_table,
            join_key=join_key,
            expected_nb_messages=expected_nb_messages,
            start_ts=interval_start.to_datetime_string(),
            end_ts=interval_end.to_datetime_string(),
            asset_table=asset_table,
            asset_info_table=asset_info_table,
            filter_predicate=filter_predicate,
        )

        trino = TrinoHook(trino_conn_id=trino_conn_id)
        coverage_records = trino.get_records(coverage_sql)
        coverage_data = {
            row[0]: {
                "site_id": row[0],
                "data_coverage": round(float(row[1]), 2),
                "is_missing": False,
            }
            for row in coverage_records
        }
        missing_records = trino.get_records(missing_sql)
        missing_data = {
            row[0]: {"site_id": row[0], "data_coverage": 0.0, "is_missing": True} for row in missing_records
        }

        combined_data = {**coverage_data, **missing_data}
        rows = list(combined_data.values())
        if not rows:
            logger.info("No daily data to insert for %s", device)
            return []

        day = interval_start.to_date_string()
        for row in rows:
            row["day"] = day

        bq_hook = BigQueryHook(gcp_conn_id=bq_conn_id)
        bq_hook.insert_all(
            project_id=bq_project_id,
            dataset_id=bq_dataset_id,
            table_id=bq_table_id,
            rows=rows,
        )
        logger.info(
            "Inserted %s rows into %s.%s.%s for day %s",
            len(rows),
            bq_project_id,
            bq_dataset_id,
            bq_table_id,
            day,
        )
        return rows

    # -------------------- OMD incident + comment helpers --------------------

    def _get_team_reference(self, team_name: str) -> Dict[str, str]:
        r = requests.get(
            f"{self._omd_api_url}/teams/name/{team_name}",
            headers=self._headers,
            timeout=30,
        )
        r.raise_for_status()
        team = r.json()
        return {
            "id": team["id"],
            "type": "team",
            "name": team["name"],
            "displayName": team["displayName"],
        }

    def _incident_exists(self, test_case_fqn: str) -> bool:
        encoded = quote(f"<#E::testCase::{test_case_fqn}>", safe="")
        thread_url = f"{self._omd_api_url}/feed?entityLink={encoded}"
        r = requests.get(thread_url, headers=self._headers, timeout=30)
        r.raise_for_status()
        threads = r.json().get("data", []) or []

        for th in reversed(threads):
            task = th.get("task") or th.get("taskDetails") or {}
            task_type = (task.get("type") or task.get("taskType") or "").lower()
            status = (task.get("status") or task.get("taskStatus") or "").lower()
            closed_at = task.get("closedAt")
            if "requesttestcasefailureresolution" in task_type and status in ("", "open") and closed_at in (
                None,
                0,
            ):
                return True
        return False

    def _create_and_assign_incident(self, test_case_fqn: str, assigned_team: str) -> None:
        team_ref = self._get_team_reference(assigned_team)
        assign_url = f"{self._omd_api_url}/dataQuality/testCases/testCaseIncidentStatus"
        assign_payload = {
            "severity": "Severity1",
            "testCaseReference": test_case_fqn,
            "testCaseResolutionStatusDetails": {"assignee": team_ref},
            "testCaseResolutionStatusType": "Assigned",
        }
        resp = requests.post(assign_url, json=assign_payload, headers=self._headers, timeout=30)
        if resp.status_code in (200, 201):
            logger.info("Incident assigned for %s", test_case_fqn)
            return
        if resp.status_code in (400, 409):
            logger.info("Incident already assigned for %s", test_case_fqn)
            return
        resp.raise_for_status()

    def _build_mention(self, username: Optional[str]) -> str:
        if not username:
            return ""
        return (
            f'<a href="{self._omd_url}/users/{username}" '
            f'data-type="mention" data-entityType="user" '
            f'data-fqn="{username}" data-label="{username}">@{username}</a>'
        )

    def _comment_on_thread(self, test_case_fqn: str, message_html: str) -> None:
        encoded_entity_link = quote(f"<#E::testCase::{test_case_fqn}>", safe="")
        thread_url = f"{self._omd_api_url}/feed?entityLink={encoded_entity_link}"
        r = requests.get(thread_url, headers=self._headers, timeout=30)
        r.raise_for_status()
        threads = r.json().get("data", []) or []

        target_id = None
        if threads:
            for th in reversed(threads):
                task = th.get("task") or th.get("taskDetails") or {}
                task_type = (task.get("type") or task.get("taskType") or "").lower()
                status = (task.get("status") or task.get("taskStatus") or "").lower()
                closed_at = task.get("closedAt")
                if "requesttestcasefailureresolution" in task_type and status in ("", "open") and closed_at in (
                    None,
                    0,
                ):
                    target_id = th["id"]
                    break

            if not target_id:
                target_id = threads[-1]["id"]

        if target_id:
            comment_url = f"{self._omd_api_url}/feed/{target_id}/posts"
            payload_comment = {"from": self._comment_user, "message": message_html}
            resp = requests.post(comment_url, json=payload_comment, headers=self._headers, timeout=30)
            resp.raise_for_status()
            logger.info("Comment added to thread %s for %s", target_id, test_case_fqn)
            return

        create_thread_url = f"{self._omd_api_url}/feed"
        payload_thread = {
            "from": self._comment_user,
            "message": message_html,
            "about": f"<#E::testCase::{test_case_fqn}>",
        }
        resp = requests.post(create_thread_url, json=payload_thread, headers=self._headers, timeout=30)
        resp.raise_for_status()
        logger.info("Thread created and comment added for %s", test_case_fqn)

    # -------------------- Test execution --------------------

    def _result_timestamp_ms(self, data_interval_start: Optional[pendulum.DateTime]) -> int:
        base = pendulum.instance(data_interval_start or pendulum.now("UTC"))
        ts = base.subtract(days=1).replace(hour=12, minute=0, second=0, microsecond=0)
        return int(ts.timestamp() * 1000)

    def _render_sql(
        self,
        sql_template: str,
        data_interval_start: Optional[pendulum.DateTime],
        sql_params: Optional[Dict[str, Any]] = None,
        window_days: Optional[int] = None,
    ) -> str:
        base = pendulum.instance(data_interval_start or pendulum.now("UTC"))
        end_date = base.subtract(days=1)
        window = window_days or 1
        start_date = end_date.subtract(days=window - 1)
        context = {
            "test_date": end_date.to_date_string(),
            "start_date": start_date.to_date_string(),
            "end_date": end_date.to_date_string(),
            "window_days": window,
        }
        if sql_params:
            context.update(sql_params)
        return sql_template.format(**context).strip()

    def _build_comment_message(
        self,
        failed_entities: Sequence[str],
        failure_message: str,
        success_message: str,
        data_interval_start: Optional[pendulum.DateTime],
        mention_user: Optional[str],
    ) -> str:
        mention = self._build_mention(mention_user)
        mention_prefix = f"{mention} - " if mention else ""
        test_date = pendulum.instance(data_interval_start or pendulum.now("UTC")).subtract(days=1).to_date_string()
        if failed_entities:
            site_list = "<br>".join(f"- {site}" for site in failed_entities)
            return (
                f"[Validation date] : {test_date}<br>"
                f"{mention_prefix}{failure_message}<br>{site_list}</p>"
            )
        return f"[Validation date] : {test_date}<br>{mention_prefix}{success_message}</p>"

    def run_bq_test_case(
        self,
        test_case_name: str,
        table_fqn: str,
        sql_template: str,
        sql_params: Optional[Dict[str, Any]] = None,
        data_interval_start: Optional[pendulum.DateTime] = None,
        window_days: Optional[int] = None,
        bq_conn_id: str = "bigquery_standard",
        bq_location: Optional[str] = None,
        result_value_name: str = "failed_count",
        failure_message: str = "Issues detected on entity IDs:",
        success_message: str = "No issues detected.",
        create_incident: bool = True,
        incident_owner: Optional[str] = None,
        comment_on_failure: bool = True,
        comment_on_success: bool = False,
        mention_user: Optional[str] = None,
        unique_entities: bool = True,
    ) -> None:
        try:
            from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook
        except Exception as exc:  # pragma: no cover - Airflow only
            raise RuntimeError("BigQueryHook is not available") from exc

        sql = self._render_sql(sql_template, data_interval_start, sql_params, window_days)
        bq_hook = BigQueryHook(gcp_conn_id=bq_conn_id, location=bq_location, use_legacy_sql=False)
        results = bq_hook.get_records(sql=sql)
        failed_entities = [str(row[0]) for row in results] if results else []
        if unique_entities:
            failed_entities = sorted(set(failed_entities))
        failed_count = len(failed_entities)
        status = "Failed" if failed_count > 0 else "Success"

        test_case_fqn = f"{table_fqn}.{test_case_name}"
        timestamp_ms = self._result_timestamp_ms(data_interval_start)
        values = {result_value_name: str(failed_count)}

        self._omd.ensure_executable_test_suite(table_fqn)
        self._omd.create_table_custom_sql_test_case(
            table_fqn=table_fqn,
            test_case_name=test_case_name,
            sql_expression=sql,
            strategy="COUNT",
            threshold=0,
        )
        self._omd.add_test_case_result(
            test_case_fqn=test_case_fqn,
            status=status,
            timestamp_ms=timestamp_ms,
            values=values,
            result=test_case_name,
        )

        if status == "Failed" and create_incident and incident_owner:
            if not self._incident_exists(test_case_fqn):
                self._create_and_assign_incident(test_case_fqn, incident_owner)

        should_comment = (status == "Failed" and comment_on_failure) or (status == "Success" and comment_on_success)
        if should_comment:
            message_html = self._build_comment_message(
                failed_entities=failed_entities,
                failure_message=failure_message,
                success_message=success_message,
                data_interval_start=data_interval_start,
                mention_user=mention_user,
            )
            self._comment_on_thread(test_case_fqn, message_html)

    def run_bq_test_cases(
        self,
        test_cases: Sequence[Dict[str, Any]],
        data_interval_start: Optional[pendulum.DateTime] = None,
        bq_conn_id: str = "bigquery_standard",
        bq_location: Optional[str] = None,
        create_incident: bool = True,
        incident_owner: Optional[str] = None,
        comment_on_failure: bool = True,
        comment_on_success: bool = False,
        mention_user: Optional[str] = None,
    ) -> None:
        for test in test_cases:
            self.run_bq_test_case(
                test_case_name=test["test_case_name"],
                table_fqn=test["table_fqn"],
                sql_template=test["sql_template"],
                sql_params=test.get("sql_params"),
                data_interval_start=data_interval_start,
                window_days=test.get("window_days"),
                bq_conn_id=test.get("bq_conn_id", bq_conn_id),
                bq_location=test.get("bq_location", bq_location),
                result_value_name=test.get("result_value_name", "failed_count"),
                failure_message=test.get("failure_message", "Issues detected on entity IDs:"),
                success_message=test.get("success_message", "No issues detected."),
                create_incident=test.get("create_incident", create_incident),
                incident_owner=test.get("incident_owner", incident_owner),
                comment_on_failure=test.get("comment_on_failure", comment_on_failure),
                comment_on_success=test.get("comment_on_success", comment_on_success),
                mention_user=test.get("mention_user", mention_user),
                unique_entities=test.get("unique_entities", True),
            )

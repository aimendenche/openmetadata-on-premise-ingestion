import yaml
from metadata.workflow.metadata import MetadataWorkflow
from metadata.workflow.workflow_output_handler import print_status

# Hive YAML configuration as a multi-line string
HIVE_CONFIG = """
source:
  type: hive
  serviceName: local_hive
  serviceConnection:
    config:
      type: Hive
      username: 
      password: 
      hostPort: 192.168.0.18:10000
  sourceConfig:
    config:
      type: DatabaseMetadata
      markDeletedTables: true
      includeTables: true
      includeViews: true
sink:
  type: metadata-rest
  config: {}
workflowConfig:
  loggerLevel: INFO
  openMetadataServerConfig:
    hostPort: "http://localhost:8585/api"
    authProvider: openmetadata
    securityConfig:
      jwtToken: "eyJraWQiOiJHYjM4OWEtOWY3Ni1nZGpzLWE5MmotMDI0MmJrOTQzNTYiLCJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJvcGVuLW1ldGFkYXRhLm9yZyIsInN1YiI6IkRhdGFJbnNpZ2h0c0FwcGxpY2F0aW9uQm90IiwiZW1haWwiOiJEYXRhSW5zaWdodHNBcHBsaWNhdGlvbkJvdEBvcGVubWV0YWRhdGEub3JnIiwiaXNCb3QiOnRydWUsInRva2VuVHlwZSI6IkJPVCIsImlhdCI6MTcwMDU4MzMxMiwiZXhwIjpudWxsfQ.1OK5ULxaOAWZOSmggqARNtoT6WcbWQ39IUjnSN_jf_b4DBF2DOUeDeAjbk9mGKSna_JVyLxgJY9PF8FC8tGcEGDr-daNXiy1NwFZK_iAOkRAiT2SwIBcIzLsgyBN9OyRpo2DyaGbkh1VYWQLh3xdi6tZg8tPX33o_9VRsZDRpD-AHd0IWKmIe-CFbazKIGqlT56ZWUQn6-OHukk-j94pyUE4-U5KgE2U0WhItubMrETsGEumEElUzDZGKV_FK0-e94qib2Oc_SCNTCCLNaLkyWIn-y0EAIUL_T-4P6-oOZ1KCu2pfZtSfQpFkbpFrW_yGiys5YKpADp2gjfZrROgZA"

"""


def run():
    workflow_config = yaml.safe_load(HIVE_CONFIG)
    workflow = MetadataWorkflow.create(workflow_config)
    workflow.execute()
    workflow.raise_from_status()
    print_status(workflow)
    workflow.stop()


if __name__ == "__main__":
    run()
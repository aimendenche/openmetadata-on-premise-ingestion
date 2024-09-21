import yaml
from metadata.workflow.metadata import MetadataWorkflow
from metadata.workflow.workflow_output_handler import print_status

CONFIG = """
source:
  type: postgres
  serviceName: local_postgres
  serviceConnection:
    config:
      type: Postgres
      username: postgres
      authType: 
        password: postgres
      database: postgres
      ingestAllDatabases: true
      # connectionOptions:
      #   key: value      hostPort: 192.168.0.18:5432
      # connectionArguments:
      #   key: value
  sourceConfig:
    config:
      type: DatabaseMetadata
      markDeletedTables: true
      includeTables: true
      includeViews: true
      # includeTags: true
      # databaseFilterPattern:
      #   includes:
      #     - database1
      #     - database2
      #   excludes:
      #     - database3
      #     - database4
      # schemaFilterPattern:
      #   includes:
      #     - schema1
      #     - schema2
      #   excludes:
      #     - schema3
      #     - schema4
      # tableFilterPattern:
      #   includes:
      #     - users
      #     - type_test
      #   excludes:
      #     - table3
      #     - table4
sink:
  type: metadata-rest
  config: {}
workflowConfig:
  loggerLevel: INFO  # DEBUG, INFO, WARNING or ERROR
  openMetadataServerConfig:
    hostPort: "http://localhost:8585/api"
    authProvider: openmetadata
    securityConfig:
      jwtToken: "eyJraWQiOiJHYjM4OWEtOWY3Ni1nZGpzLWE5MmotMDI0MmJrOTQzNTYiLCJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJvcGVuLW1ldGFkYXRhLm9yZyIsInN1YiI6IkRhdGFJbnNpZ2h0c0FwcGxpY2F0aW9uQm90IiwiZW1haWwiOiJEYXRhSW5zaWdodHNBcHBsaWNhdGlvbkJvdEBvcGVubWV0YWRhdGEub3JnIiwiaXNCb3QiOnRydWUsInRva2VuVHlwZSI6IkJPVCIsImlhdCI6MTcwMDU4MzMxMiwiZXhwIjpudWxsfQ.1OK5ULxaOAWZOSmggqARNtoT6WcbWQ39IUjnSN_jf_b4DBF2DOUeDeAjbk9mGKSna_JVyLxgJY9PF8FC8tGcEGDr-daNXiy1NwFZK_iAOkRAiT2SwIBcIzLsgyBN9OyRpo2DyaGbkh1VYWQLh3xdi6tZg8tPX33o_9VRsZDRpD-AHd0IWKmIe-CFbazKIGqlT56ZWUQn6-OHukk-j94pyUE4-U5KgE2U0WhItubMrETsGEumEElUzDZGKV_FK0-e94qib2Oc_SCNTCCLNaLkyWIn-y0EAIUL_T-4P6-oOZ1KCu2pfZtSfQpFkbpFrW_yGiys5YKpADp2gjfZrROgZA"
    ## If SSL, fill the following
    # verifySSL: validate  # or ignore
    # sslConfig:
    #   certificatePath: /local/path/to/certificate

"""

def run():
    workflow_config = yaml.safe_load(CONFIG)
    workflow = MetadataWorkflow.create(workflow_config)
    workflow.execute()
    workflow.raise_from_status()
    print_status(workflow)
    workflow.stop()


if __name__ == "__main__":
  run()

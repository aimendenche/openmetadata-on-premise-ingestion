from metadata.generated.schema.entity.services.connections.database.postgresConnection import PostgresConnection
# Corrected import statement for BasicAuth
from metadata.generated.schema.entity.services.connections.database.common.basicAuth import BasicAuth
from metadata.ingestion.ometa.ometa_api import OpenMetadata
from metadata.generated.schema.entity.services.connections.metadata.openMetadataConnection import OpenMetadataConnection, AuthProvider
from metadata.generated.schema.security.client.openMetadataJWTClientConfig import OpenMetadataJWTClientConfig

# Configuring the OpenMetadata connection
server_config = OpenMetadataConnection(
    hostPort="http://localhost:8585/api",
    authProvider=AuthProvider.openmetadata,
    securityConfig=OpenMetadataJWTClientConfig(
        jwtToken="eyJraWQiOiJHYjM4OWEtOWY3Ni1nZGpzLWE5MmotMDI0MmJrOTQzNTYiLCJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJvcGVuLW1ldGFkYXRhLm9yZyIsInN1YiI6ImluZ2VzdGlvbi1ib3QiLCJlbWFpbCI6ImluZ2VzdGlvbi1ib3RAb3Blbm1ldGFkYXRhLm9yZyIsImlzQm90Ijp0cnVlLCJ0b2tlblR5cGUiOiJCT1QiLCJpYXQiOjE3MDA1ODMzMTEsImV4cCI6bnVsbH0.p56A4--Ec702OiCYW65T0Dk4OK5mas0GQXW2c_8G-vMSyVJScQPxXPWwvtFoxg7POg6uUmkiMaHhaMZYGau_KH7jbO51VzXKrnibPnE8yDu0oj7jqxjicX5-0R6lsSyvy5qZnyG1Nu6lUa--giy7n7iwJSqWr1LDdxzZTh9XuMYKBlzhFEgfE8gzb_aEzYj9Sf3d3kQ_mI9GaTWJFQQ1QntE8lytsKlzds8D9VN8PWmId9hRFdWAKp_zmyXIazo89MSvMxVJxpYFXuTauBTQaSKIX6QzsmovSmocpQ8NqsqUi1V2TvOH8q_HtVck_VefwvCBZELJ8WWSYQVy4Fvu3A",  # Replace with your actual JWT token
    ),
)

metadata = OpenMetadata(server_config)

from metadata.generated.schema.api.services.createDatabaseService import CreateDatabaseServiceRequest
from metadata.generated.schema.entity.services.databaseService import DatabaseService, DatabaseServiceType, DatabaseConnection

basic_auth = BasicAuth(

    password="lineage2024",  # Password for PostgreSQL
)

# Creating database service
create_service = CreateDatabaseServiceRequest(
    name="local-postgres-service",
    serviceType=DatabaseServiceType.Postgres,
    connection=DatabaseConnection(
        config=PostgresConnection(
            username="postgres",  # Username for PostgreSQL
            hostPort="192.168.0.18:5432",  # Host and port
            database="postgres",  # The specific database name
            authType=basic_auth,  # Passing the BasicAuth instance
        )
    ),
)


service_entity = metadata.create_or_update(data=create_service)

service_entity.json()

from metadata.generated.schema.api.data.createDatabase import CreateDatabaseRequest
from metadata.generated.schema.api.data.createDatabaseSchema import CreateDatabaseSchemaRequest
from metadata.generated.schema.api.data.createTable import CreateTableRequest
from metadata.generated.schema.entity.data.table import Column, DataType

# Creating Database
create_db = CreateDatabaseRequest(
    name="lineage",  # Replace with your actual database name
    service=service_entity.fullyQualifiedName,
)

db_entity = metadata.create_or_update(create_db)

# Creating Database Schema
create_schema = CreateDatabaseSchemaRequest(
    name="lineage",  # Replace with your actual schema name
    database=db_entity.fullyQualifiedName
)

schema_entity = metadata.create_or_update(data=create_schema)

# Creating Table
create_table = CreateTableRequest(
    name="lineage_table",  # Replace with your actual table name
    databaseSchema=schema_entity.fullyQualifiedName,
    columns=[
        Column(name="id", dataType=DataType.BIGINT),
        Column(name="name", dataType=DataType.STRING),
        Column(name="created_at", dataType=DataType.TIMESTAMP),
        Column(name="is_active", dataType=DataType.BOOLEAN),
        Column(name="score", dataType=DataType.FLOAT)
    ],
)

table_entity = metadata.create_or_update(create_table)


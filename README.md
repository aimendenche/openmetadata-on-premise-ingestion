# OpenMetadata - Secure On-Premise Metadata Ingestion (Data catalog) 

## Overview

This project demonstrates how to set up **OpenMetadata** using Docker and securely connect it to **on-premise** PostgreSQL and Hive instances. This setup is ideal for clients who require secure, on-premise solutions where their data remains private and fully under their control. Additionally, the repository includes an **Apache NiFi lineage** ingestion connector and details contributions to OpenMetadata lineage maintenance.

---

## What is OpenMetadata?

[OpenMetadata](https://open-metadata.org/) is an open-source platform that centralizes metadata management across various sources like databases, pipelines, and dashboards. It supports data governance, quality monitoring, and lineage tracking.

This project focuses on implementing **on-premise** ingestion connectors for PostgreSQL and Hive, ensuring that sensitive client data remains in their secure environment. This approach is perfect for clients who prioritize data privacy and need their data infrastructure on-site rather than in a cloud or external service.

---

## Prerequisites

Before setting up OpenMetadata, ensure the following tools are installed:

- **Docker**: [Install Docker](https://docs.docker.com/get-docker/)
- **Docker Compose**: [Install Docker Compose](https://docs.docker.com/compose/install/)

---

## Installation

### Step 1: Clone the OpenMetadata Repository

```bash
git clone https://github.com/open-metadata/OpenMetadata.git
cd OpenMetadata/docker
```

### Step 2: Start OpenMetadata with Docker Compose

Use Docker Compose to launch the required services:

```bash
docker-compose up -d
```

This command will start services for OpenMetadata, including:
- **OpenMetadata API**: Running on port `8585`
- **ElasticSearch**: Running on port `9200`
- **MySQL**: Running on port `3306`

### Step 3: Verify Docker Containers

Ensure all containers are running correctly:

```bash
docker ps
```

You should see the following services:
- `openmetadata-server` on port `8585`
- `mysql` on port `3306`
- `elasticsearch` on port `9200`

If any container is not running, you can check its logs with:

```bash
docker logs <container_name>
```

---

## Access OpenMetadata

Once the services are up, access the OpenMetadata UI at:

```
http://localhost:8585
```

Login using the default credentials:

```
Username: admin
Password: admin
```

---

## Secure On-Premise Metadata Ingestion

### PostgreSQL On-Premise Ingestion

The **PostgreSQL connector** allows for secure metadata ingestion from **local PostgreSQL instances**. This is ideal for clients who wish to keep their data and metadata ingestion fully on-premise, ensuring no data leaves their secured environment.

**Steps**:
1. Customize the provided PostgreSQL ingestion configuration file to match the client’s on-premise PostgreSQL settings.
2. Ensure the PostgreSQL service is running locally.
3. Run the ingestion script to securely ingest metadata into OpenMetadata while maintaining data privacy.

### Hive On-Premise Ingestion

Similarly, the **Hive connector** allows for secure metadata ingestion from a **local Hive instance**. It supports clients who require all metadata operations to happen on-premise.

**Steps**:
1. Configure the Hive ingestion connector based on the client’s on-premise Hive settings.
2. Ensure the Hive service is running locally.
3. Execute the Hive ingestion script.

---

## Lineage Contributions to OpenMetadata

This project also includes **lineage ingestion**. In addition, I contributed to improving the lineage code in OpenMetadata by ensuring the proper handling of lineage data and enhancing the integration between NiFi and OpenMetadata using the correct keys and parameters.

The NiFi connector in this project allows users to track pipeline metadata and lineage while ensuring that all lineage data is captured and stored according to OpenMetadata standards.


---

## Conclusion

This repository provides a secure method for on-premise metadata ingestion using PostgreSQL and Hive, ensuring that sensitive client data remains secure within their environment. It also includes NiFi, postgres lineage ingestion and highlights contributions made to improve lineage tracking in OpenMetadata.

For more information on OpenMetadata, visit the [official documentation](https://open-metadata.org/).

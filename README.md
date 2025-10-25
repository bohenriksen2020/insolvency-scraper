# Insolvency Intelligence Monorepo

This repository hosts the Insolvency Intelligence platform, combining a Next.js
frontend with Python microservices that ingest Danish insolvency data sources.

## Structure

```
insolvency-intelligence/
├── apps/web                     # Next.js frontend
├── microservices/statstidende   # Statstidende scraper API to fetch the latest insolvency companies per date. 
├── microservices/advokatnoeglen # Find a lawyer by name
├── microservices/cvr            # CVR gateway wrapper - get company name and asset list
├── microservices/aggregator     # Public aggregation API
├── libs/shared-types            # Placeholder for shared models
└── infra                        # Docker Compose + reverse proxy
```

## Getting started

1. Ensure Docker is installed and running.
2. Copy `infra/.env` and adjust values as necessary.
3. Build and start the full stack:

   ```bash
   cd infra
   docker compose up --build
   ```

4. Access the services:
   - Frontend: <http://localhost:3000>
   - Aggregator API: <http://localhost:8002>
   - Traefik proxy (placeholder): <http://localhost>

Each microservice loads environment variables from `infra/.env`, and the Docker
images install dependencies automatically from their respective
`requirements.txt` files.

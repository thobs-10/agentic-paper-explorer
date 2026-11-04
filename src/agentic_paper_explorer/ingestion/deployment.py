"""Serve nightly scheduled deployments of the ingestion flow.

One deployment per configured query, all served from this long-running process via
`prefect.serve`, so no work pool or worker is needed. Each query shows up as its own
deployment in the Prefect UI with its own run history. The process needs `PREFECT_API_URL`
pointing at a Prefect server and  Prefect reads it from the environment.
"""

from __future__ import annotations

import logging
import re
from typing import cast

from prefect import serve
from prefect.deployments.runner import EntrypointType, RunnerDeployment
from prefect.schedules import Cron

from agentic_paper_explorer.configs.settings import Settings, get_settings
from agentic_paper_explorer.ingestion.flows import ingestion_flow

logger = logging.getLogger(__name__)

DEPLOYMENT_TAGS = ["ingestion", "scheduled"]


def deployment_name_for_query(search_query: str) -> str:
    """Turn an arXiv query into a readable deployment name, e.g. `all-retrieval-augmented`.

    Args:
        search_query: str

    Returns:
        slug: str (tag for the deployment matching the query)"""

    # use sluggish approach to standardize the query by lowercasing and replacing non-alphanumeric characters with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", search_query.lower()).strip("-")
    if not slug:
        raise ValueError(f"Cannot derive a deployment name from query {search_query!r}")
    return slug


def build_deployments(settings: Settings) -> list[RunnerDeployment]:
    """Build one scheduled deployment per configured query, without contacting a server."""
    names = [deployment_name_for_query(query) for query in settings.ingestion_schedule_queries]
    if len(set(names)) != len(names):
        # to avoid queries overriding each other's deployment on prefect
        raise ValueError(f"Scheduled ingestion queries produce duplicate deployment names: {names}")

    return [
        cast(
            RunnerDeployment,
            ingestion_flow.to_deployment(
                name=name,
                schedules=[
                    Cron(
                        settings.ingestion_schedule_cron,
                        timezone=settings.ingestion_schedule_timezone,
                    )
                ],
                parameters={
                    "search_query": query,
                    "max_total_results": settings.ingestion_schedule_max_results,
                },
                tags=list(DEPLOYMENT_TAGS),
                description=f"Nightly arXiv ingestion for {query}",
                entrypoint_type=EntrypointType.MODULE_PATH,
            ),
        )
        for name, query in zip(names, settings.ingestion_schedule_queries, strict=True)
    ]


def main() -> int:
    """Register the scheduled deployments and serve them until the process is stopped."""
    logging.basicConfig(level=logging.INFO)
    deployments = build_deployments(get_settings())
    if not deployments:
        logger.error("No scheduled ingestion queries configured; nothing to serve.")
        return 1
    logger.info("Serving %d scheduled ingestion deployment(s)", len(deployments))
    serve(*deployments)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

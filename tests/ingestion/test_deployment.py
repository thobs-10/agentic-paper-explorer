"""Tests for building the scheduled ingestion deployments."""

from typing import Any

import pytest
from prefect.client.schemas.schedules import CronSchedule
from prefect.deployments.runner import RunnerDeployment

from agentic_paper_explorer.configs.settings import Settings
from agentic_paper_explorer.ingestion import deployment as deployment_module
from agentic_paper_explorer.ingestion.deployment import (
    build_deployments,
    deployment_name_for_query,
)


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_deployment_name_for_query_slugifies_arxiv_syntax() -> None:
    assert (
        deployment_name_for_query('all:"retrieval augmented generation"')
        == "all-retrieval-augmented-generation"
    )


def test_deployment_name_for_query_rejects_query_without_word_characters() -> None:
    with pytest.raises(ValueError):
        deployment_name_for_query('":"')


def test_build_deployments_creates_one_scheduled_deployment_per_query() -> None:
    settings = _settings(
        ingestion_schedule_queries=["all:transformer", "cat:cs.CL"],
        ingestion_schedule_cron="30 3 * * *",
        ingestion_schedule_timezone="Africa/Johannesburg",
        ingestion_schedule_max_results=7,
    )

    deployments = build_deployments(settings)

    assert [d.name for d in deployments] == ["all-transformer", "cat-cs-cl"]
    for deployment, query in zip(deployments, ["all:transformer", "cat:cs.CL"], strict=True):
        assert deployment.flow_name == "arxiv-ingestion"
        assert deployment.parameters == {"search_query": query, "max_total_results": 7}
        assert deployment.schedules is not None
        assert len(deployment.schedules) == 1
        schedule = deployment.schedules[0].schedule
        assert isinstance(schedule, CronSchedule)
        assert schedule.cron == "30 3 * * *"
        assert schedule.timezone == "Africa/Johannesburg"
        assert deployment.entrypoint == "agentic_paper_explorer.ingestion.flows.ingestion_flow"


def test_build_deployments_rejects_queries_with_colliding_names() -> None:
    settings = _settings(ingestion_schedule_queries=["all:transformer", "all transformer"])

    with pytest.raises(ValueError, match="duplicate"):
        build_deployments(settings)


def test_main_serves_built_deployments(monkeypatch: pytest.MonkeyPatch) -> None:
    served: list[RunnerDeployment] = []
    monkeypatch.setattr(deployment_module, "get_settings", lambda: _settings())
    monkeypatch.setattr(deployment_module, "serve", lambda *deployments: served.extend(deployments))

    assert deployment_module.main() == 0
    assert [d.name for d in served] == [
        "all-retrieval-augmented-generation",
        "all-large-language-model-agents",
    ]


def test_main_returns_error_when_no_queries_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        deployment_module, "get_settings", lambda: _settings(ingestion_schedule_queries=[])
    )
    monkeypatch.setattr(deployment_module, "serve", pytest.fail)

    assert deployment_module.main() == 1

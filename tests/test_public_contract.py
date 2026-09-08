"""The public API and engine must remain self-contained and demo-only."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from mfbo_platform.api import create_app
from mfbo_platform.config import Settings
from mfbo_platform.domain import ExperimentConfig
from mfbo_platform.engine import DemoEngine
from mfbo_platform.factory import engine_from_settings


def test_schema_exposes_only_the_demo_contract(settings, repository, queue):
    client = TestClient(create_app(settings, repository, queue))
    schema = client.get("/openapi.json").json()["components"]["schemas"]
    properties = schema["ExperimentConfig"]["properties"]
    assert set(properties) == {
        "benchmark",
        "budget",
        "strategy",
        "fidelities",
        "seed",
        "max_iterations",
        "tags",
    }
    assert properties["strategy"]["const"] == "random"
    assert properties["benchmark"]["const"] == "hartmann6"


def test_unsupported_strategy_is_rejected(valid_payload):
    with pytest.raises(ValidationError):
        ExperimentConfig(**{**valid_payload, "strategy": "unsupported"})


def test_unsupported_backend_is_rejected():
    with pytest.raises(ValidationError):
        Settings(engine_backend="external")


def test_production_demo_requires_explicit_allowance():
    with pytest.raises(ValueError, match="disabled"):
        engine_from_settings(Settings(environment="production", allow_demo_engine=False))


def test_recommendation_reports_observed_fidelity(valid_payload):
    config = ExperimentConfig(**{**valid_payload, "max_iterations": 1})
    result = DemoEngine().execute("demo", config, lambda _: None, lambda: False, lambda: False)
    assert result.recommendation.fidelity == result.metrics[0].fidelity
    assert result.recommendation.objective == result.metrics[0].objective

import pytest
from pydantic import ValidationError

from mfbo_platform.domain import ExperimentConfig


def test_valid_configuration(valid_payload: dict[str, object]) -> None:
    config = ExperimentConfig.model_validate(valid_payload)
    assert config.fidelities[-1] == 1.0
    assert config.strategy == "random"


@pytest.mark.parametrize(
    "fidelities",
    ([0.5, 0.25, 1.0], [0.25, 0.5], [0.25, 0.25, 1.0], [0.0, 1.0]),
)
def test_invalid_fidelities_rejected(
    valid_payload: dict[str, object], fidelities: list[float]
) -> None:
    with pytest.raises(ValidationError):
        ExperimentConfig.model_validate({**valid_payload, "fidelities": fidelities})


def test_unknown_fields_rejected(valid_payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ExperimentConfig.model_validate({**valid_payload, "unsupported": True})

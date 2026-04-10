import importlib

import pytest

from nook.services.registry import COLLECTOR_RUNNERS


def test_resolve_collector_runner_returns_registered_definition() -> None:
    from nook.services.registry import resolve_collector_runner

    runner = resolve_collector_runner("tech_feed")

    assert runner.module_path == "nook.services.tech_feed.service"
    assert runner.class_name == "TechFeed"


def test_resolve_collector_runner_rejects_unknown_service() -> None:
    from nook.services.registry import resolve_collector_runner

    with pytest.raises(ValueError, match="Unknown collector service"):
        resolve_collector_runner("viewer")

    with pytest.raises(ValueError, match="Unknown collector service"):
        resolve_collector_runner("missing-service")


@pytest.mark.parametrize(
    ("service_name", "runner"),
    list(COLLECTOR_RUNNERS.items()),
)
def test_collector_service_modules_do_not_expose_lambda_handler(
    service_name: str,
    runner,
) -> None:
    module = importlib.import_module(runner.module_path)

    assert not hasattr(module, "lambda_handler"), service_name


def test_run_collector_instantiates_and_executes_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nook.services.registry import run_collector

    calls: list[str] = []

    class FakeRunner:
        def __call__(self) -> None:
            calls.append("called")

    monkeypatch.setattr(
        "nook.services.registry.resolve_collector_class",
        lambda service_name: FakeRunner,
    )

    run_collector("tech_feed")

    assert calls == ["called"]

import importlib
from dataclasses import dataclass
from typing import Callable

from nook.services.catalog import get_service_definition


@dataclass(frozen=True, slots=True)
class CollectorRunner:
    module_path: str
    class_name: str


COLLECTOR_RUNNERS: dict[str, CollectorRunner] = {
    "hacker_news": CollectorRunner(
        module_path="nook.services.hacker_news.service",
        class_name="HackerNewsRetriever",
    ),
    "paper_summarizer": CollectorRunner(
        module_path="nook.services.paper_summarizer.service",
        class_name="PaperSummarizer",
    ),
    "reddit_explorer": CollectorRunner(
        module_path="nook.services.reddit_explorer.service",
        class_name="RedditExplorer",
    ),
    "tech_feed": CollectorRunner(
        module_path="nook.services.tech_feed.service",
        class_name="TechFeed",
    ),
    "github_trending": CollectorRunner(
        module_path="nook.services.github_trending.service",
        class_name="GithubTrending",
    ),
    "product_hunt": CollectorRunner(
        module_path="nook.services.product_hunt.service",
        class_name="ProductHuntRetriever",
    ),
    "google_alerts": CollectorRunner(
        module_path="nook.services.google_alerts.service",
        class_name="GoogleAlerts",
    ),
    "tech_news": CollectorRunner(
        module_path="nook.services.tech_news.service",
        class_name="TechNews",
    ),
}


def resolve_collector_runner(service_name: str) -> CollectorRunner:
    try:
        definition = get_service_definition(service_name)
    except KeyError as error:
        raise ValueError(f"Unknown collector service: {service_name}") from error

    if definition.kind != "collector":
        raise ValueError(f"Unknown collector service: {service_name}")

    try:
        return COLLECTOR_RUNNERS[service_name]
    except KeyError as error:
        raise ValueError(f"Unknown collector service: {service_name}") from error


def resolve_collector_class(service_name: str) -> Callable[[], object]:
    runner = resolve_collector_runner(service_name)
    module = importlib.import_module(runner.module_path)
    return getattr(module, runner.class_name)


def run_collector(service_name: str) -> None:
    runner_cls = resolve_collector_class(service_name)
    runner_cls()()

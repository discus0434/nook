from dataclasses import dataclass
from typing import Literal

ServiceKind = Literal["collector", "web"]
Schedule = tuple[int, int]


@dataclass(frozen=True, slots=True)
class ServiceDefinition:
    name: str
    kind: ServiceKind
    schedule: Schedule | None
    description: str


SERVICE_DEFINITIONS: tuple[ServiceDefinition, ...] = (
    ServiceDefinition(
        name="hacker_news",
        kind="collector",
        schedule=(0, 0),
        description="Hacker News collector",
    ),
    ServiceDefinition(
        name="paper_summarizer",
        kind="collector",
        schedule=(0, 6),
        description="Paper summarizer collector",
    ),
    ServiceDefinition(
        name="reddit_explorer",
        kind="collector",
        schedule=(0, 12),
        description="Reddit explorer collector",
    ),
    ServiceDefinition(
        name="tech_feed",
        kind="collector",
        schedule=(0, 18),
        description="Tech feed collector",
    ),
    ServiceDefinition(
        name="github_trending",
        kind="collector",
        schedule=(0, 24),
        description="GitHub trending collector",
    ),
    ServiceDefinition(
        name="product_hunt",
        kind="collector",
        schedule=(0, 30),
        description="Product Hunt collector",
    ),
    ServiceDefinition(
        name="viewer",
        kind="web",
        schedule=None,
        description="Viewer web application",
    ),
    ServiceDefinition(
        name="google_alerts",
        kind="collector",
        schedule=(0, 42),
        description="Google Alerts collector",
    ),
    ServiceDefinition(
        name="tech_news",
        kind="collector",
        schedule=(0, 48),
        description="Tech news collector",
    ),
)

_SERVICE_INDEX = {definition.name: definition for definition in SERVICE_DEFINITIONS}


def get_service_definition(name: str) -> ServiceDefinition:
    try:
        return _SERVICE_INDEX[name]
    except KeyError as error:
        raise KeyError(f"unknown service: {name}") from error

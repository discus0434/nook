import inspect
import os
import time
import traceback
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

from nook.services.collector_storage import CollectorStorage
from nook.services.config import load_service_toml
from nook.services.llm_client import create_client
from nook.services.storage import build_storage_backend

_MARKDOWN_FORMAT = """
# {title}

**Stars**: {score}

[View on GitHub]({url})

**Description**: {description}

**Summary**:
{summary}
"""


class Config:
    url_format = "https://github.com/trending/{language}?since=daily"
    summary_index_s3_key_format = "github_trending/{date}.md"
    readme_max_chars = 15000  # Added: Max characters for README content

    @classmethod
    def load_languages(cls) -> list[str]:
        """Load languages from languages.toml file."""
        languages_data = load_service_toml("github_trending", "languages.toml")

        # Create a list of language names
        languages = []
        for language in languages_data.get("languages", []):
            languages.append(language["name"])

        return languages


@dataclass
class Repository:
    name: str
    description: str | None
    link: str
    stars: int
    summary: str | None = None
    readme_content: str | None = None  # Added readme_content field


class GithubTrending:
    def __init__(self):
        self._storage = CollectorStorage(
            service_name="github_trending",
            backend=build_storage_backend(os.environ),
        )
        self._languages = Config.load_languages()
        self._client = create_client()

    def __call__(self) -> None:
        markdowns = []
        for language in self._languages:
            try:
                new_repositories = self._retrieve_repositories(
                    Config.url_format.format(language=language),
                )
                markdowns += [
                    self._stylize_repository_info(repository)
                    for repository in new_repositories
                ]
                time.sleep(1)
            except Exception as e:
                print(f"Error processing language {language}: {e}")
                traceback.print_exc()
                continue
        self._store_summaries(markdowns)

    def _retrieve_repositories(self, url: str) -> list[Repository]:
        response = requests.get(url)
        soup = BeautifulSoup(response.text, "html.parser")

        repositories = []
        repo_elements = soup.find_all(
            "article",
            class_="Box-row",
        )  # Use article tag for better targeting

        for repo_element in repo_elements:
            # Extract basic info
            title_element = repo_element.find("h2", class_="h3 lh-condensed")
            if not title_element or not title_element.a:
                continue
            name = title_element.a.text.strip().replace("\n", "").replace(" ", "")
            link = f"https://github.com/{name}"

            description_element = repo_element.find(
                "p",
                class_="col-9 color-fg-muted my-1 pr-4",
            )
            description = (
                description_element.text.strip() if description_element else None
            )

            stars_element = repo_element.find(
                "a",
                href=lambda href, repository_name=name: (
                    href and f"/{repository_name}/stargazers" in href
                ),
            )
            try:
                stars = (
                    int(stars_element.text.strip().replace(",", ""))
                    if stars_element
                    else 0
                )
            except (ValueError, AttributeError):
                stars = 0  # Handle cases where stars are not found or parsing fails

            repositories.append(
                Repository(
                    name=name,
                    link=link,
                    description=description,
                    stars=stars,
                ),
            )

        # Fetch README and Summarize each repository
        for repo in repositories:
            print(f"Processing repository: {repo.name}")
            # Fetch README
            print(f"  Fetching README for {repo.name}...")
            repo.readme_content = self._fetch_readme(repo.link)
            time.sleep(1)  # Sleep after fetching README

            # Summarize
            print(f"  Summarizing {repo.name}...")
            repo.summary = self._summarize_repository(repo)
            time.sleep(2)  # Sleep after summarizing

        return repositories

    def _fetch_readme(self, repo_url: str) -> str | None:
        """Fetch README content from the repository page.

        Attempts to fetch the raw README.md from the 'main' branch first.
        If that fails, falls back to scraping the repository's HTML page.

        Parameters
        ----------
        repo_url : str
            URL of the repository (e.g., "https://github.com/user/repo").

        Returns
        -------
        str | None
            The text content of the README, or None if not found or error occurred.

        """
        repo_name = repo_url.replace("https://github.com/", "")
        raw_readme_urls = [
            f"https://raw.githubusercontent.com/{repo_name}/refs/heads/main/README.md",
            f"https://raw.githubusercontent.com/{repo_name}/refs/heads/master/README.md",
            f"https://github.com/{repo_name}/blob/main/README.md",
            f"https://github.com/{repo_name}/blob/master/README.md",
        ]

        # 1. Attempt to fetch raw README.md from main branch
        for raw_readme_url in raw_readme_urls:
            try:
                print(f"  Attempting to fetch raw README: {raw_readme_url}")
                response = requests.get(raw_readme_url, timeout=10)
                if response.status_code == 200:
                    readme_text = response.text
                    print(f"    Raw README found (length: {len(readme_text)})")
                    # Basic check if content looks like markdown (avoids some error pages)
                    if (
                        readme_text.strip().startswith("#") or len(readme_text) > 50
                    ):  # Simple heuristic
                        return readme_text
                    print(
                        "Raw content seems too short or not Markdown, falling back.",
                    )
                else:
                    print(
                        f"Raw README fetch failed ({response.status_code}), falling back.",
                    )

            except requests.exceptions.RequestException as e:
                print(
                    f"  Error fetching raw README from {raw_readme_url}: {e}. Falling back.",
                )
            except Exception as e:  # Catch potential errors during raw fetch processing
                print(
                    f"  Unexpected error during raw README fetch for {raw_readme_url}: {e}. Falling back.",
                )
                traceback.print_exc()

        # 2. Fallback to HTML scraping if raw fetch failed
        try:
            print(f"  Attempting HTML scraping for README: {repo_url}")
            response = requests.get(repo_url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            readme_article = soup.find("article", id="readme")
            if not readme_article:
                readme_article = soup.find("div", id="readme")

            if readme_article:
                readme_text = readme_article.get_text(separator="\\n", strip=True)
                print(
                    f"    README found via HTML scraping (length: {len(readme_text)})",
                )
                return readme_text
            print(f"    README section not found via HTML scraping for {repo_url}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"  Error during HTML scraping fallback for {repo_url}: {e}")
            return None
        except Exception as e:
            print(f"  Error parsing HTML during fallback for {repo_url}: {e}")
            traceback.print_exc()
            return None

    def _summarize_repository(self, repository: Repository) -> str:
        """Summarize the repository with the configured LLM, considering description and README.

        Parameters
        ----------
        repository : Repository
            The repository to summarize.

        Returns
        -------
        str
            The summary text, or an error message.

        """
        description = repository.description or "なし"
        readme = repository.readme_content or "なし"

        # Truncate README if it's too long
        if len(readme) > Config.readme_max_chars:
            print(
                f"  Truncating README for {repository.name} from {len(readme)} to {Config.readme_max_chars} chars.",
            )
            readme = readme[: Config.readme_max_chars] + "... (truncated)"

        # If both description and README (after potential truncation) are effectively empty, skip summarization
        if description == "なし" and (
            readme == "なし" or readme.strip() == "... (truncated)"
        ):
            return "No description or README content available to summarize."

        try:
            return self._client.generate_content(
                contents=self._contents_format.format(
                    name=repository.name,
                    description=description,
                    readme=readme,
                ),
                system_instruction=self._system_instruction_for_summary,
            )
        except Exception as e:
            print(f"Error during summarization for repo '{repository.name}': {e}")
            return f"Error summarizing content: {e}"

    def _store_summaries(self, summaries: list[str]) -> None:
        wrote = self._storage.write_daily_markdown(summaries, separator="\n---\n")
        if wrote:
            print("Successfully stored GitHub Trending summaries.")
            return

        print("No GitHub Trending summaries to store.")

    def _stylize_repository_info(self, repository: Repository) -> str:
        # Ensure description and summary have fallbacks
        description_text = repository.description or "No description provided."
        summary_text = repository.summary or "Summary not available."

        return _MARKDOWN_FORMAT.format(
            title=repository.name,
            score=repository.stars,
            url=repository.link,
            description=description_text,
            summary=summary_text,
        )

    @property
    def _system_instruction_for_summary(self) -> str:
        """System instruction for summarizing GitHub repositories."""
        return inspect.cleandoc(
            """
            あなたは、与えられたGitHubリポジトリの名前、説明文、そしてREADMEの内容を読んで、そのリポジトリが何をするものなのか、どのような技術が使われているか、主な機能や特徴などを簡潔に日本語で要約するアシスタントです。
            READMEの内容を最優先し、説明文は補足情報として利用してください。
            リポジトリの核心的な価値が伝わるように、端的で分かりやすい要約を作成してください。
            要約以外の余計な文章は含めないでください。
            """,
        )

    @property
    def _contents_format(self) -> str:
        """Contents format for summarizing GitHub repositories."""
        return inspect.cleandoc(
            """
            リポジトリ名: {name}
            説明文: {description}
            README:
            ```
            {readme}
            ```
            """,
        )

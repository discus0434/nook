import concurrent.futures
import inspect
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

import arxiv
import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel
from tqdm import tqdm

from nook.services.collector_storage import CollectorStorage
from nook.services.llm_client import create_client
from nook.services.paper_summarizer.summary_schema import (
    PaperSummarySections,
    render_paper_summary_markdown,
)
from nook.services.storage import build_storage_backend

logger = logging.getLogger(__name__)


class Config:
    hugging_face_api_url_format = "https://huggingface.co/api/papers?date={date}"
    hugging_face_request_timeout_seconds = 30
    arxiv_id_regex = r"\d{4}\.\d{5}"
    arxiv_ids_s3_key_format = "arxiv_ids-{date}.txt"
    summary_index_s3_key_format = "paper_summarizer/{date}.md"
    llm_timeout_ms = 180000


class HuggingFacePaper(BaseModel):
    arxiv_id: str
    upvotes: int


@dataclass
class PaperInfo:
    title: str
    abstract: str
    url: str
    contents: str
    summary: PaperSummarySections = field(init=False)


class PaperIdRetriever:
    def retrieve_from_hugging_face(self) -> list[HuggingFacePaper]:
        """
        Retrieve the papers curated by Hugging Face.

        Returns
        -------
        list[HuggingFacePaper]
            The list of arXiv papers and their upvotes.
        """
        response = requests.get(
            url=Config.hugging_face_api_url_format.format(
                date=(date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
            ),
            timeout=Config.hugging_face_request_timeout_seconds,
        )
        response.raise_for_status()

        papers: list[HuggingFacePaper] = []
        for item in response.json():
            if not isinstance(item, dict):
                logger.warning("skipping hugging face paper with invalid payload item")
                continue

            paper_id = item.get("id")
            if not isinstance(paper_id, str):
                logger.warning("skipping hugging face paper with invalid id")
                continue
            if not re.fullmatch(Config.arxiv_id_regex, paper_id):
                logger.warning(
                    "skipping hugging face paper with invalid id format",
                    extra={"paper_id": paper_id},
                )
                continue

            upvotes = item.get("upvotes")
            if not isinstance(upvotes, int):
                logger.warning(
                    "skipping hugging face paper with invalid upvote count",
                    extra={"paper_id": paper_id},
                )
                continue

            papers.append(HuggingFacePaper(arxiv_id=paper_id, upvotes=upvotes))

        return papers


class PaperSummarizer:
    def __init__(self):
        self._client = create_client(timeout=Config.llm_timeout_ms)
        self._arxiv = arxiv.Client()
        self._storage = CollectorStorage(
            service_name="paper_summarizer",
            backend=build_storage_backend(os.environ),
        )
        self._paper_id_retriever = PaperIdRetriever()

        self._old_arxiv_ids = self._load_old_arxiv_ids()

    def __call__(self) -> None:
        papers = self._paper_id_retriever.retrieve_from_hugging_face()
        new_arxiv_ids = self._select_new_arxiv_ids(papers)

        print(f"The number of new arXiv IDs: {len(new_arxiv_ids)}")

        markdowns = []
        # Process papers concurrently because it takes longer than Lambda's timeout
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            markdowns = list(
                tqdm(
                    executor.map(self._process_paper, new_arxiv_ids),
                    total=len(new_arxiv_ids),
                    desc="Summarizing papers",
                )
            )

        self._save_arxiv_ids(new_arxiv_ids)
        self._store_summaries(markdowns)

    def _process_paper(self, arxiv_id: str) -> str:
        paper_info = self._retrieve_paper_info(arxiv_id)
        paper_info.summary = self._summarize_paper_info(paper_info)
        return self._stylize_paper_info(paper_info)

    def _retrieve_paper_info(self, id_or_url: str) -> PaperInfo:
        """
        Retrive arxiv paper info given its ID and information.

        Parameters
        ----------
        id_or_url : str
            The arXiv paper ID or URL.

        Returns
        -------
        PaperInfo
            The title, abstract, content, and URL of the paper.
        """

        if id_or_url.startswith("https://arxiv.org/"):
            arxiv_id = id_or_url.split("/")[-1]
        else:
            arxiv_id = id_or_url

        search = arxiv.Search(id_list=[arxiv_id])
        info = next(self._arxiv.results(search))
        contents = self._extract_body_text(arxiv_id)
        return PaperInfo(
            title=info.title,
            abstract=info.summary,
            url=info.entry_id,
            contents=contents,
        )

    def _summarize_paper_info(self, paper_info: PaperInfo) -> PaperSummarySections:
        system_instruction = self._system_instruction_format.format(
            title=paper_info.title,
            url=paper_info.url,
            abstract=paper_info.abstract,
            contents=paper_info.contents,
        )

        return self._client.generate_structured_content(
            contents=self._contents,
            system_instruction=system_instruction,
            response_schema=PaperSummarySections,
        )

    def _stylize_paper_info(self, paper_info: PaperInfo) -> str:
        return render_paper_summary_markdown(
            title=paper_info.title,
            url=paper_info.url,
            summary=paper_info.summary,
        )

    def _select_new_arxiv_ids(self, papers: list[HuggingFacePaper]) -> list[str]:
        selected_arxiv_ids: list[str] = []
        seen_arxiv_ids = set(self._old_arxiv_ids)

        for paper in sorted(papers, key=lambda paper: paper.upvotes, reverse=True):
            if paper.arxiv_id in seen_arxiv_ids:
                continue
            seen_arxiv_ids.add(paper.arxiv_id)
            selected_arxiv_ids.append(paper.arxiv_id)

        return selected_arxiv_ids

    def _store_summaries(self, summaries: list[str]) -> None:
        wrote = self._storage.write_daily_markdown(summaries)
        if not wrote:
            print("No paper summaries to store.")

    def _load_old_arxiv_ids(self) -> list[str]:
        arxiv_ids = []
        for i in range(1, 8):
            state_key = Config.arxiv_ids_s3_key_format.format(
                date=(date.today() - timedelta(days=i)).strftime("%Y-%m-%d")
            )
            content = self._storage.read_state(state_key)
            if content is None:
                continue
            arxiv_ids.extend(content.splitlines())

        return arxiv_ids

    def _save_arxiv_ids(self, new_arxiv_ids: list[str]) -> None:
        state_key = Config.arxiv_ids_s3_key_format.format(
            date=date.today().strftime("%Y-%m-%d")
        )
        self._storage.write_state(state_key, "\n".join(new_arxiv_ids))

    def _is_valid_body_line(self, line: str, min_length: int = 80):
        """本文として妥当な行かを判断するための簡易ヒューリスティック。
        ・行の長さが十分（例: 80文字以上）
        ・メールアドレス（@）が含まれない
        ・「Corresponding Author」や「University」「Lab」などのキーワードを含まない
        ・かつ、文として終わる（ピリオドが含まれている）場合を優先
        """
        if "@" in line:
            return False
        for kw in [
            "university",
            "lab",
            "department",
            "institute",
            "corresponding author",
        ]:
            if kw in line.lower():
                return False
        if len(line) < min_length:
            return False
        return "." in line

    def _extract_body_text(self, arxiv_id: str, min_line_length: int = 40):
        response = requests.get(f"https://arxiv.org/html/{arxiv_id}")
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, "html.parser")

        body = soup.body
        if body:
            for tag in body.find_all(["header", "nav", "footer", "script", "style"]):
                tag.decompose()
            full_text = body.get_text(separator="\n", strip=True)
        else:
            full_text = ""

        lines = full_text.splitlines()

        # ヒューリスティックにより、実際の論文本文の開始行を探す
        start_index = 0
        for i, line in enumerate(lines):
            clean_line = line.strip()
            # 先頭部分の空行や短すぎる行はスキップ
            if len(clean_line) < min_line_length:
                continue
            if self._is_valid_body_line(clean_line, min_length=100):
                start_index = i
                break

        # 開始行以降を本文として抽出
        body_lines = lines[start_index:]
        # ノイズ除去: 短すぎる行は除外
        filtered_lines = []
        for line in body_lines:
            if len(line.strip()) >= min_line_length:
                line = line.strip()
                line = line.replace("Â", " ")
                filtered_lines.append(line.strip())
        return "\n".join(filtered_lines)

    @property
    def _system_instruction_format(self) -> str:
        return inspect.cleandoc(
            """
            以下のテキストは、ある論文のタイトルとURL、abstract、および本文のコンテンツです。
            本文はhtmlから抽出されたもので、ノイズや不要な部分が含まれている可能性があります。
            よく読んで、ユーザーの質問に答えてください。

            title
            '''
            {title}
            '''

            url
            '''
            {url}
            '''

            abstract
            '''
            {abstract}
            '''

            contents
            '''
            {contents}
            '''
            """
        )

    @property
    def _contents(self) -> str:
        return inspect.cleandoc(
            """
            以下の structured output schema に従って、各 field を日本語で埋めてください。

            - `approach`: どのようなアプローチで課題を解決しようとしたか
            - `results`: 結果として何が達成できたのか
            - `limitations`: limitation や問題点。本文で言及されたものに加えて、本文から自然に推測できるものも含めてよい
            - `references`: 特に参照すべき参考文献。`title`、`url`、`rationale` を埋める

            なお、数式は説明に直接使わず、必要なら Python 風の疑似コードで言い換えてください。
            """
        )

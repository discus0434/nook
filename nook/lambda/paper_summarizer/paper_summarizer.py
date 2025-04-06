import concurrent.futures
import inspect
import os
import re
import json
import traceback
from dataclasses import dataclass, field
from datetime import date, timedelta
from pprint import pprint
import base64
from typing import Any

import arxiv
import boto3
import requests
from botocore.exceptions import ClientError
from bs4 import BeautifulSoup
from gemini_client import create_client
from tqdm import tqdm


class Config:
    hugging_face_api_url_format = "https://huggingface.co/papers?date={date}"
    arxiv_id_regex = r"\d{4}\.\d{5}"
    arxiv_ids_s3_key_format = "paper_summarizer/arxiv_ids-{date}.txt"
    summary_index_s3_key_format = "paper_summarizer/{date}.md"



def remove_tex_backticks(text: str) -> str:
    r"""
    文字列が TeX 形式、つまり
      `$\ldots$`
    の場合、外側のバッククォート (`) だけを削除して
      $\ldots$
    に変換します。
    それ以外の場合は、文字列を変更しません。
    """
    # 正規表現パターン:
    # ^`       : 文字列の先頭にバッククォート
    # (\$.*?\$): 内部は $ で始まり $ で終わる部分をキャプチャ（非貪欲）
    # `$       : 文字列の末尾にバッククォート
    pattern = r"^`(\$.*?\$)`$"
    return re.sub(pattern, r"\1", text)


def remove_outer_markdown_markers(text: str) -> str:
    """
    文章中の "```markdown" で始まるブロックについて、
    最も遠くにある "```" を閉じマーカーとして認識し、
    開始の "```markdown" とその閉じマーカー "```" のみを削除します。
    ブロック内に存在する他の "```" はそのまま残ります。

    例:
        入力:
            "通常のテキスト\n```markdown\n内部の```は残す\nその他のテキスト\n```\n続きのテキスト"
        出力:
            "通常のテキスト\n\n内部の```は残す\nその他のテキスト\n続きのテキスト"
    """
    pattern = r"```markdown(.*)```"
    return re.sub(pattern, lambda m: m.group(1), text, flags=re.DOTALL)


def remove_outer_singlequotes(text: str) -> str:
    """
    文章中の "'''" で始まるブロックについて、
    最も遠くにある "'''" を閉じマーカーとして認識し、
    開始の "'''" とその閉じマーカー "'''" のみを削除します。
    ブロック内に存在する他の "'''" はそのまま残ります。

    例:
        入力:
            "通常のテキスト\n'''\n内部の'''は残す\nその他のテキスト\n'''\n続きのテキスト"
        出力:
            "通常のテキスト\n\n内部の'''は残す\nその他のテキスト\n続きのテキスト"
    """
    pattern = r"'''(.*)'''"
    return re.sub(pattern, lambda m: m.group(1), text, flags=re.DOTALL)


@dataclass
class PaperInfo:
    title: str
    abstract: str
    url: str
    contents: str
    summary: str = field(init=False)


class PaperIdRetriever:
    def retrieve_from_hugging_face(self) -> list[str]:
        """
        Retrieve the arXiv IDs of the papers curated by Hugging Face.

        Returns
        -------
        list[str]
            The list of arXiv IDs, or [] if an error occurred.
        """
        arxiv_ids = []
        try:
            response = requests.get(
                url=Config.hugging_face_api_url_format.format(
                    date=(date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
                )
            )
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")

            for article in soup.find_all("article"):
                for a in article.find_all("a"):
                    href = a.get("href")
                    if re.match(rf"^/papers/{Config.arxiv_id_regex}$", href):
                        arxiv_ids.append(href.split("/")[-1])

        except requests.exceptions.RequestException as e:
            print(f"Error when retrieving papers from Hugging Face: {e}")

        return list(set(arxiv_ids))


class PaperSummarizer:
    def __init__(self):
        self._client = create_client()
        self._arxiv = arxiv.Client()
        self._s3 = boto3.client("s3")
        self._bucket_name = os.environ["BUCKET_NAME"]
        self._paper_id_retriever = PaperIdRetriever()

        self._old_arxiv_ids = self._load_old_arxiv_ids()

    def __call__(self) -> None:
        new_arxiv_ids = self._paper_id_retriever.retrieve_from_hugging_face()
        new_arxiv_ids = self._remove_duplicates(new_arxiv_ids)

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

    def _summarize_paper_info(self, paper_info: PaperInfo) -> str:
        system_instruction = self._system_instruction_format.format(
            title=paper_info.title,
            url=paper_info.url,
            abstract=paper_info.abstract,
            contents=paper_info.contents,
        )

        return self._client.generate_content(
            contents=self._contents,
            system_instruction=system_instruction,
        )

    def _stylize_paper_info(self, paper_info: PaperInfo) -> str:
        summary = paper_info.summary
        summary = remove_tex_backticks(summary)
        summary = remove_outer_markdown_markers(summary)
        summary = remove_outer_singlequotes(summary)
        return summary

    def _remove_duplicates(self, new_arxiv_ids: list[str]) -> list[str]:
        return list(set(new_arxiv_ids) - set(self._old_arxiv_ids))

    def _store_summaries(self, summaries: list[str]) -> None:
        date_str = date.today().strftime("%Y-%m-%d")
        key = Config.summary_index_s3_key_format.format(date=date_str)
        content = "\n\n---\n\n".join(summaries)
        try:
            self._s3.put_object(
                Bucket=self._bucket_name,
                Key=key,
                Body=content,
            )
        except ClientError as e:
            print(f"Error putting object {key} into bucket {self._bucket_name}.")
            print(e)

    def _load_old_arxiv_ids(self) -> list[str]:
        arxiv_ids = []
        for i in range(1, 8):
            last_n_arxiv_ids_s3_key = Config.arxiv_ids_s3_key_format.format(
                date=(date.today() - timedelta(days=i)).strftime("%Y-%m-%d")
            )
            try:
                response = self._s3.get_object(
                    Bucket=self._bucket_name,
                    Key=last_n_arxiv_ids_s3_key,
                )
                last_n_arxiv_ids = response["Body"].read().decode("utf-8").splitlines()
                arxiv_ids.extend(last_n_arxiv_ids)
            except ClientError as e:
                print(
                    f"Error getting object {last_n_arxiv_ids_s3_key} "
                    f"from bucket {self._bucket_name}. "
                )
                print(e)
                continue

        return arxiv_ids

    def _save_arxiv_ids(self, new_arxiv_ids: list[str]) -> None:
        today_arxiv_ids_s3_key = Config.arxiv_ids_s3_key_format.format(
            date=date.today().strftime("%Y-%m-%d")
        )
        try:
            arxiv_ids_content = "\n".join(new_arxiv_ids)
            self._s3.put_object(
                Bucket=self._bucket_name,
                Key=today_arxiv_ids_s3_key,
                Body=arxiv_ids_content,
            )
        except ClientError as e:
            print(
                f"Error putting object {today_arxiv_ids_s3_key} "
                f"into bucket {self._bucket_name}."
            )
            print(e)

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
        return False if "." not in line else True

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
            以下の8つの質問について、順を追って非常に詳細に、分かりやすく答えてください。

            1. 既存研究では何ができなかったのか
            2. どのようなアプローチでそれを解決しようとしたか
            3. 結果、何が達成できたのか
            4. Limitationや問題点は何か。本文で言及されているものの他、あなたが考えるものも含めて
            5. 技術的な詳細について。技術者が読むことを想定したトーンで
            6. コストや物理的な詳細について。例えばトレーニングに使用したGPUの数や時間、データセット、モデルのサイズなど
            7. 参考文献のうち、特に参照すべきもの
            8. この論文を140字以内のツイートで要約すると？

            フォーマットは以下の通りで、markdown形式で回答してください。このフォーマットに沿った文言以外の出力は不要です。
            なお、数式は表示が崩れがちで面倒なので、説明に数式を使うときは、代わりにPython風の疑似コードを書いてください。

            '''
            # タイトル

            [View Paper](url)

            ## 1. 既存研究では何ができなかったのか

            ...

            ## 2. どのようなアプローチでそれを解決しようとしたか

            ...
            '''

            それでは、よろしくお願いします。
            """
        )



def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    pprint(event)
    is_trigger_event = False

    try:
        if event.get("source") == "aws.events":
            is_trigger_event = True
            print("Invocation source: EventBridge")
        elif "requestContext" in event and event.get("requestContext", {}).get("http", {}).get("method") == "POST":
            print("Invocation source: Function URL (POST)")
            body_str = event.get("body", "{}")
            if event.get("isBase64Encoded", False):
                print("Decoding Base64 body")
                try:
                    body_str = base64.b64decode(body_str).decode('utf-8')
                except (base64.binascii.Error, UnicodeDecodeError) as e:
                    print(f"Failed to decode Base64 body: {e}")
                    body_str = "{}"
            print(f"Parsed body string: {body_str[:200]}...")
            try:
                body_json = json.loads(body_str)
                if body_json.get("source") == "aws.events":
                    print("Found 'source: aws.events' in request body.")
                    is_trigger_event = True
                else:
                    print("Request body did not contain 'source: aws.events'.")
            except json.JSONDecodeError as e:
                print(f"Failed to decode JSON body: {e}")
                print(f"Body content was: {body_str}")

        if is_trigger_event:
            print("Triggering PaperSummarizer job...")
            paper_summarizer_ = PaperSummarizer()
            paper_summarizer_()
            print("PaperSummarizer job finished.")
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"message": "PaperSummarizer triggered successfully"})
            }
        else:
             print("Invocation source not recognized or payload mismatch. No action taken.")
             if "requestContext" in event:
                 return {
                     "statusCode": 400,
                     "headers": {"Content-Type": "application/json"},
                     "body": json.dumps({"message": "Invalid request: Expected 'source: aws.events' in POST body"})
                 }
             else:
                 return {"statusCode": 400}

    except Exception as e:
        print("An error occurred during execution:")
        pprint(traceback.format_exc())
        # Return an error appropriate for Function URL if applicable
        if "requestContext" in event:
            return {
                "statusCode": 500,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"message": f"Internal server error: {e}"})
            }
        else:
            # For non-HTTP triggers
            return {"statusCode": 500}

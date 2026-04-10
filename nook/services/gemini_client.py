"""
Gemini API Client for Lambda functions.

This module provides a common interface for interacting with the Gemini API.
"""

import json
import logging
import os
import re
import traceback
from dataclasses import dataclass
from typing import Any, Mapping, TypeVar

import requests
from google import genai
from google.genai import types
from google.genai.errors import APIError
from json_repair import repair_json
from pydantic import BaseModel, ValidationError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from nook.services.runtime_secrets import require_runtime_secret

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_RETRYABLE_REQUEST_EXCEPTIONS = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
)
GEMINI_MODEL_ENV = "GEMINI_MODEL"
StructuredResponseT = TypeVar("StructuredResponseT", bound=BaseModel)


def _log_retry_attempt(retry_state):
    """
    Log retry attempt details.

    Parameters
    ----------
    retry_state : tenacity.RetryCallState
        The state of the retry.
    """
    exception = retry_state.outcome.exception()
    attempt = retry_state.attempt_number
    wait_time = retry_state.next_action.sleep

    logger.warning(
        f"API error (attempt {attempt}). Waiting {wait_time:.2f}s before retry. "
        f"Error: {exception}"
    )


def _is_retryable_error(error: Exception) -> bool:
    return isinstance(error, (APIError, *_RETRYABLE_REQUEST_EXCEPTIONS))


@dataclass
class GeminiClientConfig:
    """Configuration for the Gemini client."""

    model: str
    temperature: float = 0.5
    top_p: float = 0.95
    top_k: int = 40
    max_output_tokens: int = 8192
    response_mime_type: str = "text/plain"
    timeout: int = 60000
    use_search: bool = False

    def update(self, **kwargs) -> None:
        """Update the configuration with the given keyword arguments."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
            else:
                raise ValueError(f"Invalid configuration key: {key}")


class GeminiClient:
    """Client for interacting with the Gemini API."""

    def __init__(self, config: GeminiClientConfig | None = None, **kwargs):
        """
        Initialize the Gemini client.

        Parameters
        ----------
        config : GeminiClientConfig | None
            Configuration for the Gemini client.
            If not provided, the required env-derived model and default generation
            parameters will be used.
        """
        self._api_key = require_runtime_secret("GEMINI_API_KEY")

        self._config = config or GeminiClientConfig(model=resolve_gemini_model())
        self._config.update(**kwargs)

        self._client = genai.Client(
            api_key=self._api_key,
            http_options=types.HttpOptions(timeout=self._config.timeout),
        )
        self._chat = None

    @retry(
        stop=stop_after_attempt(7),
        wait=wait_exponential(multiplier=3, min=15, max=120),
        retry=retry_if_exception(_is_retryable_error),
        before_sleep=_log_retry_attempt,
    )
    def generate_content(
        self,
        contents: str | list[str],
        system_instruction: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        max_output_tokens: int | None = None,
        response_mime_type: str | None = None,
    ) -> str:
        """
        Generate content using the Gemini API.

        Parameters
        ----------
        contents : str | list[str]
            The content to generate from.
        system_instruction : str | None
            The system instruction to use.
        model : str | None
            The model to use.
            If not provided, the model from the config will be used.
        temperature : float | None
            The temperature to use.
            If not provided, the temperature from the config will be used.
        top_p : float | None
            The top_p to use.
            If not provided, the top_p from the config will be used.
        top_k : int | None
            The top_k to use.
            If not provided, the top_k from the config will be used.
        max_output_tokens : int | None
            The max_output_tokens to use.
            If not provided, the max_output_tokens from the config will be used.
        response_mime_type : str | None
            The response_mime_type to use.
            If not provided, the response_mime_type from the config will be used.

        Returns
        -------
        str
            The generated content.
        """
        response = self._generate_response(
            contents=contents,
            system_instruction=system_instruction,
            model=model,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            max_output_tokens=max_output_tokens,
            response_mime_type=response_mime_type or self._config.response_mime_type,
        )
        return self._extract_response_text(response)

    @retry(
        stop=stop_after_attempt(7),
        wait=wait_exponential(multiplier=3, min=15, max=120),
        retry=retry_if_exception(_is_retryable_error),
        before_sleep=_log_retry_attempt,
    )
    def generate_structured_content(
        self,
        contents: str | list[str],
        response_schema: type[StructuredResponseT],
        system_instruction: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        max_output_tokens: int | None = None,
    ) -> StructuredResponseT:
        response = self._generate_response(
            contents=contents,
            system_instruction=system_instruction,
            model=model,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            max_output_tokens=max_output_tokens,
            response_mime_type="application/json",
            response_schema=response_schema,
        )
        parsed_response = getattr(response, "parsed", None)
        if parsed_response is not None:
            return self._validate_structured_payload(parsed_response, response_schema)

        response_text = self._normalize_structured_response_text(
            self._extract_response_text(response)
        )

        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError:
            payload = self._repair_structured_payload(response_text)

        return self._validate_structured_payload(payload, response_schema)

    def _validate_structured_payload(
        self,
        payload: object,
        response_schema: type[StructuredResponseT],
    ) -> StructuredResponseT:
        if isinstance(payload, response_schema):
            return payload

        try:
            return response_schema.model_validate(payload)
        except ValidationError as error:
            print(traceback.format_exc())
            raise ValueError("Failed to validate structured Gemini response") from error

    def _raise_structured_decode_error(
        self,
        response_text: str,
        *,
        error: Exception | None = None,
    ) -> None:
        try:
            if error is not None:
                raise ValueError(
                    "Failed to decode structured Gemini response"
                ) from error
            raise ValueError("Failed to decode structured Gemini response")
        except ValueError:
            print(traceback.format_exc())
            print(
                "Failed structured Gemini response payload "
                f"(first 2000 chars): {response_text[:2000]}"
            )
            raise

    def create_chat(
        self,
        model: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        max_output_tokens: int | None = None,
    ) -> None:
        """
        Create a new chat session.

        Parameters
        ----------
        model : str | None
            The model to use.
            If not provided, the model from the config will be used.
        temperature : float | None
            The temperature to use.
            If not provided, the temperature from the config will be used.
        top_p : float | None
            The top_p to use.
            If not provided, the top_p from the config will be used.
        top_k : int | None
            The top_k to use.
            If not provided, the top_k from the config will be used.
        max_output_tokens : int | None
            The max_output_tokens to use.
            If not provided, the max_output_tokens from the config will be used.
        """
        config_params = {
            "temperature": temperature or self._config.temperature,
            "top_p": top_p or self._config.top_p,
            "top_k": top_k or self._config.top_k,
            "max_output_tokens": max_output_tokens or self._config.max_output_tokens,
            "response_modalities": ["TEXT"],
        }

        if self._config.use_search:
            google_search_tool = types.Tool(google_search=types.GoogleSearch())
            config_params["tools"] = [google_search_tool]

        self._chat = self._client.chats.create(
            model=model or self._config.model,
            config=types.GenerateContentConfig(**config_params),
        )

    def send_message(self, message: str) -> str:
        """
        Send a message to the chat and get the response.

        Parameters
        ----------
        message : str
            The message to send.

        Returns
        -------
        str
            The response from the chat.

        Raises
        ------
        ValueError
            If no chat has been created.
        """
        if not self._chat:
            raise ValueError("No chat has been created. Call create_chat() first.")

        response = self._chat.send_message(message)
        return response.text

    def chat_with_search(self, message: str, model: str | None = None) -> str:
        """
        Create a new chat with search capability and send a message.

        This is a convenience method that combines create_chat() and send_message().

        Parameters
        ----------
        message : str
            The message to send.
        model : str | None
            The model to use.
            If not provided, the model from the config will be used.

        Returns
        -------
        str
            The response from the chat.
        """
        original_use_search = self._config.use_search
        self._config.use_search = True

        try:
            self.create_chat(model=model)
            return self.send_message(message)
        finally:
            self._config.use_search = original_use_search

    def _get_default_safety_settings(self) -> list[types.SafetySetting]:
        """
        Get the default safety settings.

        Returns
        -------
        list[types.SafetySetting]
            The default safety settings.
        """
        return [
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                threshold=types.HarmBlockThreshold.BLOCK_NONE,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                threshold=types.HarmBlockThreshold.BLOCK_NONE,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                threshold=types.HarmBlockThreshold.BLOCK_NONE,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                threshold=types.HarmBlockThreshold.BLOCK_NONE,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY,
                threshold=types.HarmBlockThreshold.BLOCK_NONE,
            ),
        ]

    def _generate_response(
        self,
        *,
        contents: str | list[str],
        system_instruction: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        max_output_tokens: int | None = None,
        response_mime_type: str,
        response_schema: type[BaseModel] | None = None,
    ) -> Any:
        normalized_contents = [contents] if isinstance(contents, str) else contents
        config_params: dict[str, Any] = {
            "temperature": self._config.temperature
            if temperature is None
            else temperature,
            "top_p": self._config.top_p if top_p is None else top_p,
            "top_k": self._config.top_k if top_k is None else top_k,
            "max_output_tokens": self._config.max_output_tokens
            if max_output_tokens is None
            else max_output_tokens,
            "response_mime_type": response_mime_type,
            "safety_settings": self._get_default_safety_settings(),
        }
        if response_schema is not None:
            config_params["response_schema"] = response_schema
        if system_instruction:
            config_params["system_instruction"] = system_instruction

        return self._client.models.generate_content(
            model=self._config.model if model is None else model,
            contents=normalized_contents,
            config=types.GenerateContentConfig(**config_params),
        )

    def _extract_response_text(self, response: Any) -> str:
        text = getattr(response, "text", None)
        if isinstance(text, str) and text:
            return text

        try:
            extracted_text = response.candidates[0].content.parts[0].text
        except (AttributeError, IndexError, TypeError) as error:
            print(traceback.format_exc())
            raise ValueError("Gemini response did not contain text") from error

        if not isinstance(extracted_text, str) or not extracted_text:
            raise ValueError("Gemini response did not contain text")
        return extracted_text

    def _normalize_structured_response_text(self, text: str) -> str:
        normalized_text = text.strip()
        if normalized_text.startswith("```"):
            lines = normalized_text.splitlines()
            if len(lines) >= 2 and lines[0].startswith("```") and lines[-1] == "```":
                normalized_text = "\n".join(lines[1:-1]).strip()

        if not normalized_text.startswith("{") or not normalized_text.endswith("}"):
            self._raise_structured_decode_error(normalized_text)

        return re.sub(r",(\s*[}\]])", r"\1", normalized_text)

    def _repair_structured_payload(self, response_text: str) -> object:
        try:
            repaired_payload = repair_json(response_text, return_objects=True)
        except Exception as error:
            self._raise_structured_decode_error(response_text, error=error)

        if isinstance(repaired_payload, dict):
            return repaired_payload

        self._raise_structured_decode_error(response_text)


def create_client(config: dict[str, Any] | None = None, **kwargs) -> GeminiClient:
    """
    Create a Gemini client with the given configuration.

    Parameters
    ----------
    config : dict[str, Any] | None
        Configuration for the Gemini client.
        If not provided, the required env-derived model and default generation
        parameters will be used.

    Returns
    -------
    GeminiClient
        The Gemini client.
    """
    env = kwargs.pop("env", None)
    env_model = resolve_gemini_model(env=env)
    if config:
        client_config = GeminiClientConfig(
            model=config.get("model", env_model),
            temperature=config.get("temperature", 1.0),
            top_p=config.get("top_p", 0.95),
            top_k=config.get("top_k", 40),
            max_output_tokens=config.get("max_output_tokens", 8192),
            response_mime_type=config.get("response_mime_type", "text/plain"),
            timeout=config.get("timeout", 60000),
            use_search=config.get("use_search", False),
        )
    else:
        client_config = GeminiClientConfig(
            model=env_model,
        )

    return GeminiClient(client_config, **kwargs)


def resolve_gemini_model(
    *,
    env: Mapping[str, str | None] | None = None,
) -> str:
    resolved_env = env if env is not None else os.environ
    model = resolved_env.get(GEMINI_MODEL_ENV)
    if model:
        return model

    raise ValueError(f"Missing required environment variable: {GEMINI_MODEL_ENV}")

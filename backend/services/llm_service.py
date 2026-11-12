"""LLM integration service wrapping Google Gemini via LangChain with safe fallbacks."""

import logging
from typing import TypeVar

from pydantic import BaseModel
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from backend.config import get_settings


logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


def _is_transient_error(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    name = type(exc).__name__.lower()
    return any(
        token in name
        for token in ("connect", "timeout", "remoteprotocol", "ratelimit", "unavailable", "resourceexhausted")
    )


class LLMUnavailableError(Exception):
    """Raised when Gemini credentials are missing or the LLM client cannot be initialized."""


class LLMService:
    """Provides structured and plain-text calls to Google Gemini via LangChain."""

    def __init__(self, api_key: str | None = None, model_name: str | None = None) -> None:
        settings = get_settings()
        self.api_key = (api_key if api_key is not None else settings.gemini_api_key).strip()
        self.model_name = model_name or settings.gemini_model

    @property
    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key != "your_gemini_api_key_here")

    def _build_chat_model(self, temperature: float = 0.1):
        if not self.is_available:
            raise LLMUnavailableError("Gemini API key is not configured.")
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as exc:
            raise LLMUnavailableError(
                "langchain-google-genai is not installed."
            ) from exc

        return ChatGoogleGenerativeAI(
            model=self.model_name,
            google_api_key=self.api_key,
            temperature=temperature,
            max_retries=1,
        )

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        retry=retry_if_exception(_is_transient_error),
    )
    def invoke_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: type[T],
        temperature: float = 0.1,
    ) -> T:
        """Invoke Gemini with strict Pydantic structured output validation."""
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = self._build_chat_model(temperature=temperature)
        structured_llm = llm.with_structured_output(schema)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        result = structured_llm.invoke(messages)
        if isinstance(result, schema):
            return result
        return schema.model_validate(result)

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        retry=retry_if_exception(_is_transient_error),
    )
    def invoke_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ) -> str:
        """Invoke Gemini for plain-text generation."""
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = self._build_chat_model(temperature=temperature)
        response = llm.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
        )
        content = getattr(response, "content", response)
        if isinstance(content, list):
            parts = [
                part.get("text", str(part)) if isinstance(part, dict) else str(part)
                for part in content
            ]
            return "\n".join(parts).strip()
        return str(content).strip()

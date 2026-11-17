"""LLM integration service wrapping Google Gemini via LangChain with safe fallbacks."""

import logging
from typing import TypeVar

from pydantic import BaseModel
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from backend.config import get_settings


logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


def classify_llm_exception(exc: BaseException) -> tuple[str, str]:
    """Map an LLM exception into an explicit status label and safe diagnostic reason."""
    if isinstance(exc, LLMUnavailableError):
        return exc.status_label, exc.reason
    if isinstance(exc, LLMInvocationError):
        return exc.status_label, exc.reason

    msg = str(exc).lower()
    exc_name = type(exc).__name__.lower()

    if any(tok in msg for tok in ("api_key_invalid", "invalid api key", "api key not valid", "401", "unauthenticated", "permissiondenied", "permission_denied", "403")):
        return "invalid_credentials", "Gemini API credentials were rejected or lack permission."
    if any(tok in msg or tok in exc_name for tok in ("ratelimit", "rate_limit", "resourceexhausted", "resource_exhausted", "quota", "429")):
        return "rate_limited", "Gemini API rate limit or quota exceeded."
    if any(tok in msg for tok in ("notfound", "not_found", "404", "model is not found", "invalidargument", "invalid_argument")):
        return "model_error", "Configured Gemini model is invalid or unavailable."
    if any(tok in exc_name or tok in msg for tok in ("validationerror", "outputparserexception", "jsondecodeerror", "malformed", "none was returned")):
        return "malformed_output", "Gemini returned malformed or invalid structured output."
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)) or any(
        tok in exc_name or tok in msg
        for tok in ("connect", "timeout", "remoteprotocol", "unavailable", "503", "502", "504")
    ):
        return "transient_error", "Temporary network or timeout error reaching Gemini API."
    return "unknown_error", f"Gemini request failed ({type(exc).__name__})."


def _is_transient_error(exc: BaseException) -> bool:
    if isinstance(exc, (LLMUnavailableError, LLMInvocationError)):
        return exc.status_label in {"rate_limited", "transient_error"}
    status_label, _ = classify_llm_exception(exc)
    return status_label in {"rate_limited", "transient_error"}


class LLMUnavailableError(Exception):
    """Raised when Gemini credentials are missing or the LLM client cannot be initialized."""

    def __init__(self, reason: str = "Gemini API key is not configured.", status_label: str = "missing_key") -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_label = status_label


class LLMInvocationError(Exception):
    """Raised when Gemini invocation fails with a categorized diagnostic status."""

    def __init__(self, status_label: str, reason: str) -> None:
        super().__init__(reason)
        self.status_label = status_label
        self.reason = reason


class LLMService:
    """Provides structured and plain-text calls to Google Gemini via LangChain."""

    def __init__(self, api_key: str | None = None, model_name: str | None = None) -> None:
        settings = get_settings()
        self.api_key = (api_key if api_key is not None else settings.gemini_api_key).strip()
        self.model_name = model_name or settings.gemini_model
        self.last_status: str = "ok" if self.is_available else "missing_key"
        self.last_error_reason: str | None = None if self.is_available else "Gemini API key is not configured."

    @property
    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key != "your_gemini_api_key_here")

    def _build_chat_model(self, temperature: float = 0.1):
        if not self.is_available:
            self.last_status = "missing_key"
            self.last_error_reason = "Gemini API key is not configured."
            raise LLMUnavailableError(self.last_error_reason, status_label="missing_key")
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as exc:
            self.last_status = "dependency_missing"
            self.last_error_reason = "langchain-google-genai is not installed."
            raise LLMUnavailableError(self.last_error_reason, status_label="dependency_missing") from exc

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
        try:
            result = structured_llm.invoke(messages)
            if result is None:
                raise LLMInvocationError(
                    "malformed_output",
                    "Gemini returned an empty structured response.",
                )
            validated = result if isinstance(result, schema) else schema.model_validate(result)
            self.last_status = "ok"
            self.last_error_reason = None
            return validated
        except (LLMUnavailableError, LLMInvocationError) as exc:
            self.last_status = exc.status_label
            self.last_error_reason = exc.reason
            raise
        except Exception as exc:
            status_label, reason = classify_llm_exception(exc)
            self.last_status = status_label
            self.last_error_reason = reason
            raise LLMInvocationError(status_label, reason) from exc




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
        try:
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
                text_out = "\n".join(parts).strip()
            else:
                text_out = str(content).strip()
            self.last_status = "ok"
            self.last_error_reason = None
            return text_out
        except (LLMUnavailableError, LLMInvocationError) as exc:
            self.last_status = exc.status_label
            self.last_error_reason = exc.reason
            raise
        except Exception as exc:
            status_label, reason = classify_llm_exception(exc)
            self.last_status = status_label
            self.last_error_reason = reason
            raise LLMInvocationError(status_label, reason) from exc

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        retry=retry_if_exception(_is_transient_error),
    )
    async def ainvoke_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: type[T],
        temperature: float = 0.1,
    ) -> T:
        """Asynchronously invoke Gemini with strict Pydantic structured output validation."""
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = self._build_chat_model(temperature=temperature)
        structured_llm = llm.with_structured_output(schema)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        try:
            result = await structured_llm.ainvoke(messages)
            if result is None:
                raise LLMInvocationError(
                    "malformed_output",
                    "Gemini returned an empty structured response.",
                )
            validated = result if isinstance(result, schema) else schema.model_validate(result)
            self.last_status = "ok"
            self.last_error_reason = None
            return validated
        except (LLMUnavailableError, LLMInvocationError) as exc:
            self.last_status = exc.status_label
            self.last_error_reason = exc.reason
            raise
        except Exception as exc:
            status_label, reason = classify_llm_exception(exc)
            self.last_status = status_label
            self.last_error_reason = reason
            raise LLMInvocationError(status_label, reason) from exc

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        retry=retry_if_exception(_is_transient_error),
    )
    async def ainvoke_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ) -> str:
        """Asynchronously invoke Gemini for plain-text generation."""
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = self._build_chat_model(temperature=temperature)
        try:
            response = await llm.ainvoke(
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
                text_out = "\n".join(parts).strip()
            else:
                text_out = str(content).strip()
            self.last_status = "ok"
            self.last_error_reason = None
            return text_out
        except (LLMUnavailableError, LLMInvocationError) as exc:
            self.last_status = exc.status_label
            self.last_error_reason = exc.reason
            raise
        except Exception as exc:
            status_label, reason = classify_llm_exception(exc)
            self.last_status = status_label
            self.last_error_reason = reason
            raise LLMInvocationError(status_label, reason) from exc




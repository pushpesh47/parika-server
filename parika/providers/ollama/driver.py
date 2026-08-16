"""
PARIKA Ollama Provider - Driver

Implements the `ProviderDriver` contract
(`parika.core.provider_manager.driver.ProviderDriver`) against a local
or remote Ollama server (https://ollama.com): model discovery
(`GET /api/tags` + `GET /api/show`), health checks
(`GET /api/version`), single-turn generation (`POST /api/generate`),
and multi-turn chat with native tool calling (`POST /api/chat`),
streamed or not.

Tool calling is resolved by `chat_loop.run_chat_loop()` and
`ToolCallResolver` (`tool_calling.py`), which call `Brain.handle()` -
never `ToolManager` or any other Core component directly - so Planner
always decides how a requested capability is actually executed (see
`PARIKA_Decision_Flow.md` section 4.4 and `Running.md` section 8.3).
Wire-format translation, model discovery, and health checking are
likewise delegated to `wire.py`, `discovery.py`, `health.py`, and
`stream_consumers.py` so this module stays focused on orchestration
(see `PARIKA_Core_Coding_Standards.md` - File Size Guidelines).

This driver contains no registration, lifecycle, or capability-routing
logic; that is owned by `ProviderManager` and whatever composition
root registers this provider (see `parika/interfaces/runtime.py`).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import replace
from time import perf_counter
from typing import Any

from parika.core.brain.brain import Brain
from parika.core.logger.logger import Logger
from parika.core.provider_manager.chat_request import ChatRequest
from parika.core.provider_manager.driver import ProviderDriver
from parika.core.provider_manager.provider_health import ProviderHealth
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.request import ProviderRequest
from parika.core.provider_manager.response import ProviderResponse

from .chat_adapter import to_chat_result, to_ollama_chat_request
from .chat_loop import run_chat_loop
from .discovery import build_provider_model
from .exceptions import (
    OllamaModelNotFoundError,
    OllamaProviderError,
    OllamaRequestError,
    OllamaResponseError,
)
from .health import check_ollama_health
from .messages import OllamaMessage
from .reasoning_markup import ReasoningMarkupStreamFilter, strip_reasoning_markup
from .requests import OllamaChatRequest, OllamaGenerateRequest
from .responses import OllamaChatResponse, OllamaGenerateResponse
from .stream_consumers import consume_chat_stream, consume_generate_stream
from .stream_filter import ToolMarkupStreamFilter
from .text_tool_calls import looks_like_text_tool_call, parse_text_tool_calls
from .tool_calling import ToolCallResolver
from .transparency import (
    log_execution_completed,
    log_native_tool_calls_received,
    log_sending_request,
    log_streaming_final_response,
    log_streaming_started,
    log_tool_requested,
)
from .transport import OllamaTransport
from .wire import (
    build_chat_request_payload,
    build_generate_request_payload,
    looks_like_model_not_found,
    parse_tool_calls,
)

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_CONNECT_TIMEOUT_SECONDS = 5.0
DEFAULT_REQUEST_TIMEOUT_SECONDS = 120.0

_TAGS_PATH = "/api/tags"
_SHOW_PATH = "/api/show"
_CHAT_PATH = "/api/chat"
_GENERATE_PATH = "/api/generate"
_VERSION_PATH = "/api/version"


class OllamaProviderDriver(ProviderDriver):
    """
    ProviderDriver implementation for a local or remote Ollama server.

    In addition to the `ProviderDriver` contract
    (`discover_models()`, `check_health()`, `execute()`), this driver
    exposes `list_models()`, `health()`, `availability()`,
    `generate()`, `chat()`, and `stream()` directly for callers that
    want to invoke a specific Ollama operation without going through
    `ProviderManager.execute()`'s single dispatch method.
    """

    def __init__(
        self,
        *,
        transport: OllamaTransport,
        logger: Logger,
        base_url: str = DEFAULT_BASE_URL,
        connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        """
        Initialize the driver.

        Args:
            transport:
                HTTP transport used to communicate with the Ollama
                server.

            logger:
                PARIKA Logger component.

            base_url:
                Base URL of the Ollama server, with no trailing
                slash. Read from Configuration by the composition
                root; never hardcoded by callers.

            connect_timeout_seconds:
                Timeout applied to lightweight calls (model discovery,
                health checks).

            request_timeout_seconds:
                Timeout applied to generation/chat calls, which may
                take much longer than a health check.
        """

        self._transport = transport
        self._logger = logger.get_logger(__name__)

        self._base_url = base_url.rstrip("/")
        self._connect_timeout_seconds = connect_timeout_seconds
        self._request_timeout_seconds = request_timeout_seconds

        self._tool_call_resolver = ToolCallResolver(logger=logger)

    # ------------------------------------------------------------------
    # Brain binding
    # ------------------------------------------------------------------

    def bind_brain(self, brain: Brain) -> None:
        """
        Bind the Brain used to resolve tool calls requested by a
        model.

        Brain is constructed after ProviderManager during Core
        bootstrap (Architecture Specification section 5.1), so this
        driver is registered first and bound to Brain once it exists.
        Tool calling reports a descriptive error (rather than
        raising) if a model requests a tool before this is called.
        """

        self._tool_call_resolver.bind_brain(brain)

    # ------------------------------------------------------------------
    # ProviderDriver contract
    # ------------------------------------------------------------------

    def discover_models(self) -> frozenset[ProviderModel]:
        """
        Discover models installed on the Ollama server.
        """

        return self.list_models()  # type: ignore[return-value]

    def check_health(self) -> ProviderHealth:
        """
        Check whether the Ollama server is reachable.
        """

        return self.health()

    def execute(
        self,
        model: ProviderModel,
        request: ProviderRequest,
    ) -> ProviderResponse:
        """
        Execute a request using the specified Ollama model.

        Dispatches the provider-independent `ChatRequest` (built by
        every provider-independent layer -- Interfaces, Modules) by
        converting it to this provider's own `OllamaChatRequest` via
        `chat_adapter.to_ollama_chat_request()`, running it through
        the existing, unmodified `chat()` implementation, and
        converting the resulting `OllamaChatResponse` back into a
        provider-independent `ChatResult` via `chat_adapter
        .to_chat_result()` -- this is the one place Ollama's own
        `OllamaMessage`/`OllamaToolSpec`/`OllamaChatResponse` shapes
        are ever produced from, or reduced to, the generic
        representation.

        The concrete `OllamaChatRequest`/`OllamaGenerateRequest`
        types remain directly supported for callers that already
        hold one (e.g. this provider's own tests, or a caller that
        wants Ollama-specific control over `max_tool_iterations`).

        Raises:
            OllamaRequestError:
                If `request` is not a supported request type.
        """

        if isinstance(request, ChatRequest):
            ollama_request = to_ollama_chat_request(request)

            return to_chat_result(self.chat(model, ollama_request))

        if isinstance(request, OllamaChatRequest):
            return self.chat(model, request)

        if isinstance(request, OllamaGenerateRequest):
            return self.generate(model, request)

        raise OllamaRequestError(
            "OllamaProviderDriver only supports ChatRequest, "
            "OllamaChatRequest, and OllamaGenerateRequest, got "
            f"{type(request).__name__!r}."
        )

    # ------------------------------------------------------------------
    # Model discovery
    # ------------------------------------------------------------------

    def list_models(self) -> tuple[ProviderModel, ...]:
        """
        List every model currently installed on the Ollama server.

        For each model reported by `GET /api/tags`, `POST /api/show`
        is additionally called to derive normalized capabilities,
        execution features, and limits (see `model_mapping.py`). A
        model whose details cannot be fetched is still returned, with
        the conservative default capability set.
        """

        tags_payload = self._request_json(
            "GET",
            _TAGS_PATH,
            payload=None,
            timeout=self._connect_timeout_seconds,
        )

        raw_models = tags_payload.get("models")

        if not isinstance(raw_models, list):
            return ()

        models: list[ProviderModel] = []

        for entry in raw_models:
            if not isinstance(entry, dict):
                continue

            name = entry.get("model") or entry.get("name")

            if not isinstance(name, str) or not name:
                continue

            models.append(self._fetch_and_build_model(name, entry))

        return tuple(models)

    def _fetch_and_build_model(
        self,
        name: str,
        tags_entry: dict[str, Any],
    ) -> ProviderModel:
        """
        Fetch `/api/show` details (best effort) and build the
        ProviderModel for one discovered model.
        """

        try:
            show_payload = self._request_json(
                "POST",
                _SHOW_PATH,
                payload={"model": name},
                timeout=self._connect_timeout_seconds,
            )

        except OllamaProviderError:
            self._logger.warning(
                "Failed to fetch model details for '%s'; using "
                "default capabilities.",
                name,
            )
            show_payload = {}

        return build_provider_model(name, tags_entry, show_payload)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> ProviderHealth:
        """
        Check the operational health of the Ollama server.

        Delegates to `health.check_ollama_health()`; see its
        docstring for why connectivity failures are captured into
        `ProviderHealth(available=False, ...)` rather than raised.
        """

        return check_ollama_health(
            request_json=self._request_json,
            version_path=_VERSION_PATH,
            timeout=self._connect_timeout_seconds,
        )

    def availability(self) -> bool:
        """
        Return whether the Ollama server is currently reachable.
        """

        return self.health().available

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def generate(
        self,
        model: ProviderModel,
        request: OllamaGenerateRequest,
    ) -> OllamaGenerateResponse:
        """
        Execute a single-turn completion via `POST /api/generate`.

        Raises:
            OllamaModelNotFoundError, OllamaConnectionError,
            OllamaTimeoutError, OllamaResponseError:
                If `model` is missing, the server is unreachable, the
                request times out, or the response is malformed.
        """

        started_at = perf_counter()
        payload = build_generate_request_payload(model.id, request)
        streaming = request.on_token is not None

        log_sending_request(
            self._logger,
            model_id=model.id,
            endpoint=_GENERATE_PATH,
            streaming=streaming,
        )

        if request.on_token is not None:
            log_streaming_started(self._logger, model.id)
            final_chunk = consume_generate_stream(
                self._stream_lines(
                    "POST",
                    _GENERATE_PATH,
                    payload=payload,
                    timeout=self._request_timeout_seconds,
                ),
                on_token=request.on_token,
            )
            log_streaming_final_response(
                self._logger, model.id, len(final_chunk.get("response", ""))
            )
        else:
            final_chunk = self._request_json(
                "POST",
                _GENERATE_PATH,
                payload=payload,
                timeout=self._request_timeout_seconds,
            )

        log_execution_completed(
            self._logger, model.id, (perf_counter() - started_at) * 1000
        )

        return OllamaGenerateResponse(
            model_id=model.id,
            text=final_chunk.get("response", ""),
            done=bool(final_chunk.get("done", True)),
            total_duration_ns=final_chunk.get("total_duration"),
            prompt_eval_count=final_chunk.get("prompt_eval_count"),
            eval_count=final_chunk.get("eval_count"),
        )

    # ------------------------------------------------------------------
    # Chat / Tool Calling
    # ------------------------------------------------------------------

    def chat(
        self,
        model: ProviderModel,
        request: OllamaChatRequest,
    ) -> OllamaChatResponse:
        """
        Execute a (possibly multi-turn) chat via `POST /api/chat`,
        resolving any tool calls the model requests through
        `ToolCallResolver` (which itself always calls
        `Brain.handle()`, never bypassing Planner). See
        `chat_loop.run_chat_loop()` for the loop itself.

        Raises:
            OllamaModelNotFoundError, OllamaConnectionError,
            OllamaTimeoutError, OllamaResponseError:
                If `model` is missing, the server is unreachable, a
                request times out, or a response is malformed.

            OllamaToolCallError:
                If the model keeps requesting tool calls beyond
                `request.max_tool_iterations`.
        """

        started_at = perf_counter()

        result = run_chat_loop(
            model_id=model.id,
            messages=list(request.messages),
            tools_by_name={tool.name: tool for tool in request.tools},
            max_tool_iterations=request.max_tool_iterations,
            chat_once=lambda messages: self._chat_once(
                model, messages, request
            ),
            tool_call_resolver=self._tool_call_resolver,
        )

        log_execution_completed(
            self._logger,
            model.id,
            (perf_counter() - started_at) * 1000,
            tool_calls=len(result.tool_invocations),
        )

        return result

    def _chat_once(
        self,
        model: ProviderModel,
        messages: list[OllamaMessage],
        request: OllamaChatRequest,
    ) -> tuple[OllamaMessage, dict[str, Any]]:
        """
        Perform a single `/api/chat` round trip and return the
        produced assistant message together with the raw response
        metrics.
        """

        payload = build_chat_request_payload(model.id, messages, request)
        streaming = request.on_token is not None

        log_sending_request(
            self._logger,
            model_id=model.id,
            endpoint=_CHAT_PATH,
            streaming=streaming,
            tool_names=[tool.name for tool in request.tools],
        )

        if request.on_token is not None:
            log_streaming_started(self._logger, model.id)

            on_token = request.on_token

            # Two independent, chained filters, each scoped to this
            # one turn:
            #
            # 1. `reasoning_filter` suppresses a leaked
            #    `<think>...</think>`/`<reasoning>...</reasoning>`
            #    block live, for every streamed chat, tools or not -
            #    a model can narrate its own reasoning ("I need to
            #    search...", "Let me check...") regardless of whether
            #    this turn ends up calling a tool - then *resumes*
            #    normal streaming for whatever genuine answer text
            #    follows the closing tag, in the very same turn (see
            #    `reasoning_markup.py`'s own docstring for why this
            #    must resume, unlike leaked tool-call markup).
            # 2. `markup_filter` only ever runs when tools were
            #    actually offered - leaked tool-call template markup
            #    is exclusively a tool-calling concern, and
            #    `looks_like_text_tool_call()`'s own recovery below
            #    stays identically gated on `request.tools` - so
            #    ordinary tool-less streaming text is otherwise
            #    completely unaffected by either filter.
            reasoning_filter = ReasoningMarkupStreamFilter()
            markup_filter = (
                ToolMarkupStreamFilter() if request.tools else None
            )

            # Buffered, never flushed live: whether this turn resolves
            # to a tool call is only known once the full response has
            # been received (Ollama's native `tool_calls` field, or the
            # `looks_like_text_tool_call()` markup-recovery fallback
            # below, both require the complete `content`). Streaming a
            # fragment to `on_token` immediately - before that is known
            # - previously risked showing the caller leaked preamble
            # text for a turn that turns out to be a tool call, which
            # would then be superseded by the follow-up turn's real
            # final answer. Buffering and flushing only once confirmed
            # (below) fixes that without changing behavior for a
            # genuine, tool-call-free streamed response, which is
            # flushed in full immediately after the stream completes.
            buffered_fragments: list[str] = []

            def _filtered_on_token(fragment: str) -> None:
                safe_text = reasoning_filter.feed(fragment)

                if markup_filter is not None:
                    safe_text = markup_filter.feed(safe_text)

                if safe_text:
                    buffered_fragments.append(safe_text)

            final_chunk = consume_chat_stream(
                self._stream_lines(
                    "POST",
                    _CHAT_PATH,
                    payload=payload,
                    timeout=self._request_timeout_seconds,
                ),
                on_token=_filtered_on_token,
            )

            residual = reasoning_filter.flush()

            if markup_filter is not None:
                residual = markup_filter.feed(residual)
                residual += markup_filter.flush()

            if residual:
                buffered_fragments.append(residual)
        else:
            final_chunk = self._request_json(
                "POST",
                _CHAT_PATH,
                payload=payload,
                timeout=self._request_timeout_seconds,
            )

        reported_prompt_eval_count = final_chunk.get("prompt_eval_count")

        if reported_prompt_eval_count is not None:
            # Lightweight, ongoing observability -- not a second
            # estimation: the Runtime Context Budget's `num_ctx` was
            # already sized upstream (Planner, from AI Context
            # Engineering's own measured `estimated_prompt_tokens`,
            # see `ai_context/goal_builder.py`) before this request
            # was ever sent; this only compares that already-decided
            # value against Ollama's own reported tokenizer count.
            self._logger.debug(
                "model=%s num_ctx=%s ollama_prompt_eval_count=%s",
                model.id,
                request.options.context_window_tokens,
                reported_prompt_eval_count,
            )

        message_payload = final_chunk.get("message")
        message_payload = message_payload if isinstance(message_payload, dict) else {}

        content = message_payload.get("content", "") or ""
        content = strip_reasoning_markup(content)
        tool_calls = parse_tool_calls(message_payload.get("tool_calls"))

        log_native_tool_calls_received(self._logger, model.id, len(tool_calls))

        if not tool_calls and request.tools and looks_like_text_tool_call(content):
            recovered = parse_text_tool_calls(content)

            if recovered:
                self._logger.warning(
                    "Recovered %d tool call(s) from leaked template "
                    "markup in model=%s's response content instead of "
                    "the native tool_calls field: %s",
                    len(recovered),
                    model.id,
                    [call.name for call in recovered],
                )
                tool_calls = recovered
                content = ""

        if tool_calls and content:
            # A tool-calling turn never carries directly displayable
            # text: any accompanying content here is either leaked
            # protocol markup already excluded from the live stream
            # (see `ToolMarkupStreamFilter`) or a preamble that would
            # otherwise reach the caller as a second, superseded
            # "response" once the follow-up turn's real final answer
            # arrives. Clearing it here - regardless of whether these
            # `tool_calls` came from Ollama's native field or from
            # markup recovery above - keeps every tool-calling
            # `OllamaMessage` content-free, so exactly one assistant
            # response (the final, tool-call-free turn) is ever
            # streamed or recorded per chat turn.
            content = ""

        assistant_message = OllamaMessage(
            role="assistant",
            content=content,
            tool_calls=tool_calls,
        )

        if streaming and not assistant_message.tool_calls:
            for fragment in buffered_fragments:
                on_token(fragment)

            log_streaming_final_response(
                self._logger, model.id, len(assistant_message.content)
            )
        elif streaming and buffered_fragments:
            self._logger.debug(
                "Discarding %d buffered streaming fragment(s) for "
                "model=%s: this turn resolved to a tool call, so the "
                "buffered text was either leaked reasoning/tool-call "
                "markup or a preamble that would otherwise reach the "
                "caller as a superseded response.",
                len(buffered_fragments),
                model.id,
            )

        if assistant_message.tool_calls:
            log_tool_requested(
                self._logger,
                model.id,
                [call.name for call in assistant_message.tool_calls],
            )

        return assistant_message, final_chunk

    # ------------------------------------------------------------------
    # Streaming convenience
    # ------------------------------------------------------------------

    def stream(
        self,
        model: ProviderModel,
        request: OllamaChatRequest | OllamaGenerateRequest,
        on_token: Callable[[str], None],
    ) -> ProviderResponse:
        """
        Execute `request` with streaming enabled via `on_token`,
        regardless of whether it already carried a callback.

        This is a convenience wrapper around `execute()` for callers
        that want to supply the streaming callback separately from
        building the request itself.
        """

        streaming_request = replace(request, on_token=on_token)

        return self.execute(model, streaming_request)

    # ------------------------------------------------------------------
    # Transport helpers
    # ------------------------------------------------------------------

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None,
        timeout: float,
    ) -> dict[str, Any]:
        """
        Perform a JSON request, translating "model not found"
        responses into `OllamaModelNotFoundError`.
        """

        try:
            return self._transport.request_json(
                method,
                f"{self._base_url}{path}",
                payload=payload,
                timeout=timeout,
            )

        except OllamaResponseError as ex:
            if looks_like_model_not_found(str(ex)):
                raise OllamaModelNotFoundError(str(ex)) from ex

            raise

    def _stream_lines(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None,
        timeout: float,
    ) -> Iterator[dict[str, Any]]:
        """
        Perform a streaming NDJSON request, translating "model not
        found" responses into `OllamaModelNotFoundError`.
        """

        try:
            yield from self._transport.stream_lines(
                method,
                f"{self._base_url}{path}",
                payload=payload,
                timeout=timeout,
            )

        except OllamaResponseError as ex:
            if looks_like_model_not_found(str(ex)):
                raise OllamaModelNotFoundError(str(ex)) from ex

            raise

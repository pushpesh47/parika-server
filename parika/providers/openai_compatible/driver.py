from __future__ import annotations
import json
from collections import defaultdict
from typing import Any
from urllib.error import HTTPError
from parika.core.provider_manager.chat_message import ChatMessage, ChatToolCall
from parika.core.provider_manager.chat_request import ChatRequest
from parika.core.provider_manager.chat_result import ChatResult, ToolInvocation
from parika.core.provider_manager.driver import ProviderDriver
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.model_execution_feature import ModelExecutionFeature
from parika.core.provider_manager.model_limits import ModelLimits
from parika.core.provider_manager.provider_health import ProviderHealth
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.request import ProviderRequest
from parika.core.provider_manager.response import ProviderResponse
from parika.core.provider_manager.tool_spec import ToolSpec
from .exceptions import *  # noqa: F403
from .transport import OpenAICompatibleTransport, UrllibOpenAICompatibleTransport
from parika.core.provider_manager.exceptions import ProviderExecutionError
from parika.core.provider_manager.egress_policy import CloudEgressPolicy


def _set_nested_path(obj: dict[str, Any], path: str, value: Any) -> None:
    """Set a nested value in a dict using dot notation path (e.g., 'a.b.c')."""
    keys = path.split(".")
    current = obj
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value


class OpenAICompatibleProviderDriver(ProviderDriver):
    """One driver for arbitrary chat-completions-compatible endpoints."""
    def __init__(self, *, provider_id: str, base_url: str, model: str, api_key_env: str,
                 logger, transport: OpenAICompatibleTransport | None = None,
                 request_timeout_seconds: float = 120.0, connect_timeout_seconds: float = 10.0,
                 streaming: bool = True, tool_calling: bool = True,
                 structured_output: bool = False, reasoning: bool = False,
                 parallel_tool_calls: bool = False, allow_native_tools: bool = False,
                 allow_cloud_egress: bool = True, supported_parameters: set[str] | None = None,
                 reasoning_request_path: str | None = None):
        if not base_url or not model or not api_key_env:
            raise OpenAICompatibleConfigurationError("OpenAI-compatible provider requires base_url, model, and api_key_env")
        import os
        key = os.environ.get(api_key_env)
        if not key:
            raise OpenAICompatibleConfigurationError(f"API key environment variable '{api_key_env}' is not set")
        self.provider_id, self.base_url, self.model_id, self._key = provider_id, base_url.rstrip("/"), model, key
        self._transport = transport or UrllibOpenAICompatibleTransport()
        self._logger = logger.get_logger(__name__) if hasattr(logger, "get_logger") else logger
        self._request_timeout, self._connect_timeout = request_timeout_seconds, connect_timeout_seconds
        self._features = {ModelExecutionFeature.STREAMING} if streaming else set()
        if tool_calling: self._features.add(ModelExecutionFeature.TOOL_CALLING)
        if structured_output: self._features.update({ModelExecutionFeature.STRUCTURED_OUTPUT, ModelExecutionFeature.JSON_OUTPUT})
        self._reasoning, self._parallel = reasoning, parallel_tool_calls
        self._brain = None
        self._policy = CloudEgressPolicy(allow=allow_cloud_egress, allow_native_tools=allow_native_tools)
        self._supported_parameters = frozenset(supported_parameters) if supported_parameters else frozenset({
            "temperature", "top_p", "seed", "max_tokens", "stop"
        })
        self._reasoning_request_path = reasoning_request_path

    def bind_brain(self, brain) -> None:
        self._brain = brain

    def discover_models(self):
        # ProviderModel contains opaque mappings and is intentionally
        # consumed as a sequence by ProviderManager as well as sets.
        return (self._model(),)
    def check_health(self):
        try:
            self._request("POST", self._payload(ChatRequest(messages=(ChatMessage(role="user", content="ping")))), timeout=self._connect_timeout)
            return ProviderHealth(available=True, latency_ms=0.0)
        except Exception:
            return ProviderHealth(available=False, latency_ms=None)
    def execute(self, model: ProviderModel, request: ProviderRequest) -> ProviderResponse:
        if not isinstance(request, ChatRequest):
            raise OpenAICompatibleCapabilityError("OpenAI-compatible driver supports ChatRequest only")
        if request.options.stream and ModelExecutionFeature.STREAMING not in model.execution_features:
            raise OpenAICompatibleCapabilityError("streaming is not supported by this model")
        if request.tools and ModelExecutionFeature.TOOL_CALLING not in model.execution_features:
            raise OpenAICompatibleCapabilityError("tool calling is not supported by this model")
        return self._chat(model, request)

    def _model(self):
        return ProviderModel(id=self.model_id, name=self.model_id, capabilities=frozenset({ModelCapability.TEXT_GENERATION}), execution_features=frozenset(self._features), limits=ModelLimits())
    def _headers(self): return {"Authorization": f"Bearer {self._key}", "Content-Type":"application/json", "User-Agent":"PARIKA-openai-compatible/1.0"}
    def _payload(self, request):
        p = {"model": self.model_id, "messages":[self._message(m) for m in request.messages], "stream": bool(request.options.stream)}
        o = request.options
        for k, v in (("temperature", o.temperature), ("top_p", o.top_p), ("seed", o.seed), ("max_tokens", o.max_output_tokens), ("stop", list(o.stop_sequences) or None)):
            if v is not None and k in self._supported_parameters:
                p[k] = v
        approved_tools = [t for t in request.tools if (t.implementation != "parika_native" or self._policy.allow_native_tools) and not t.local_only]
        if approved_tools: p["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": dict(t.parameters)}} for t in approved_tools]
        if o.response_format:
            if o.response_format == "json": p["response_format"] = {"type": "json_object"}
            elif o.response_format == "json_schema" and o.response_schema: p["response_format"] = {"type": "json_schema", "json_schema": o.response_schema}
        
        # Handle reasoning/thinking parameter if configured
        if o.reasoning is not None and self._reasoning_request_path:
            _set_nested_path(p, self._reasoning_request_path, o.reasoning)
        
        return p
    @staticmethod
    def _message(message):
        value={"role":message.role,"content":message.content}
        if message.role == "tool":
            value["tool_call_id"] = message.tool_call_id
            if message.name: value["name"] = message.name
        if message.tool_calls:
            value["tool_calls"]=[{"id":c.id,"type":"function","function":{"name":c.name,"arguments":json.dumps(dict(c.arguments))}} for c in message.tool_calls]
        return value
    def _request(self, method, payload, *, timeout):
        try: return self._transport.request_json(method, self.base_url+"/chat/completions", payload=payload, headers=self._headers(), timeout=timeout)
        except HTTPError as ex:
            code=ex.code
            if code==401: raise OpenAICompatibleAuthenticationError("provider authentication failed") from ex
            if code==403: raise OpenAICompatibleAuthorizationError("provider authorization failed") from ex
            if code==404: raise OpenAICompatibleModelNotFoundError("provider model or endpoint unavailable") from ex
            if code==429: raise OpenAICompatibleRateLimitError("provider rate limit") from ex
            if code>=500: raise OpenAICompatibleServerError(f"provider server error HTTP {code}") from ex
            response_body = None
            try:
                raw_body = ex.read().decode("utf-8")
                try:
                    response_body = json.loads(raw_body)
                except json.JSONDecodeError:
                    response_body = raw_body
            except Exception:
                pass

            raise OpenAICompatibleResponseError(
                f"provider request rejected HTTP {code}",
                response_body=response_body,
                http_status=code,
            ) from ex
        except TimeoutError as ex: raise OpenAICompatibleTimeoutError("provider request timed out") from ex
        except ConnectionError as ex: raise OpenAICompatibleConnectionError("provider connection failed") from ex
        except (ValueError, json.JSONDecodeError) as ex: raise OpenAICompatibleResponseError("provider returned malformed JSON") from ex
    def _chat(self, model, request, _depth=0):
        decision = self._policy.check(category="prompt")
        if decision.decision.value == "deny":
            raise OpenAICompatibleCapabilityError(decision.reason)
        payload=self._payload(request)
        try:
            chunks = self._transport.stream_lines("POST", self.base_url+"/chat/completions", payload=payload, headers=self._headers(), timeout=self._request_timeout) if request.options.stream else (self._request("POST",payload,timeout=self._request_timeout),)
            text_parts=[]; calls=defaultdict(lambda:{"name":"","arguments":"","id":None}); usage={}
            for chunk in chunks:
                usage.update(chunk.get("usage") or {})
                for choice in chunk.get("choices") or []:
                    delta=choice.get("delta") or choice.get("message") or {}; content=delta.get("content") or ""
                    if content: text_parts.append(content); request.on_token and request.on_token(content)
                    for tc in delta.get("tool_calls") or []:
                        i=tc.get("index",0); fn=tc.get("function") or {}; calls[i]["id"]=tc.get("id") or calls[i]["id"]; calls[i]["name"]+=fn.get("name") or ""; calls[i]["arguments"]+=fn.get("arguments") or ""
            inv=[]
            for c in calls.values():
                try: args=json.loads(c["arguments"] or "{}")
                except json.JSONDecodeError as ex: raise OpenAICompatibleResponseError("provider returned malformed tool arguments") from ex
                spec = next((t for t in request.tools if t.name == c["name"]), None)
                if spec is None or spec.local_only or (spec.implementation == "parika_native" and not self._policy.allow_native_tools):
                    raise OpenAICompatibleCapabilityError("requested tool is not approved for cloud execution")
                if self._brain is None:
                    raise OpenAICompatibleCapabilityError("tool execution is unavailable")
                from parika.core.brain.brain_request import BrainRequest
                from parika.core.planner.goal import Goal
                try:
                    result = self._brain.handle(BrainRequest(goals=(Goal(id=f"cloud-tool-{c['name']}", capability_id=spec.capability_id, inputs=args),)))
                    ok = bool(result.results and result.results[0].succeeded)
                    content = str(result.results[0].response) if ok else "tool execution failed"
                except Exception as ex:
                    raise OpenAICompatibleCapabilityError("tool execution failed") from ex
                inv.append(ToolInvocation(name=c["name"], capability_id=spec.capability_id, succeeded=ok, content=content))
                inv[-1] = ToolInvocation(name=c["name"], capability_id=spec.capability_id, succeeded=ok, content=content)
            if inv and _depth < 5:
                assistant = ChatMessage(role="assistant", content="".join(text_parts), tool_calls=tuple(ChatToolCall(id=c["id"], name=c["name"], arguments=json.loads(c["arguments"] or "{}")) for c in calls.values()))
                tool_results = tuple(ChatMessage(role="tool", content=i.content, tool_call_id=c["id"], name=c["name"]) for i, c in zip(inv, calls.values()))
                next_request = ChatRequest(messages=request.messages + (assistant,) + tool_results, tools=request.tools, options=request.options)
                return self._chat(model, next_request, _depth + 1)
            if inv:
                raise OpenAICompatibleCapabilityError("maximum cloud tool iterations exceeded")
            return ChatResult(model_id=model.id, message=ChatMessage(role="assistant",content="".join(text_parts)), tool_invocations=tuple(inv), metadata={"usage":usage} if usage else {})
        except (OpenAICompatibleError, ProviderExecutionError): raise
        except Exception as ex: raise OpenAICompatibleResponseError("provider response could not be normalized") from ex

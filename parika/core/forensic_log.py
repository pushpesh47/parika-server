"""
PARIKA Forensic Logging - Temporary instrumentation for tracing
complete user request execution pipeline.

This module provides a centralized logging mechanism for forensic
tracing of the entire execution pipeline from user query to final
response. All logs are written to /mnt/dev/python/parika/tmp/goal_execution_trace.log

DO NOT USE IN PRODUCTION - This is temporary debugging instrumentation only.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

_LOG_FILE = "/mnt/dev/python/parika/tmp/goal_execution_trace.log"
_lock = threading.Lock()

# Global trace ID for the current request
_current_trace_id: str | None = None
_trace_id_lock = threading.Lock()


@dataclass
class TraceContext:
    """Context for a single trace."""
    trace_id: str
    request_id: str | None = None
    session_id: str | None = None
    user_query: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def _write_log(entry: str) -> None:
    """Write a log entry to the forensic log file."""
    with _lock:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry + "\n")


def _format_entry(trace_id: str, stage: str, data: dict[str, Any]) -> str:
    """Format a log entry with trace_id and stage."""
    timestamp = datetime.now(UTC).isoformat()
    
    def make_serializable(obj: Any) -> Any:
        if obj is None:
            return None
        if isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, (list, tuple, set)):
            return [make_serializable(v) for v in obj]
        if isinstance(obj, dict):
            return {k: make_serializable(v) for k, v in obj.items()}
        if hasattr(obj, '__dict__'):
            return make_serializable(obj.__dict__)
        return str(obj)
    
    payload = {
        "trace_id": trace_id,
        "timestamp": timestamp,
        "stage": stage,
        "data": make_serializable(data),
    }
    return json.dumps(payload, ensure_ascii=False)


def set_trace_context(
    trace_id: str | None = None,
    request_id: str | None = None,
    session_id: str | None = None,
    user_query: str | None = None,
) -> str:
    """Set the current trace context and return the trace_id."""
    global _current_trace_id
    
    with _trace_id_lock:
        if trace_id is None:
            trace_id = uuid4().hex[:16]
        _current_trace_id = trace_id
    
    # Log trace start
    if user_query is not None:
        log_user_query(trace_id, user_query, request_id, session_id)
    
    return trace_id


def get_current_trace_id() -> str | None:
    """Get the current trace ID."""
    with _trace_id_lock:
        return _current_trace_id


def clear_trace_context() -> None:
    """Clear the current trace context."""
    global _current_trace_id
    with _trace_id_lock:
        _current_trace_id = None


def log_trace_header(trace_id: str) -> None:
    """Log the trace header separator."""
    _write_log("=" * 60)
    _write_log(f"PARIKA FORENSIC TRACE")
    _write_log(f"trace_id={trace_id}")
    _write_log(f"timestamp={datetime.now(UTC).isoformat()}")
    _write_log("=" * 60)


def log_user_query(
    trace_id: str,
    user_query: str,
    request_id: str | None = None,
    session_id: str | None = None,
) -> None:
    """Log the original user query."""
    log_trace_header(trace_id)
    data = {
        "user_query": user_query,
        "request_id": request_id,
        "session_id": session_id,
    }
    _write_log(_format_entry(trace_id, "USER_QUERY", data))


def log_decomposer_input(
    trace_id: str,
    model: str | None = None,
    provider: str | None = None,
    request_options: dict[str, Any] | None = None,
    reasoning: Any = None,
    temperature: float | None = None,
    seed: int | None = None,
    top_p: float | None = None,
    structured_output: Any = None,
    num_capabilities: int | None = None,
    capability_ids: list[str] | None = None,
    system_prompt: str | None = None,
    messages: list[dict[str, str]] | None = None,
) -> None:
    """Log the GoalDecomposer input."""
    data = {
        "model": model,
        "provider": provider,
        "request_options": request_options,
        "reasoning": reasoning,
        "temperature": temperature,
        "seed": seed,
        "top_p": top_p,
        "structured_output": structured_output,
        "num_capabilities": num_capabilities,
        "capability_ids": capability_ids,
        "system_prompt": system_prompt,
        "messages": messages,
    }
    _write_log(_format_entry(trace_id, "DECOMPOSER_INPUT", data))


def log_decomposition_raw(
    trace_id: str,
    raw_response: str,
    parsed: dict[str, Any] | None = None,
    parsing_error: str | None = None,
    validation_result: dict[str, Any] | None = None,
) -> None:
    """Log the raw GoalDecomposer output."""
    data = {
        "raw_response": raw_response,
        "parsed": parsed,
        "parsing_error": parsing_error,
        "validation_result": validation_result,
    }
    _write_log(_format_entry(trace_id, "DECOMPOSITION_RAW", data))


def log_decomposition_goals(
    trace_id: str,
    goals: list[dict[str, Any]],
    before_validation: list[dict[str, Any]] | None = None,
    after_validation: list[dict[str, Any]] | None = None,
    after_enhancement: list[dict[str, Any]] | None = None,
    transformation_note: str | None = None,
) -> None:
    """Log the decomposed goals."""
    data = {
        "goals": goals,
        "before_validation": before_validation,
        "after_validation": after_validation,
        "after_enhancement": after_enhancement,
        "transformation_note": transformation_note,
    }
    _write_log(_format_entry(trace_id, "DECOMPOSITION_GOALS", data))


def log_plan(
    trace_id: str,
    plan_id: str,
    steps: list[dict[str, Any]],
) -> None:
    """Log the execution plan."""
    data = {
        "plan_id": plan_id,
        "num_steps": len(steps),
        "steps": steps,
    }
    _write_log(_format_entry(trace_id, "PLAN", data))


def log_tool_start(
    trace_id: str,
    goal_id: str,
    task_id: str,
    capability_id: str,
    tool_id: str,
    arguments: dict[str, Any],
    backend: str,
) -> None:
    """Log tool invocation start."""
    data = {
        "goal_id": goal_id,
        "task_id": task_id,
        "capability_id": capability_id,
        "tool_id": tool_id,
        "arguments": arguments,
        "backend": backend,
        "start_timestamp": datetime.now(UTC).isoformat(),
    }
    _write_log(_format_entry(trace_id, "TOOL_START", data))


def log_tool_result(
    trace_id: str,
    goal_id: str,
    task_id: str,
    capability_id: str,
    tool_id: str,
    success: bool,
    result: Any,
    exception: str | None = None,
    execution_time: float | None = None,
    result_type: str | None = None,
) -> None:
    """Log tool execution result."""
    # Truncate very large results
    result_str = str(result)
    if len(result_str) > 5000:
        result_str = result_str[:5000] + "... [TRUNCATED]"
    
    data = {
        "goal_id": goal_id,
        "task_id": task_id,
        "capability_id": capability_id,
        "tool_id": tool_id,
        "success": success,
        "result": result_str,
        "result_type": result_type or type(result).__name__,
        "exception": exception,
        "execution_time": execution_time,
    }
    _write_log(_format_entry(trace_id, "TOOL_RESULT", data))


def log_task_response_wrapping(
    trace_id: str,
    goal_id: str,
    task_id: str,
    capability_id: str,
    raw_backend_result: Any,
    capability_execution_response: dict[str, Any] | None = None,
    task_response: dict[str, Any] | None = None,
    goal_result_response_type: str | None = None,
) -> None:
    """Log the result as it moves through boundaries."""
    # Convert non-serializable objects to strings
    def make_serializable(obj: Any) -> Any:
        if obj is None:
            return None
        if isinstance(obj, (str, int, float, bool, list, tuple, dict)):
            if isinstance(obj, dict):
                return {k: make_serializable(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple)):
                return [make_serializable(v) for v in obj]
            return obj
        return str(obj)
    
    data = {
        "goal_id": goal_id,
        "task_id": task_id,
        "capability_id": capability_id,
        "raw_backend_result_type": type(raw_backend_result).__name__,
        "raw_backend_result": make_serializable(str(raw_backend_result)[:2000]),
        "capability_execution_response": make_serializable(capability_execution_response),
        "task_response": make_serializable(task_response),
        "goal_result_response_type": goal_result_response_type,
    }
    _write_log(_format_entry(trace_id, "TASK_RESPONSE_WRAPPING", data))


def log_synthesis_ready(
    trace_id: str,
    synthesis_goal_id: str,
    dependency_goal_ids: list[str],
    dependency_statuses: dict[str, str],
    all_succeeded: bool,
) -> None:
    """Log when synthesis becomes eligible."""
    data = {
        "synthesis_goal_id": synthesis_goal_id,
        "dependency_goal_ids": dependency_goal_ids,
        "dependency_statuses": dependency_statuses,
        "all_succeeded": all_succeeded,
    }
    _write_log(_format_entry(trace_id, "SYNTHESIS_READY", data))


def log_synthesis_input(
    trace_id: str,
    synthesis_goal_id: str,
    model: str | None = None,
    provider: str | None = None,
    system_messages: list[str] | None = None,
    dependency_results_message: str | None = None,
    user_message: str | None = None,
    message_roles: list[str] | None = None,
    message_ordering: list[str] | None = None,
    advertised_tools: list[str] | None = None,
    request_options: dict[str, Any] | None = None,
    context_metadata: dict[str, Any] | None = None,
) -> None:
    """Log the exact synthesis request sent to the model."""
    data = {
        "synthesis_goal_id": synthesis_goal_id,
        "model": model,
        "provider": provider,
        "system_messages": system_messages,
        "dependency_results_message": dependency_results_message,
        "user_message": user_message,
        "message_roles": message_roles,
        "message_ordering": message_ordering,
        "advertised_tools": advertised_tools,
        "request_options": request_options,
        "context_metadata": context_metadata,
    }
    _write_log(_format_entry(trace_id, "SYNTHESIS_INPUT", data))


def log_synthesis_result(
    trace_id: str,
    synthesis_goal_id: str,
    model: str | None = None,
    provider: str | None = None,
    success: bool = True,
    response_type: str | None = None,
    raw_response: str | None = None,
    tool_calls: int = 0,
    response_length: int | None = None,
    latency: float | None = None,
) -> None:
    """Log the synthesis model response."""
    response_str = raw_response or ""
    if len(response_str) > 5000:
        response_str = response_str[:5000] + "... [TRUNCATED]"
    
    data = {
        "synthesis_goal_id": synthesis_goal_id,
        "model": model,
        "provider": provider,
        "success": success,
        "response_type": response_type,
        "response": response_str,
        "tool_calls": tool_calls,
        "response_length": response_length,
        "latency": latency,
    }
    _write_log(_format_entry(trace_id, "SYNTHESIS_RESULT", data))


def log_final_result(
    trace_id: str,
    success: bool,
    used_tools: list[str] | None = None,
    response: str | None = None,
    response_status: str | None = None,
    total_execution_time: float | None = None,
    request_id: str | None = None,
) -> None:
    """Log the final PARIKA result."""
    response_str = response or ""
    if len(response_str) > 5000:
        response_str = response_str[:5000] + "... [TRUNCATED]"
    
    data = {
        "success": success,
        "used_tools": used_tools,
        "response": response_str,
        "response_status": response_status,
        "total_execution_time": total_execution_time,
        "request_id": request_id,
    }
    _write_log(_format_entry(trace_id, "FINAL_RESULT", data))


def log_experience_registration(
    trace_id: str,
    capability_id: str,
    outcome: str,
    provider_id: str | None = None,
    model_id: str | None = None,
    tool_id: str | None = None,
    latency_ms: float | None = None,
    task_succeeded: bool | None = None,
    task_id: str | None = None,
) -> None:
    """Log experience registration."""
    data = {
        "capability_id": capability_id,
        "outcome": outcome,
        "provider_id": provider_id,
        "model_id": model_id,
        "tool_id": tool_id,
        "latency_ms": latency_ms,
        "task_succeeded": task_succeeded,
        "task_id": task_id,
    }
    _write_log(_format_entry(trace_id, "EXPERIENCE_REGISTRATION", data))


def log_experience_retrieval(
    trace_id: str,
    query: str | None = None,
    capability_id: str | None = None,
    num_hits: int | None = None,
    aggregate_success_rate: float | None = None,
    passed_to_planner: bool | None = None,
) -> None:
    """Log experience retrieval during context assembly."""
    data = {
        "query": query,
        "capability_id": capability_id,
        "num_hits": num_hits,
        "aggregate_success_rate": aggregate_success_rate,
        "passed_to_planner": passed_to_planner,
    }
    _write_log(_format_entry(trace_id, "EXPERIENCE_RETRIEVAL", data))


def log_generic(trace_id: str, stage: str, data: dict[str, Any]) -> None:
    """Log a generic trace entry."""
    _write_log(_format_entry(trace_id, stage, data))
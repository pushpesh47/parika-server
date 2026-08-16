"""
End-to-end integration tests for the complete execution pipeline:

    Brain -> Planner -> TaskManager -> CapabilityExecutor ->
    ToolManager -> Web Search Tool -> Internet

These tests exercise the full, real Core stack together with the real
Web Search Module and Web Search Tool. Only the outermost network
boundary (HttpTransport) is replaced with a deterministic fake so the
suite never depends on real network access, while every PARIKA
component in between is real.

This suite models the same shape of request PARIKA receives when an
Ollama model decides to call the `web.search` tool: a single Goal
carrying a capability id and arguments.
"""

from __future__ import annotations

import pytest

from parika.core.brain.brain import Brain
from parika.core.brain.brain_request import BrainRequest
from parika.core.capability_executor.capability_executor import (
    CapabilityExecutor,
)
from parika.core.capability_registry.capability_registry import (
    CapabilityRegistry,
)
from parika.core.capability_resolver.capability_resolver import (
    CapabilityResolver,
)
from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.module_manager.module_manager import ModuleManager
from parika.core.planner.goal import Goal
from parika.core.planner.planner import Planner
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.task_manager.exceptions import (
    TaskCancelledError,
    TaskExecutionError,
)
from parika.core.task_manager.request import TaskRequest
from parika.core.task_manager.task_manager import TaskManager
from parika.core.task_manager.task_status import TaskStatus
from parika.core.tool_manager.exceptions import ToolExecutionError
from parika.core.tool_manager.tool_manager import ToolManager
from parika.modules.web_search.driver import WebSearchModuleDriver
from parika.modules.web_search.manifest import (
    WEB_SEARCH_MODULE_ID,
    create_web_search_module,
)
from parika.tools.web_search.exceptions import (
    WebSearchNetworkError,
    WebSearchTimeoutError,
)
from parika.tools.web_search.transport import HttpResponse

SAMPLE_RESULTS_HTML = """
<div class="g">
  <a href="https://example.com/parika">
    <h3>PARIKA Official Site</h3>
  </a>
  <div class="VwiC3b">Official homepage of PARIKA.</div>
</div>
"""
"""
Shaped for `GoogleHtmlSearchBackend` - the default provider (see
`config.DEFAULT_PROVIDER`) this pipeline exercises when
`WebSearchModuleDriver` is constructed without an explicit
`Configuration`, exactly as this suite's `Pipeline` does.
"""


class _FakeTransport:
    """
    Deterministic HttpTransport test double standing in for the real
    network boundary.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._responses: list[HttpResponse | Exception] = []

    def queue_response(self, response: HttpResponse) -> None:
        self._responses.append(response)

    def queue_error(self, error: Exception) -> None:
        self._responses.append(error)

    def get(self, url: str, *, timeout: float) -> HttpResponse:
        self.calls.append(url)

        item = self._responses.pop(0)

        if isinstance(item, Exception):
            raise item

        return item


def _search_response(body: str = SAMPLE_RESULTS_HTML) -> HttpResponse:
    return HttpResponse(
        status_code=200,
        url="https://www.google.com/search?q=parika&num=5",
        headers={"Content-Type": "text/html"},
        body=body.encode("utf-8"),
    )


class Pipeline:
    """Bundles the full, real Core stack plus the Web Search Module."""

    def __init__(self, transport: _FakeTransport) -> None:
        configuration = Configuration()
        logger = Logger(configuration)
        event_bus = EventBus(logger=logger)

        capability_registry = CapabilityRegistry(
            event_bus=event_bus, logger=logger
        )
        capability_resolver = CapabilityResolver(
            capability_registry=capability_registry, logger=logger
        )
        resource_manager = ResourceManager(
            configuration=configuration, logger=logger
        )
        policy_engine = PolicyEngine(event_bus=event_bus, logger=logger)
        provider_manager = ProviderManager(
            event_bus=event_bus, logger=logger
        )
        tool_manager = ToolManager(event_bus=event_bus, logger=logger)
        module_manager = ModuleManager(
            configuration=configuration,
            event_bus=event_bus,
            logger=logger,
        )

        capability_executor = CapabilityExecutor(
            event_bus=event_bus,
            logger=logger,
            tool_manager=tool_manager,
            provider_manager=provider_manager,
        )
        self.task_manager = TaskManager(
            event_bus=event_bus,
            logger=logger,
            capability_executor=capability_executor,
        )
        planner = Planner(
            capability_resolver=capability_resolver,
            resource_manager=resource_manager,
            policy_engine=policy_engine,
            provider_manager=provider_manager,
            tool_manager=tool_manager,
            logger=logger,
        )
        self.brain = Brain(
            planner=planner,
            task_manager=self.task_manager,
            logger=logger,
        )

        module_driver = WebSearchModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            transport=transport,
            # No retry delay in tests.
            backoff_seconds=0.0,
        )
        self.module_manager = module_manager
        module_manager.register(create_web_search_module(module_driver))
        module_manager.load(WEB_SEARCH_MODULE_ID)


@pytest.fixture
def transport() -> _FakeTransport:
    return _FakeTransport()


@pytest.fixture
def pipeline(transport: _FakeTransport) -> Pipeline:
    return Pipeline(transport)


def _ollama_tool_call_goal(**inputs: object) -> Goal:
    """
    Build the Goal PARIKA would plan for an Ollama `web_search` tool
    call.
    """

    return Goal(id="ollama-tool-call", capability_id="web.search", inputs=inputs)


# ---------------------------------------------------------------------
# Successful execution
# ---------------------------------------------------------------------


class TestSuccessfulExecution:
    def test_full_pipeline_returns_search_results(
        self,
        pipeline: Pipeline,
        transport: _FakeTransport,
    ) -> None:
        transport.queue_response(_search_response())

        goal = _ollama_tool_call_goal(query="PARIKA architecture")
        response = pipeline.brain.handle(BrainRequest(goals=(goal,)))

        assert response.succeeded

        result = response.results[0]
        assert result.status is TaskStatus.COMPLETED
        assert result.response is not None

        tool_response = result.response.outputs["result"]
        assert tool_response.attributes["query"] == "PARIKA architecture"
        assert tool_response.result[0]["title"] == "PARIKA Official Site"
        assert tool_response.result[0]["url"] == (
            "https://example.com/parika"
        )


# ---------------------------------------------------------------------
# Network failure
# ---------------------------------------------------------------------


class TestNetworkFailure:
    def test_persistent_network_failure_fails_the_goal(
        self,
        pipeline: Pipeline,
        transport: _FakeTransport,
    ) -> None:
        transport.queue_error(WebSearchNetworkError("connection reset"))
        transport.queue_error(WebSearchNetworkError("connection reset"))
        transport.queue_error(WebSearchNetworkError("connection reset"))

        goal = _ollama_tool_call_goal(query="PARIKA architecture")
        response = pipeline.brain.handle(BrainRequest(goals=(goal,)))

        assert not response.succeeded

        result = response.results[0]
        assert result.status is TaskStatus.FAILED
        assert isinstance(result.failure, TaskExecutionError)

        # The full exception chain is preserved end to end.
        tool_error = result.failure.__cause__
        assert isinstance(tool_error, Exception)

        cause_chain = []
        current: BaseException | None = result.failure
        while current is not None:
            cause_chain.append(type(current))
            current = current.__cause__

        assert ToolExecutionError in cause_chain
        assert WebSearchNetworkError in cause_chain


# ---------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------


class TestTimeout:
    def test_persistent_timeout_fails_the_goal(
        self,
        pipeline: Pipeline,
        transport: _FakeTransport,
    ) -> None:
        transport.queue_error(WebSearchTimeoutError("timed out"))
        transport.queue_error(WebSearchTimeoutError("timed out"))
        transport.queue_error(WebSearchTimeoutError("timed out"))

        goal = _ollama_tool_call_goal(query="PARIKA architecture")
        response = pipeline.brain.handle(BrainRequest(goals=(goal,)))

        assert not response.succeeded

        result = response.results[0]
        assert result.status is TaskStatus.FAILED

        cause_chain = []
        current: BaseException | None = result.failure
        while current is not None:
            cause_chain.append(type(current))
            current = current.__cause__

        assert WebSearchTimeoutError in cause_chain


# ---------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------


class TestRetry:
    def test_transient_failure_recovers_via_retry(
        self,
        pipeline: Pipeline,
        transport: _FakeTransport,
    ) -> None:
        transport.queue_error(WebSearchTimeoutError("timed out once"))
        transport.queue_response(_search_response())

        goal = _ollama_tool_call_goal(query="PARIKA architecture")
        response = pipeline.brain.handle(BrainRequest(goals=(goal,)))

        assert response.succeeded
        assert len(transport.calls) == 2


# ---------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------


class TestCancellation:
    def test_cancelled_task_never_reaches_the_tool(
        self,
        pipeline: Pipeline,
        transport: _FakeTransport,
    ) -> None:
        task = pipeline.task_manager.create(
            TaskRequest(
                capability_id="web.search",
                inputs={"query": "PARIKA architecture"},
            )
        )

        pipeline.task_manager.cancel(task.id)

        with pytest.raises(TaskCancelledError):
            pipeline.task_manager.execute(task.id, object())  # type: ignore[arg-type]

        assert transport.calls == []
        assert pipeline.task_manager.get(task.id).status.value == (
            "cancelled"
        )


# ---------------------------------------------------------------------
# Invalid requests
# ---------------------------------------------------------------------


class TestInvalidRequests:
    def test_missing_query_fails_the_goal_without_raising(
        self,
        pipeline: Pipeline,
        transport: _FakeTransport,
    ) -> None:
        goal = _ollama_tool_call_goal()  # No query supplied.
        response = pipeline.brain.handle(BrainRequest(goals=(goal,)))

        assert not response.succeeded

        result = response.results[0]
        assert result.status is TaskStatus.FAILED
        assert transport.calls == []

    def test_unknown_capability_reports_planning_failure(
        self,
        pipeline: Pipeline,
    ) -> None:
        goal = Goal(id="g1", capability_id="unknown.capability")
        response = pipeline.brain.handle(BrainRequest(goals=(goal,)))

        assert not response.succeeded
        assert response.plan_id is None
        assert response.planning_failure is not None

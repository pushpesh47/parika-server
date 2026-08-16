"""
PARIKA API - Concurrency Test

Tests that all independent APIs remain responsive while Core is
performing a long-running operation (simulated via test.slow_operation
capability).

This test creates a long-running Core operation (30+ seconds) and
verifies that other APIs complete successfully while Core is busy.
"""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient


class TestAPIConcurrency:
    """
    Test suite for verifying API concurrency during long Core operations.
    
    Uses test.slow_operation capability to create a deterministic
    long-running Core operation, then tests all other API endpoints
    to verify they remain responsive.
    """

    # How long the Core operation should run (seconds)
    CORE_BUSY_DURATION = 10.0
    
    # Maximum time to wait for API responses during Core busy period (seconds)
    API_TIMEOUT = 5.0

    @pytest.fixture(autouse=True)
    def setup(self, client_with_slow_module: TestClient):
        """Setup test client with slow module loaded."""
        self.client = client_with_slow_module
        self.auth_header = {"Authorization": "Bearer test-token"}

    def _make_request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        """Make an authenticated request and return parsed response."""
        headers = kwargs.pop("headers", {})
        headers.update(self.auth_header)
        response = self.client.request(method, path, headers=headers, **kwargs)
        return {
            "status_code": response.status_code,
            "json": response.json() if response.headers.get("content-type", "").startswith("application/json") else None,
            "elapsed": response.elapsed.total_seconds(),
        }

    def _execute_slow_operation(self, delay_seconds: float) -> dict[str, Any]:
        """
        Execute the test.slow_operation capability via the generic
        capabilities execute endpoint.
        """
        return self._make_request(
            "POST",
            f"/api/v1/capabilities/test.slow_operation/execute",
            json={
                "arguments": {"delay_seconds": delay_seconds},
                "parameters": {},
            },
        )

    def test_health_endpoint_during_core_busy(self):
        """Test /api/v1/health while Core is busy."""
        # Start long-running Core operation in background
        import threading
        
        core_result = {}
        core_exception = {}
        
        def run_core_operation():
            try:
                core_result["response"] = self._execute_slow_operation(self.CORE_BUSY_DURATION)
            except Exception as e:
                core_exception["error"] = e
        
        core_thread = threading.Thread(target=run_core_operation)
        core_thread.start()
        
        # Give Core time to start
        time.sleep(0.5)
        
        # Test health endpoint while Core is busy
        start = time.time()
        response = self._make_request("GET", "/api/v1/health")
        elapsed = time.time() - start
        
        # Verify response
        assert response["status_code"] == 200, f"Health endpoint failed: {response}"
        assert response["json"]["status"] == "ok"
        assert elapsed < self.API_TIMEOUT, f"Health endpoint took too long: {elapsed}s"
        
        # Verify Core is still busy
        core_thread.join(timeout=self.CORE_BUSY_DURATION + 2.0)
        assert core_thread.is_alive() or core_result.get("response"), "Core operation should still be running or completed"
        
        if core_result.get("response"):
            assert core_result["response"]["status_code"] == 200
            assert core_result["response"]["json"]["result"]["status"] == "completed"

    def test_live_endpoint_during_core_busy(self):
        """Test /api/v1/live while Core is busy."""
        import threading
        
        core_result = {}
        
        def run_core_operation():
            core_result["response"] = self._execute_slow_operation(self.CORE_BUSY_DURATION)
        
        core_thread = threading.Thread(target=run_core_operation)
        core_thread.start()
        time.sleep(0.5)
        
        start = time.time()
        response = self._make_request("GET", "/api/v1/live")
        elapsed = time.time() - start
        
        assert response["status_code"] == 200
        assert response["json"]["status"] == "ok"
        assert elapsed < self.API_TIMEOUT
        
        core_thread.join(timeout=self.CORE_BUSY_DURATION + 2.0)

    def test_ready_endpoint_during_core_busy(self):
        """Test /api/v1/ready while Core is busy."""
        import threading
        
        core_result = {}
        
        def run_core_operation():
            core_result["response"] = self._execute_slow_operation(self.CORE_BUSY_DURATION)
        
        core_thread = threading.Thread(target=run_core_operation)
        core_thread.start()
        time.sleep(0.5)
        
        start = time.time()
        response = self._make_request("GET", "/api/v1/ready")
        elapsed = time.time() - start
        
        assert response["status_code"] == 200
        assert response["json"]["status"] == "ready"
        assert elapsed < self.API_TIMEOUT
        
        core_thread.join(timeout=self.CORE_BUSY_DURATION + 2.0)

    def test_providers_endpoint_during_core_busy(self):
        """Test /api/v1/providers while Core is busy."""
        import threading
        
        core_result = {}
        
        def run_core_operation():
            core_result["response"] = self._execute_slow_operation(self.CORE_BUSY_DURATION)
        
        core_thread = threading.Thread(target=run_core_operation)
        core_thread.start()
        time.sleep(0.5)
        
        start = time.time()
        response = self._make_request("GET", "/api/v1/providers")
        elapsed = time.time() - start
        
        assert response["status_code"] == 200
        assert "providers" in response["json"]
        assert isinstance(response["json"]["providers"], list)
        assert elapsed < self.API_TIMEOUT
        
        core_thread.join(timeout=self.CORE_BUSY_DURATION + 2.0)

    def test_capabilities_endpoint_during_core_busy(self):
        """Test /api/v1/capabilities while Core is busy."""
        import threading
        
        core_result = {}
        
        def run_core_operation():
            core_result["response"] = self._execute_slow_operation(self.CORE_BUSY_DURATION)
        
        core_thread = threading.Thread(target=run_core_operation)
        core_thread.start()
        time.sleep(0.5)
        
        start = time.time()
        response = self._make_request("GET", "/api/v1/capabilities")
        elapsed = time.time() - start
        
        assert response["status_code"] == 200
        assert "capabilities" in response["json"]
        assert isinstance(response["json"]["capabilities"], list)
        assert elapsed < self.API_TIMEOUT
        
        core_thread.join(timeout=self.CORE_BUSY_DURATION + 2.0)

    def test_status_endpoint_during_core_busy(self):
        """Test /api/v1/status while Core is busy."""
        import threading
        
        core_result = {}
        
        def run_core_operation():
            core_result["response"] = self._execute_slow_operation(self.CORE_BUSY_DURATION)
        
        core_thread = threading.Thread(target=run_core_operation)
        core_thread.start()
        time.sleep(0.5)
        
        start = time.time()
        response = self._make_request("GET", "/api/v1/status")
        elapsed = time.time() - start
        
        assert response["status_code"] == 200
        assert "execution_state" in response["json"]
        assert elapsed < self.API_TIMEOUT
        
        core_thread.join(timeout=self.CORE_BUSY_DURATION + 2.0)

    def test_tools_endpoint_during_core_busy(self):
        """Test /api/v1/tools while Core is busy."""
        import threading
        
        core_result = {}
        
        def run_core_operation():
            core_result["response"] = self._execute_slow_operation(self.CORE_BUSY_DURATION)
        
        core_thread = threading.Thread(target=run_core_operation)
        core_thread.start()
        time.sleep(0.5)
        
        start = time.time()
        response = self._make_request("GET", "/api/v1/tools")
        elapsed = time.time() - start
        
        assert response["status_code"] == 200
        assert "tools" in response["json"]
        assert isinstance(response["json"]["tools"], list)
        assert elapsed < self.API_TIMEOUT
        
        core_thread.join(timeout=self.CORE_BUSY_DURATION + 2.0)

    def test_modules_endpoint_during_core_busy(self):
        """Test /api/v1/modules while Core is busy."""
        import threading
        
        core_result = {}
        
        def run_core_operation():
            core_result["response"] = self._execute_slow_operation(self.CORE_BUSY_DURATION)
        
        core_thread = threading.Thread(target=run_core_operation)
        core_thread.start()
        time.sleep(0.5)
        
        start = time.time()
        response = self._make_request("GET", "/api/v1/modules")
        elapsed = time.time() - start
        
        assert response["status_code"] == 200
        assert "modules" in response["json"]
        assert isinstance(response["json"]["modules"], list)
        assert elapsed < self.API_TIMEOUT
        
        core_thread.join(timeout=self.CORE_BUSY_DURATION + 2.0)

    def test_config_endpoint_during_core_busy(self):
        """Test /api/v1/config while Core is busy."""
        import threading
        
        core_result = {}
        
        def run_core_operation():
            core_result["response"] = self._execute_slow_operation(self.CORE_BUSY_DURATION)
        
        core_thread = threading.Thread(target=run_core_operation)
        core_thread.start()
        time.sleep(0.5)
        
        start = time.time()
        response = self._make_request("GET", "/api/v1/config")
        elapsed = time.time() - start
        
        assert response["status_code"] == 200
        assert elapsed < self.API_TIMEOUT
        
        core_thread.join(timeout=self.CORE_BUSY_DURATION + 2.0)

    def test_media_state_endpoint_during_core_busy(self):
        """Test /api/v1/media/state while Core is busy."""
        import threading
        
        core_result = {}
        
        def run_core_operation():
            core_result["response"] = self._execute_slow_operation(self.CORE_BUSY_DURATION)
        
        core_thread = threading.Thread(target=run_core_operation)
        core_thread.start()
        time.sleep(0.5)
        
        start = time.time()
        response = self._make_request("GET", "/api/v1/media/state")
        elapsed = time.time() - start
        
        assert response["status_code"] == 200
        assert elapsed < self.API_TIMEOUT
        
        core_thread.join(timeout=self.CORE_BUSY_DURATION + 2.0)

    def test_voice_settings_endpoint_during_core_busy(self):
        """Test /api/v1/voice/settings while Core is busy."""
        import threading
        
        core_result = {}
        
        def run_core_operation():
            core_result["response"] = self._execute_slow_operation(self.CORE_BUSY_DURATION)
        
        core_thread = threading.Thread(target=run_core_operation)
        core_thread.start()
        time.sleep(0.5)
        
        start = time.time()
        response = self._make_request("GET", "/api/v1/voice/settings")
        elapsed = time.time() - start
        
        assert response["status_code"] == 200
        assert elapsed < self.API_TIMEOUT
        
        core_thread.join(timeout=self.CORE_BUSY_DURATION + 2.0)

    def test_expense_create_during_core_busy(self):
        """Test POST /api/v1/expenses while Core is busy."""
        import threading
        
        core_result = {}
        
        def run_core_operation():
            core_result["response"] = self._execute_slow_operation(self.CORE_BUSY_DURATION)
        
        core_thread = threading.Thread(target=run_core_operation)
        core_thread.start()
        time.sleep(0.5)
        
        start = time.time()
        response = self._make_request(
            "POST",
            "/api/v1/expenses",
            json={"amount": 1000, "item": "concurrency-test", "date": "today"},
        )
        elapsed = time.time() - start
        
        assert response["status_code"] == 200
        assert "expense" in response["json"]
        assert response["json"]["expense"]["item"] == "concurrency-test"
        assert elapsed < self.API_TIMEOUT
        
        core_thread.join(timeout=self.CORE_BUSY_DURATION + 2.0)

    def test_expense_list_during_core_busy(self):
        """Test GET /api/v1/expenses while Core is busy."""
        import threading
        
        core_result = {}
        
        def run_core_operation():
            core_result["response"] = self._execute_slow_operation(self.CORE_BUSY_DURATION)
        
        core_thread = threading.Thread(target=run_core_operation)
        core_thread.start()
        time.sleep(0.5)
        
        start = time.time()
        response = self._make_request("GET", "/api/v1/expenses")
        elapsed = time.time() - start
        
        assert response["status_code"] == 200
        assert "expenses" in response["json"]
        assert isinstance(response["json"]["expenses"], list)
        assert elapsed < self.API_TIMEOUT
        
        core_thread.join(timeout=self.CORE_BUSY_DURATION + 2.0)

    def test_expense_summary_during_core_busy(self):
        """Test GET /api/v1/expenses/summary while Core is busy."""
        import threading
        
        core_result = {}
        
        def run_core_operation():
            core_result["response"] = self._execute_slow_operation(self.CORE_BUSY_DURATION)
        
        core_thread = threading.Thread(target=run_core_operation)
        core_thread.start()
        time.sleep(0.5)
        
        start = time.time()
        response = self._make_request("GET", "/api/v1/expenses/summary")
        elapsed = time.time() - start
        
        assert response["status_code"] == 200
        assert "total" in response["json"]
        assert elapsed < self.API_TIMEOUT
        
        core_thread.join(timeout=self.CORE_BUSY_DURATION + 2.0)

    def test_multiple_apis_concurrently_during_core_busy(self):
        """Test multiple APIs simultaneously while Core is busy."""
        import threading
        
        core_result = {}
        
        def run_core_operation():
            core_result["response"] = self._execute_slow_operation(self.CORE_BUSY_DURATION)
        
        core_thread = threading.Thread(target=run_core_operation)
        core_thread.start()
        time.sleep(0.5)
        
        # Test multiple endpoints concurrently
        endpoints = [
            ("GET", "/api/v1/health"),
            ("GET", "/api/v1/live"),
            ("GET", "/api/v1/ready"),
            ("GET", "/api/v1/providers"),
            ("GET", "/api/v1/capabilities"),
            ("GET", "/api/v1/status"),
            ("GET", "/api/v1/tools"),
            ("GET", "/api/v1/modules"),
            ("GET", "/api/v1/config"),
            ("GET", "/api/v1/media/state"),
            ("GET", "/api/v1/voice/settings"),
            ("GET", "/api/v1/expenses"),
            ("GET", "/api/v1/expenses/summary"),
        ]
        
        results = {}
        
        def test_endpoint(method, path):
            start = time.time()
            response = self._make_request(method, path)
            results[path] = {
                "response": response,
                "elapsed": time.time() - start,
            }
        
        threads = []
        for method, path in endpoints:
            t = threading.Thread(target=test_endpoint, args=(method, path))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join(timeout=self.API_TIMEOUT * 2)
        
        # Verify all succeeded
        for path, result in results.items():
            assert result["response"]["status_code"] == 200, f"Failed: {path} -> {result['response']}"
            assert result["elapsed"] < self.API_TIMEOUT, f"Too slow: {path} took {result['elapsed']}s"
        
        core_thread.join(timeout=self.CORE_BUSY_DURATION + 2.0)

    def test_chat_blocked_by_core_busy(self):
        """Test that /api/v1/chat IS blocked by Core busy (expected behavior)."""
        import threading
        
        core_result = {}
        
        def run_core_operation():
            core_result["response"] = self._execute_slow_operation(self.CORE_BUSY_DURATION)
        
        core_thread = threading.Thread(target=run_core_operation)
        core_thread.start()
        time.sleep(0.5)
        
        # Chat should be blocked/queued behind the slow operation
        start = time.time()
        response = self._make_request(
            "POST",
            "/api/v1/chat",
            json={"text": "hello", "session_id": "test-concurrency"},
        )
        elapsed = time.time() - start
        
        # Chat goes through CoreExecutionOwner so it will wait
        # The response should eventually succeed but take at least CORE_BUSY_DURATION
        assert response["status_code"] == 200
        # Should take at least the core busy duration (minus some overhead)
        assert elapsed >= self.CORE_BUSY_DURATION * 0.8, f"Chat should have waited for Core: {elapsed}s"
        
        core_thread.join(timeout=self.CORE_BUSY_DURATION + 2.0)


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
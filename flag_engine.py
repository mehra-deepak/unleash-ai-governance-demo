from __future__ import annotations

import os
import logging
import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

import requests
from UnleashClient import UnleashClient


FEATURE_NAME = "gpt_5_assistant"
DEMO_MODE_MESSAGE = "Unleash not connected – running in demo mode"


@dataclass
class FlagEvaluation:
    user_id: str
    user_type: str
    enabled: bool
    model: str
    latency_ms: int
    cost_per_request: float
    hallucination: bool
    incident: bool
    reason: str
    timestamp: str


@dataclass
class UnleashFeatureFlagGateway:
    """Production-style wrapper around the Unleash Python SDK.

    The SDK owns feature evaluation. This app adds demo-friendly controls,
    logging, and a kill switch so viewers can see why feature flags are useful
    during risky production releases.
    """

    unleash_url: str = os.getenv("UNLEASH_URL", "http://localhost:4242/api")
    client_token: str = os.getenv(
        "UNLEASH_API_TOKEN",
        os.getenv(
            "UNLEASH_CLIENT_TOKEN",  # Backward-compatible alias.
        "default:development.unleash-insecure-api-token",
        ),
    )
    admin_token: str = os.getenv(
        "UNLEASH_ADMIN_TOKEN",
        "*:*.unleash-insecure-admin-api-token",
    )
    app_name: str = os.getenv("UNLEASH_APP_NAME", "ai-governance-demo")
    project_id: str = os.getenv("UNLEASH_PROJECT_ID", "default")
    environment: str = os.getenv("UNLEASH_ENVIRONMENT", "development")
    refresh_interval: int = int(os.getenv("UNLEASH_REFRESH_INTERVAL", "2"))
    startup_retries: int = int(os.getenv("UNLEASH_STARTUP_RETRIES", "5"))
    startup_retry_delay: float = float(os.getenv("UNLEASH_RETRY_DELAY", "0.5"))
    cache_directory: str = os.getenv(
        "UNLEASH_CACHE_DIRECTORY",
        str(Path(__file__).parent / ".unleash-cache"),
    )
    logs: list[FlagEvaluation] = field(default_factory=list)

    def __post_init__(self) -> None:
        logging.getLogger("UnleashClient").setLevel(logging.CRITICAL)
        logging.getLogger("apscheduler").setLevel(logging.CRITICAL)
        self._lock = Lock()
        self._kill_switch_enabled = False
        self._configured_enabled = False
        self._configured_rollout = 0
        self._last_admin_message = "Waiting for Unleash setup."
        self._last_health_checked = 0.0
        self._last_health_status = False
        self._wait_for_unleash()
        self._client = self._build_client()

    def _wait_for_unleash(self) -> None:
        """Give a starting Unleash container a brief window to become ready."""
        for attempt in range(1, self.startup_retries + 1):
            if self._unleash_healthy(force=True):
                self._last_admin_message = "Connected to Unleash."
                return
            if attempt < self.startup_retries:
                time.sleep(self.startup_retry_delay)
        self._last_admin_message = DEMO_MODE_MESSAGE

    def _build_client(self) -> UnleashClient:
        # The Python SDK downloads flag definitions from Unleash and evaluates
        # them locally. That keeps application checks fast and resilient.
        client = UnleashClient(
            url=self.unleash_url,
            app_name=self.app_name,
            custom_headers={"Authorization": self.client_token},
            refresh_interval=self.refresh_interval,
            metrics_interval=10,
            disable_metrics=True,
            disable_registration=True,
            request_timeout=1,
            request_retries=0,
            cache_directory=self.cache_directory,
            verbose_log_level=50,
        )
        client.initialize_client()
        return client

    def close(self) -> None:
        self._client.destroy()

    def check(self, user_id: str, user_type: str = "regular") -> dict[str, Any]:
        """Evaluate the GPT-5 assistant flag and simulate production metrics."""
        user_type = self._validate_user_type(user_type)
        with self._lock:
            kill_switch_enabled = self._kill_switch_enabled
            configured_enabled = self._configured_enabled
            configured_rollout = self._configured_rollout

        if kill_switch_enabled:
            result = self._evaluation(user_id, user_type, False, "kill switch", False)
            self._append_log(result)
            return result.__dict__

        context = {"userId": user_id, "properties": {"userType": user_type}}
        if not configured_enabled:
            enabled = False
            reason = "disabled"
        elif not self._unleash_healthy():
            enabled = False
            reason = "demo mode"
        else:
            enabled = bool(self._client.is_enabled(FEATURE_NAME, context))
            reason = "targeted rollout" if enabled else "not targeted"

        incident = enabled and configured_rollout > 50 and self._bucket(user_id, "incident") < 35
        if incident:
            causes = ("latency spike", "cost spike", "hallucination increase")
            reason = causes[self._bucket(user_id, "cause") % len(causes)]

        result = self._evaluation(user_id, user_type, enabled, reason, incident)
        self._append_log(result)
        return result.__dict__

    def simulate_users(self, count: int = 50) -> dict[str, Any]:
        users = [f"user-{index:03d}" for index in range(1, count + 1)]
        audiences = ("internal", "beta", "regular")
        results = [self.check(user_id, audiences[(index - 1) % 3]) for index, user_id in enumerate(users, 1)]
        enabled_count = sum(1 for result in results if result["enabled"])
        incident_count = sum(1 for result in results if result["incident"])
        average_latency = round(sum(result["latency_ms"] for result in results) / count)
        average_cost = round(sum(result["cost_per_request"] for result in results) / count, 4)
        hallucination_rate = round(
            sum(1 for result in results if result["hallucination"]) / count * 100,
            1,
        )
        return {
            "total": count,
            "enabled": enabled_count,
            "disabled": count - enabled_count,
            "incidents": incident_count,
            "incident": incident_count > 0,
            "metrics": {
                "latency_ms": average_latency,
                "cost_per_request": average_cost,
                "hallucination_rate": hallucination_rate,
            },
            "audiences": {
                audience: sum(1 for result in results if result["user_type"] == audience and result["enabled"])
                for audience in audiences
            },
            "results": results,
            "rollout": self._configured_rollout,
            "kill_switch": self._kill_switch_enabled,
        }

    def update_release(self, enabled: bool, rollout: int) -> dict[str, Any]:
        """Update demo release settings and try to mirror them in Unleash.

        In a real company, this is the moment an operator changes rollout in
        Unleash instead of shipping a new deploy. The app starts using the new
        policy as soon as the SDK refreshes its local flag cache.
        """
        rollout = self._validate_rollout(rollout)
        with self._lock:
            self._kill_switch_enabled = False
            self._configured_enabled = enabled
            self._configured_rollout = rollout

        admin_message = self._sync_unleash_admin(enabled=enabled, rollout=rollout)
        self._last_admin_message = admin_message
        return self.config()

    def kill_switch(self) -> dict[str, Any]:
        """Immediately stop serving the risky feature.

        The local guard takes effect instantly, then the app attempts to turn
        the flag off in Unleash so every SDK client converges on the same state.
        """
        with self._lock:
            self._kill_switch_enabled = True
            self._configured_enabled = False
            self._configured_rollout = 0

        admin_message = self._sync_unleash_admin(enabled=False, rollout=0)
        self._last_admin_message = f"Kill switch active. {admin_message}"
        return self.config()

    def config(self) -> dict[str, Any]:
        with self._lock:
            return {
                "feature": FEATURE_NAME,
                "enabled": self._configured_enabled,
                "rollout": self._configured_rollout,
                "kill_switch": self._kill_switch_enabled,
                "unleash_url": self.unleash_url,
                "admin_message": self._last_admin_message,
                "fallback_message": DEMO_MODE_MESSAGE,
            }

    def recent_logs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [entry.__dict__ for entry in self.logs[-75:]][::-1]

    def diagnostics(self) -> dict[str, Any]:
        healthy = self._unleash_healthy(force=True)
        return {
            **self.config(),
            "unleash_healthy": healthy,
            "health_url": f"{self._server_base_url()}/health",
            "admin_api_url": f"{self._server_base_url()}/api/admin",
            "next_step": (
                "Click Update Unleash Flag, wait about 2 seconds, then simulate users."
                if healthy
                else DEMO_MODE_MESSAGE
            ),
        }

    def _sync_unleash_admin(self, enabled: bool, rollout: int) -> str:
        """Best-effort Admin API sync for the local Docker Unleash server."""
        try:
            self._ensure_feature_exists()
            if enabled:
                self._sync_targeting_strategies(rollout)
                self._set_environment_enabled(True)
            else:
                self._set_environment_enabled(False)
            return "Synced to Unleash Admin API."
        except requests.RequestException as exc:
            return f"Could not reach Unleash Admin API: {exc.__class__.__name__}."
        except Exception as exc:
            return f"Unleash Admin API sync skipped: {exc}."

    def _ensure_feature_exists(self) -> None:
        response = self._admin_request(
            "GET",
            f"/admin/projects/{self.project_id}/features/{FEATURE_NAME}",
            ok=(200, 404),
        )
        if response.status_code == 200:
            return

        self._admin_request(
            "POST",
            f"/admin/projects/{self.project_id}/features",
            json={
                "name": FEATURE_NAME,
                "type": "release",
                "description": "Experimental GPT-5 assistant used by the AI governance demo.",
                "impressionData": True,
            },
            ok=(200, 201, 409),
        )

    def _set_environment_enabled(self, enabled: bool) -> None:
        action = "on" if enabled else "off"
        self._admin_request(
            "POST",
            f"/admin/projects/{self.project_id}/features/{FEATURE_NAME}"
            f"/environments/{self.environment}/{action}",
            ok=(200, 202, 204, 409),
        )

    def _sync_targeting_strategies(self, rollout: int) -> None:
        response = self._admin_request(
            "GET",
            f"/admin/projects/{self.project_id}/features/{FEATURE_NAME}"
            f"/environments/{self.environment}/strategies",
        )
        payload = response.json()
        strategies = payload.get("strategies", []) if isinstance(payload, dict) else payload
        audience_rollouts = {
            "internal": 100,
            "beta": rollout,
            "regular": max(0, (rollout - 50) * 2),
        }
        for audience, audience_rollout in audience_rollouts.items():
            existing = next(
                (
                    strategy for strategy in strategies
                    if any(
                        audience in constraint.get("values", [])
                        for constraint in strategy.get("constraints", [])
                    )
                ),
                None,
            )
            body = {
                "name": "flexibleRollout",
                "title": f"{audience.title()} users",
                "parameters": {
                    "rollout": str(audience_rollout),
                    "stickiness": "userId",
                    "groupId": FEATURE_NAME,
                },
                "constraints": [
                    {"contextName": "userType", "operator": "IN", "values": [audience]}
                ],
                "segments": [],
            }
            path = (
                f"/admin/projects/{self.project_id}/features/{FEATURE_NAME}"
                f"/environments/{self.environment}/strategies"
            )
            if existing:
                self._admin_request("PUT", f"{path}/{existing['id']}", json=body, ok=(200, 202))
            else:
                self._admin_request("POST", path, json=body, ok=(200, 201))

    def _admin_request(
        self,
        method: str,
        path: str,
        ok: tuple[int, ...] = (200,),
        **kwargs: Any,
    ) -> requests.Response:
        response = requests.request(
            method,
            f"{self._server_base_url()}/api{path}",
            headers={
                "Authorization": self.admin_token,
                "Content-Type": "application/json",
            },
            timeout=4,
            **kwargs,
        )
        if response.status_code not in ok:
            raise RuntimeError(f"{method} {path} returned {response.status_code}")
        return response

    def _server_base_url(self) -> str:
        return self.unleash_url.removesuffix("/api")

    def _unleash_healthy(self, force: bool = False) -> bool:
        now = time.monotonic()
        with self._lock:
            if not force and now - self._last_health_checked < 2:
                return self._last_health_status

        try:
            response = requests.get(f"{self._server_base_url()}/health", timeout=0.2)
            healthy = response.status_code == 200
        except requests.RequestException:
            healthy = False

        with self._lock:
            self._last_health_checked = now
            self._last_health_status = healthy
        return healthy

    def _append_log(self, entry: FlagEvaluation) -> None:
        with self._lock:
            self.logs.append(entry)
            self.logs = self.logs[-200:]

    def _evaluation(
        self,
        user_id: str,
        user_type: str,
        enabled: bool,
        reason: str,
        incident: bool,
    ) -> FlagEvaluation:
        model = "GPT-5 Assistant" if enabled else "GPT-4 Assistant"
        latency = (
            720 + self._bucket(user_id, "latency") * 4
            if enabled
            else 380 + self._bucket(user_id, "latency") * 2
        )
        cost = (
            0.028 + self._bucket(user_id, "cost") / 10000
            if enabled
            else 0.009 + self._bucket(user_id, "cost") / 20000
        )
        hallucination = self._bucket(user_id, "hallucination") < (10 if enabled else 4)
        if incident:
            latency += 2400
            cost += 0.12
            hallucination = self._bucket(user_id, "incident-hallucination") < 55
        return FlagEvaluation(
            user_id=user_id,
            user_type=user_type,
            enabled=enabled,
            model=model,
            latency_ms=latency,
            cost_per_request=round(cost, 4),
            hallucination=hallucination,
            incident=incident,
            reason=reason,
            timestamp=self._now(),
        )

    @staticmethod
    def _bucket(user_id: str, salt: str) -> int:
        digest = hashlib.sha256(f"{user_id}:{salt}".encode()).hexdigest()
        return int(digest[:8], 16) % 100

    @staticmethod
    def _validate_user_type(user_type: str) -> str:
        normalized = user_type.strip().lower()
        if normalized not in {"internal", "beta", "regular"}:
            raise ValueError("user_type must be internal, beta, or regular")
        return normalized

    @staticmethod
    def _validate_rollout(rollout: int) -> int:
        if not 0 <= rollout <= 100:
            raise ValueError("rollout must be between 0 and 100")
        return rollout

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

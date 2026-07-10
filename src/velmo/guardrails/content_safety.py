"""Azure AI Content Safety production seam.

Managed moderation (text:analyze) and prompt-injection detection (Prompt Shields,
text:shieldPrompt). Selected by env, like get_kb()/get_fact_store(). Never used
offline: get_moderator() returns None when the endpoint is absent, so the
deterministic detectors carry the whole test suite.
"""

from __future__ import annotations

import os

_API_VERSION = "2024-09-01"
_SEVERITY_BLOCK_THRESHOLD = 2  # FourSeverityLevels: 0 / 2 / 4 / 6
_CATEGORY_MAP = {"Hate": "hate", "Sexual": "sexual", "Violence": "violence", "SelfHarm": "violence"}


class ContentSafetyModerator:
    """Thin client over the Content Safety REST API (httpx, imported lazily)."""

    def __init__(self, endpoint: str, key: str) -> None:
        self._base = endpoint.rstrip("/")
        self._key = key

    def _post(self, path: str, body: dict) -> dict:
        import httpx  # type: ignore[import-untyped]

        response = httpx.post(
            f"{self._base}/contentsafety/{path}?api-version={_API_VERSION}",
            headers={"Ocp-Apim-Subscription-Key": self._key, "Content-Type": "application/json"},
            json=body,
            timeout=5.0,
        )
        response.raise_for_status()
        return response.json()

    def analyze(self, text: str) -> set[str]:
        """Return the guardrail categories whose severity meets the block threshold."""
        data = self._post(
            "text:analyze",
            {
                "text": text,
                "categories": ["Hate", "SelfHarm", "Sexual", "Violence"],
                "outputType": "FourSeverityLevels",
            },
        )
        blocked: set[str] = set()
        for item in data.get("categoriesAnalysis", []):
            if item.get("severity", 0) >= _SEVERITY_BLOCK_THRESHOLD:
                mapped = _CATEGORY_MAP.get(item.get("category", ""))
                if mapped:
                    blocked.add(mapped)
        return blocked

    def shield(self, text: str) -> bool:
        """Return True if Prompt Shields flags the text as a prompt attack."""
        data = self._post("text:shieldPrompt", {"userPrompt": text, "documents": []})
        return bool(data.get("userPromptAnalysis", {}).get("attackDetected", False))


def get_moderator() -> ContentSafetyModerator | None:
    """Return a Content Safety client if configured, else None (offline default)."""
    endpoint = os.getenv("AZURE_CONTENT_SAFETY_ENDPOINT")
    if not endpoint:
        return None
    key = os.getenv("AZURE_CONTENT_SAFETY_KEY") or os.getenv("AZURE_AI_INFERENCE_API_KEY")
    if not key:
        return None
    return ContentSafetyModerator(endpoint, key)

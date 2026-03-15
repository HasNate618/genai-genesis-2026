"""
Runtime helpers for executing markdown-defined agent contracts against Gemini.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib import error, parse, request

DEFAULT_GEMINI_MODEL = "gemini-2.0-flash-lite"
FALLBACK_GEMINI_MODELS: tuple[str, ...] = (
    "gemini-2.0-flash-lite-001",
    "gemini-flash-lite-latest",
    "gemini-2.0-flash",
    "gemini-2.5-flash",
    "gemini-flash-latest",
)
_GEMINI_ENDPOINT_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


class AgentRuntimeError(RuntimeError):
    """Raised when contract execution against Gemini fails."""


def _load_contract_markdown(contract_filename: str) -> str:
    contract_path = Path(__file__).resolve().parent / contract_filename
    if not contract_path.is_file():
        raise AgentRuntimeError(f"Agent contract not found: {contract_filename}")

    contract_text = contract_path.read_text(encoding="utf-8").strip()
    if not contract_text:
        raise AgentRuntimeError(f"Agent contract is empty: {contract_filename}")
    return contract_text


def _build_prompt(contract_text: str, payload: dict[str, Any]) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (
        "Execute this agent contract.\n"
        "Return exactly one JSON object matching the contract output.\n"
        "No prose. No markdown fences.\n\n"
        "=== AGENT CONTRACT ===\n"
        f"{contract_text}\n\n"
        "=== INPUT JSON ===\n"
        f"{payload_json}\n\n"
    )


def _call_gemini(prompt: str, gemini_key: str, model: str) -> dict[str, Any]:
    if not gemini_key:
        raise AgentRuntimeError("Gemini API key is required for contract execution.")

    endpoint = _GEMINI_ENDPOINT_TEMPLATE.format(
        model=parse.quote(model, safe=""),
        key=parse.quote(gemini_key, safe=""),
    )
    body = json.dumps(
        {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "maxOutputTokens": 1024,
            },
        }
    ).encode("utf-8")

    req = request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            with request.urlopen(req, timeout=60) as response:
                response_text = response.read().decode("utf-8", errors="replace")
            break
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            detail_lower = detail.lower()
            quota_exceeded = "quota exceeded" in detail_lower or "limit: 0" in detail_lower
            retryable = exc.code in {429, 500, 503}
            if quota_exceeded:
                raise AgentRuntimeError(
                    "Gemini quota exceeded for this key/project. "
                    f"Model={model}. Details: {detail[:500]}"
                ) from exc
            if retryable and attempt < max_attempts:
                time.sleep(1.5 * (2 ** (attempt - 1)))
                continue
            raise AgentRuntimeError(
                f"Gemini HTTP error ({exc.code}) while running contract (model={model}): {detail[:500]}"
            ) from exc
        except error.URLError as exc:
            if attempt < max_attempts:
                time.sleep(1.5 * (2 ** (attempt - 1)))
                continue
            raise AgentRuntimeError(f"Gemini request failed: {exc.reason}") from exc
        except TimeoutError as exc:
            if attempt < max_attempts:
                time.sleep(1.5 * (2 ** (attempt - 1)))
                continue
            raise AgentRuntimeError("Gemini request timed out while running contract.") from exc

    if not response_text.strip():
        raise AgentRuntimeError("Gemini returned an empty HTTP response body.")

    try:
        return json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise AgentRuntimeError("Gemini returned invalid JSON in HTTP response body.") from exc


def _extract_candidate_text(response_body: dict[str, Any]) -> str:
    candidates = response_body.get("candidates") or []
    if not candidates:
        prompt_feedback = response_body.get("promptFeedback")
        raise AgentRuntimeError(
            f"Gemini returned no candidates. promptFeedback={json.dumps(prompt_feedback, ensure_ascii=False)}"
        )

    first = candidates[0] or {}
    parts = ((first.get("content") or {}).get("parts") or [])
    text = "".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()
    if not text:
        raise AgentRuntimeError("Gemini returned an empty candidate text response.")
    return text


def _parse_agent_json(response_text: str) -> dict[str, Any]:
    attempts: list[str] = [response_text.strip()]
    attempts.extend(match.strip() for match in _JSON_FENCE_PATTERN.findall(response_text))

    first_open = response_text.find("{")
    last_close = response_text.rfind("}")
    if 0 <= first_open < last_close:
        attempts.append(response_text[first_open : last_close + 1].strip())

    seen: set[str] = set()
    for candidate in attempts:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    raise AgentRuntimeError(
        f"Agent returned invalid JSON output. Raw text excerpt: {response_text[:500]}"
    )


async def run_contract_agent(
    contract_filename: str,
    payload: dict[str, Any],
    gemini_key: str,
    model: str | None = None,
) -> dict[str, Any]:
    """Execute a markdown contract with Gemini and return parsed JSON output."""

    contract_text = _load_contract_markdown(contract_filename)
    prompt = _build_prompt(contract_text, payload)

    ordered_models: list[str] = []
    if model:
        ordered_models.append(model)
    else:
        ordered_models.append(DEFAULT_GEMINI_MODEL)
        ordered_models.extend(FALLBACK_GEMINI_MODELS)

    # De-duplicate while preserving order.
    deduped_models = list(dict.fromkeys(ordered_models))
    last_error: AgentRuntimeError | None = None

    for candidate_model in deduped_models:
        try:
            response = await asyncio.to_thread(
                _call_gemini,
                prompt,
                gemini_key,
                candidate_model,
            )
            response_text = _extract_candidate_text(response)
            return _parse_agent_json(response_text)
        except AgentRuntimeError as exc:
            last_error = exc
            message = str(exc).lower()
            # Retry other known models only for model-not-found style errors.
            if "not found" in message or "not_found" in message:
                continue
            raise

    if last_error is not None:
        raise last_error
    raise AgentRuntimeError("Gemini contract execution failed for unknown reason.")

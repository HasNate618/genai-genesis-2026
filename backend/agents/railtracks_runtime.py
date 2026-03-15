"""Railtracks-backed runtime adapter for markdown-defined agent contracts."""

from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from backend.agents.railtracks_tools import build_tool_nodes

DEFAULT_GEMINI_MODEL = "gemini-2.0-flash-lite"
_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_CONTRACT_ROLE_MAP = {
    "planning_agent.md": "planner",
    "task_coordinator_agent.md": "task_coordinator",
    "conflict_analysis_agent.md": "conflict_analyst",
    "coding_agent.md": "coding_agent",
    "merge_agent.md": "merge_agent",
    "qa_agent.md": "qa_agent",
}


class RailtracksRuntimeError(RuntimeError):
    """Raised when Railtracks runtime execution fails."""


def _load_contract_markdown(contract_filename: str) -> str:
    contract_path = Path(__file__).resolve().parent / contract_filename
    if not contract_path.is_file():
        raise RailtracksRuntimeError(f"Agent contract not found: {contract_filename}")
    contract_text = contract_path.read_text(encoding="utf-8").strip()
    if not contract_text:
        raise RailtracksRuntimeError(f"Agent contract is empty: {contract_filename}")
    return contract_text


def _build_prompt(payload: dict[str, Any]) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (
        "Execute the contract using available tools as needed.\n"
        "Return exactly one JSON object matching the contract output.\n"
        "No prose. No markdown fences.\n\n"
        "=== INPUT JSON ===\n"
        f"{payload_json}\n"
    )


def _build_system_message(contract_text: str) -> str:
    return (
        "You are a strict contract executor.\n"
        "Follow the contract and output schema exactly.\n"
        "Never emit text outside the requested JSON object.\n\n"
        "=== AGENT CONTRACT ===\n"
        f"{contract_text}\n"
    )


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

    raise RailtracksRuntimeError(
        f"Railtracks agent returned invalid JSON output. Raw excerpt: {response_text[:500]}"
    )


@contextmanager
def _temporary_env(name: str, value: str):
    previous = os.getenv(name)
    if value:
        os.environ[name] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


def _resolve_model(model: str | None) -> str:
    if model:
        return model
    configured = (os.getenv("AGENTIC_ARMY_GEMINI_MODEL") or "").strip()
    return configured or DEFAULT_GEMINI_MODEL


async def run_railtracks_agent(
    contract_filename: str,
    payload: dict[str, Any],
    gemini_key: str,
    *,
    model: str | None = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Execute a markdown agent contract through Railtracks and parse JSON output."""
    if not gemini_key:
        raise RailtracksRuntimeError("Gemini API key is required for Railtracks runtime.")

    try:
        import railtracks as rt
    except Exception as exc:  # pragma: no cover - exercised by runtime environments
        raise RailtracksRuntimeError(
            "Railtracks package is not available. Install `railtracks` to use railtracks runtime mode."
        ) from exc

    contract_text = _load_contract_markdown(contract_filename)
    role = _CONTRACT_ROLE_MAP.get(contract_filename, "planner")
    llm_model = _resolve_model(model)
    tool_nodes = build_tool_nodes(rt=rt, role=role, agent_id=agent_id)
    prompt = _build_prompt(payload)
    system_message = _build_system_message(contract_text)

    try:
        with _temporary_env("GEMINI_API_KEY", gemini_key):
            agent = rt.agent_node(
                name=f"{role}-agent",
                llm=rt.llm.GeminiLLM(llm_model),
                system_message=system_message,
                tool_nodes=tool_nodes,
            )
            result = await rt.call(agent, prompt)
    except Exception as exc:
        raise RailtracksRuntimeError(f"Railtracks execution failed for role '{role}': {exc}") from exc

    response_text = getattr(result, "text", None)
    if not isinstance(response_text, str) or not response_text.strip():
        response_text = str(result)
    return _parse_agent_json(response_text)

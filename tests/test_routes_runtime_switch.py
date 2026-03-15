import asyncio

from backend.api import routes


def _request() -> routes.JobCreateReq:
    return routes.JobCreateReq(
        goal="Integrate runtime switch safely.",
        coder_count=2,
        gemini_key="live-key",
        moorcheh_key="",
    )


def test_agent_runtime_mode_defaults_to_contract(monkeypatch) -> None:
    monkeypatch.delenv("AGENTIC_ARMY_AGENT_RUNTIME", raising=False)
    assert routes._agent_runtime_mode() == "contract"


def test_agent_runtime_mode_accepts_railtracks(monkeypatch) -> None:
    monkeypatch.setenv("AGENTIC_ARMY_AGENT_RUNTIME", "railtracks")
    assert routes._agent_runtime_mode() == "railtracks"


def test_planning_uses_railtracks_when_mode_enabled(monkeypatch) -> None:
    req = _request()

    async def fake_railtracks(contract_filename, payload, gemini_key, *, model=None, agent_id=None):
        del contract_filename, payload, gemini_key, model, agent_id
        return {"plan": "railtracks-generated-plan"}

    async def fail_contract(*_args, **_kwargs):
        raise AssertionError("Contract runtime should not be called in railtracks mode.")

    monkeypatch.setenv("AGENTIC_ARMY_AGENT_RUNTIME", "railtracks")
    monkeypatch.setattr(routes, "run_railtracks_agent", fake_railtracks)
    monkeypatch.setattr(routes, "run_contract_agent", fail_contract)

    result = asyncio.run(routes._run_planning_agent(req, plan_round=1, feedback="", revision_source="none"))
    assert result == "railtracks-generated-plan"


def test_planning_uses_contract_when_mode_disabled(monkeypatch) -> None:
    req = _request()

    async def fake_contract(contract_filename, payload, gemini_key, *, model=None):
        del contract_filename, payload, gemini_key, model
        return {"plan": "contract-generated-plan"}

    async def fail_railtracks(*_args, **_kwargs):
        raise AssertionError("Railtracks runtime should not be called in contract mode.")

    monkeypatch.setenv("AGENTIC_ARMY_AGENT_RUNTIME", "contract")
    monkeypatch.setattr(routes, "run_contract_agent", fake_contract)
    monkeypatch.setattr(routes, "run_railtracks_agent", fail_railtracks)

    result = asyncio.run(routes._run_planning_agent(req, plan_round=1, feedback="", revision_source="none"))
    assert result == "contract-generated-plan"

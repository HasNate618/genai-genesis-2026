"""
AgenticArmy API Routes
3-Phase Agent Workflow Implementation
"""
import uuid
import asyncio
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1")

# ── In-memory job store ───────────────────────────────────────────
_jobs: dict[str, dict] = {}

# Event locks for the double human-in-the-loop gates
_plan_events: dict[str, asyncio.Event] = {}
_result_events: dict[str, asyncio.Event] = {}


# ── Schemas ───────────────────────────────────────────────────────
class JobCreateReq(BaseModel):
    goal: str
    coder_count: int = 2
    gemini_key: str
    moorcheh_key: Optional[str] = ""


class ReviewReq(BaseModel):
    approved: bool
    feedback: Optional[str] = ""


# ── Helpers ───────────────────────────────────────────────────────
def _new_job(goal: str, coder_count: int) -> dict:
    return {
        "goal": goal,
        "coder_count": coder_count,
        "status": "initializing",
        "logs": [],
        "plan": None,
        "plan_feedback": None,
        "result_feedback": None,
        "agent_states": {
            "planner": "idle",
            "conflict_manager": "idle",
            "coder": "idle",
            "verification": "idle",
        },
        "created_at": datetime.utcnow().isoformat(),
    }


def _log(job: dict, message: str) -> None:
    ts = datetime.utcnow().strftime("%H:%M:%S")
    job["logs"].append(f"[{ts}] {message}")


# ── Routes ────────────────────────────────────────────────────────
@router.get("/health")
async def health():
    """Health check ping."""
    return {"status": "ok", "service": "agentic-army-v1"}


@router.post("/jobs")
async def start_job(req: JobCreateReq):
    """
    Step 1: Goal Input
    Spins up the Planner Agent in a background task.
    """
    job_id = str(uuid.uuid4())
    job = _new_job(req.goal, req.coder_count)
    _jobs[job_id] = job
    
    _plan_events[job_id] = asyncio.Event()
    _result_events[job_id] = asyncio.Event()

    # Fire-and-forget Phase 1 pipeline
    asyncio.create_task(_run_pipeline(job_id, req))

    return {"job_id": job_id}


@router.get("/jobs/{job_id}/plan")
async def get_plan(job_id: str):
    """
    Step 2: Plan Generation
    Extension polls this until plan is not null. status will be 'awaiting_plan_approval'.
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    return {
        "status": job["status"],
        "plan": job["plan"]
    }


@router.post("/jobs/{job_id}/plan/review")
async def review_plan(job_id: str, req: ReviewReq):
    """
    Step 3: Plan Review (HitL 1)
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job["plan_approved"] = req.approved
    job["plan_feedback"] = req.feedback
    
    event = _plan_events.get(job_id)
    if event:
        event.set()

    return {"ok": True, "approved": req.approved}


@router.get("/jobs/{job_id}/status")
async def get_status(job_id: str):
    """
    Step 4-6: Execution Polling
    Poll pipeline status, logs, and agent states.
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "status": job["status"],
        "logs": job["logs"],
        "agentStates": job["agent_states"],
    }


@router.post("/jobs/{job_id}/result/review")
async def review_result(job_id: str, req: ReviewReq):
    """
    Step 7: Final Delivery Review (HitL 2)
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job["result_approved"] = req.approved
    job["result_feedback"] = req.feedback
    
    event = _result_events.get(job_id)
    if event:
        event.set()

    return {"ok": True, "approved": req.approved}


# ── 3-Phase Mock Pipeline ─────────────────────────────────────────
async def _run_pipeline(job_id: str, req: JobCreateReq):
    """
    Advanced state machine mock for 3-Phase pipeline with branch/PR mock output
    and human-in-the-loop gates.
    """
    job = _jobs[job_id]
    plan_event = _plan_events[job_id]
    result_event = _result_events[job_id]

    try:
        # ==========================================
        # PHASE 1: THE PLANNING LOOP
        # ==========================================
        while True:
            job["status"] = "planning"
            job["agent_states"]["planner"] = "running"
            
            if job.get("plan_feedback"):
                _log(job, f"🧠 Planner refining plan based on feedback: '{job['plan_feedback'][:50]}...'")
                await asyncio.sleep(2)  # Refinement delay
            else:
                _log(job, f"🧠 Planner starting for goal: {req.goal[:80]}...")
                await asyncio.sleep(2)  # Generation delay
                
            stub_plan = (
                f"## Technical Roadmap\n\n"
                f"**Goal:** {req.goal}\n\n"
                f"**Execution Tasks:**\n"
                f"1. Setup isolated branch `feature/{job_id[:8]}`\n"
                f"2. Implement changes (allocated to {req.coder_count} agents)\n"
                f"3. Run Verification QA suite over PR diffs\n"
            )
            job["plan"] = stub_plan
            job["agent_states"]["planner"] = "done"
            _log(job, "✓ Technical roadmap generated")

            # HitL Gate 1: Plan Approval
            job["status"] = "awaiting_plan_approval"
            _log(job, "⏳ Waiting for human Plan Approval...")
            
            plan_event.clear()
            await plan_event.wait()

            if job.get("plan_approved"):
                _log(job, "✅ Plan approved! Advancing to Execution phase.")
                break
            else:
                _log(job, "❌ Plan denied. Looping back to Planner.")
                
        # ==========================================
        # PHASE 2: EXECUTION & VERIFICATION
        # ==========================================
        # Step 4: Task Coordination
        while True:
            job["status"] = "coordinating"
            job["agent_states"]["conflict_manager"] = "running"
            
            if job.get("result_feedback"):
                _log(job, f"🎯 Conflict Manager adjusting tasks based on final review feedback: '{job['result_feedback'][:50]}...'")
            else:
                _log(job, "🎯 Conflict Manager querying Moorcheh for semantic context...")
                await asyncio.sleep(1)
                _log(job, f"🎯 Chunking plan into specific assignments for {req.coder_count} Coder(s)...")
                
            await asyncio.sleep(1.5)
            job["agent_states"]["conflict_manager"] = "done"

            # Step 5: Parallel Coding
            job["status"] = "coding"
            job["agent_states"]["coder"] = "running"
            _log(job, f"💻 Coders checking out new Git branch: `feature/agentic-{job_id[:6]}`")
            await asyncio.sleep(1)
            _log(job, f"💻 {req.coder_count} Coder agent(s) executing isolated changes...")
            await asyncio.sleep(3)
            _log(job, "💻 Committing changes & generating mock Pull Request against `main`.")
            job["agent_states"]["coder"] = "done"

            # Step 6: Automated QA Verification
            job["status"] = "verifying"
            job["agent_states"]["verification"] = "running"
            _log(job, "🧪 Verification Agent running test suites & linters on PR...")
            await asyncio.sleep(2)
            
            # (Simulating an easy pass here for the mock)
            _log(job, "✓ Branch tests passed.")
            job["agent_states"]["verification"] = "done"
        
            # ==========================================
            # PHASE 3: FINAL DELIVERY
            # ==========================================
            job["status"] = "review_ready"
            _log(job, "⏳ PR ready! Waiting for Final Human Review...")
            
            result_event.clear()
            await result_event.wait()
            
            if job.get("result_approved"):
                _log(job, "✅ PR Approved! Merging directly into `main`...")
                await asyncio.sleep(1)
                _log(job, "✓ Merge complete. Cleaning up branch.")
                break
            else:
                _log(job, "❌ PR Denied with feedback. Looping back to Conflict Manager...")
                # The while True loop will handle the repeat
            
        # Finish
        job["status"] = "done"
        _log(job, "🎉 Feature successfully integrated. Pipeline complete!")

    except Exception as e:
        job["status"] = "failed"
        _log(job, f"☠️ Pipeline critical error: {str(e)}")
        for agent in job["agent_states"]:
            if job["agent_states"][agent] == "running":
                job["agent_states"][agent] = "error"

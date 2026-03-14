# Shared Project Memory (SPM) — Project Overview

**GenAI Genesis 2026 Hackathon Submission**

---

## What We Are Building

**Shared Project Memory (SPM)** is middleware that lets multiple autonomous AI coding agents collaborate on the same codebase without stomping on each other's work. It acts as a shared brain that any agent — Cursor, Devin, Aider, or a custom LLM loop — can read from and write to via a simple REST API.

---

## The Problem

Modern AI coding agents operate in isolation. When two agents work on the same project simultaneously, the result is duplicated effort, conflicting edits, and lost architectural decisions. Today, a human resolves every collision manually. SPM eliminates this friction with a coordination protocol that is agent-framework agnostic.

---

## The Solution

SPM sits between client agents and the shared repository. It provides four core capabilities:

| Capability | What It Does |
|---|---|
| **Task Coordination** | Tracks who is doing what; prevents two agents from claiming the same work |
| **Conflict Detection** | Scores collision risk before an agent touches a file (file overlap + dependency graph + semantic similarity) |
| **Shared Memory** | Stores plans, decisions, and file-change intents in Moorcheh for semantic retrieval by any agent |
| **Memory Compaction** | Periodically summarizes old records so context stays lean and retrieval stays fast |

---

## Why This Wins Two Prize Tracks

### Bitdeer — "Beyond the Prototype"
SPM is production-grade middleware: typed Python, FastAPI, Pydantic schemas, Docker packaging, structured logging, graceful degradation, and an OpenAPI contract. It solves a real, daily pain point for any team running multiple AI agents.

### Moorcheh — "Efficient Memory"
Multi-agent workflows generate memory at O(agents × tasks × actions) rate. SPM uses Moorcheh's MIB+ITS stack (32× compression, deterministic exhaustive search) as its semantic memory layer, then applies an application-level compaction loop on top. The demo proves this with concrete compression ratios, retrieval latency numbers, and grounding accuracy metrics.

**Pitch:** *Memory-in-a-Box becomes a multi-agent brain.*

---

## System at a Glance

```
┌─────────────────────────────────────────────────┐
│           External Client Agents                │
│     (Cursor / Aider / Devin / Custom loops)     │
└──────────────────┬──────────────────────────────┘
                   │  REST API calls
┌──────────────────▼──────────────────────────────┐
│         SPM Infrastructure Agents               │
│  ┌─────────────────┐  ┌─────────────────────┐  │
│  │ Task Coordinator│  │ Conflict Detector   │  │
│  └─────────────────┘  └─────────────────────┘  │
│  ┌─────────────────┐  ┌─────────────────────┐  │
│  │ Context Query   │  │ Memory Compactor    │  │
│  └─────────────────┘  └─────────────────────┘  │
│  ┌─────────────────┐                           │
│  │ Merge Validator │                           │
│  └─────────────────┘                           │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│       Memory Layer (Moorcheh + SQLite)          │
│  Semantic memory (Moorcheh) + fast index (SQL)  │
└─────────────────────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│      Streamlit Dashboard (Human Supervisor)     │
│  Claims board · Conflict log · Memory stats     │
│  Query console · HITL decision queue            │
└─────────────────────────────────────────────────┘
```

---

## Five Infrastructure Agents

| Agent | Role |
|---|---|
| **Task Coordinator** | Approves, queues, or rejects task claims; owns execution order |
| **Conflict Detector** | Computes a 3-channel risk score (file overlap × 0.5, dependency graph × 0.3, semantic similarity × 0.2) |
| **Context Query** | Answers natural-language questions against shared memory with citations |
| **Memory Compactor** | Clusters old low-importance records and summarizes them via LLM |
| **Merge Validator** | Runs ordered safety checks before work enters the shared workspace |

---

## Key Metrics Demonstrated in the Demo

- **Conflict prevention rate** — fraction of would-be collisions caught before they happen
- **Compression ratio** — raw events reduced by 5–10× at the application layer (on top of Moorcheh's 32×)
- **Retrieval latency** — P50/P95 Moorcheh query time before and after compaction
- **Grounding rate** — fraction of context answers backed by valid cited records

---

## 36-Hour Build Plan (Summary)

| Hours | Milestone |
|---|---|
| 0–2 | Scaffolding, environment, Moorcheh SDK validation |
| 2–6 | Memory layer: `store.py`, `index.py`, `schemas.py` |
| 6–12 | Coordination + conflict detection engines |
| 12–16 | FastAPI server wiring everything together |
| 16–20 | Compaction loop + LLM summarizer |
| 20–26 | Streamlit dashboard + metrics collection |
| 26–30 | Demo scripts + benchmark tooling |
| 30–34 | Integration tests, Docker packaging, README |
| 34–36 | Demo rehearsal, metrics capture, presentation |

---

## For the Full Technical Plan

See [`PLAN.md`](./PLAN.md) for architecture diagrams, agent profiles with flowcharts, memory schemas, conflict detection algorithm, compaction strategy, file structure, demo script, and risk mitigations.

"""
Three-channel conflict detector.

Channels and weights:
  - File overlap (deterministic, weight 0.5): exact path intersection via SQLite
  - Dependency overlap (deterministic, weight 0.3): shared dependency edges in SQLite
  - Semantic overlap (probabilistic, weight 0.2): Moorcheh similarity search

Composite risk score = sum(channel_score * weight).
  >= CONFLICT_BLOCK_THRESHOLD  → block + re-plan
  >= CONFLICT_WARN_THRESHOLD   → warn + suggest order
  <  CONFLICT_WARN_THRESHOLD   → proceed

Usage::

    detector = ConflictDetector(store, index)
    result = await detector.check(
        agent_id="agent-b",
        task_id="db-opt",
        file_paths=["src/session.py"],
        intent_text="Optimise DB queries in session management",
    )
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.config import settings
from src.memory.index import SQLiteIndex
from src.memory.schemas import MemoryRecord, STATUS_OPEN, STATUS_IN_PROGRESS
from src.memory.store import MemoryStore

logger = logging.getLogger(__name__)

_WEIGHT_FILE = 0.5
_WEIGHT_DEP = 0.3
_WEIGHT_SEMANTIC = 0.2


class ConflictDetector:
    """Detect conflicts between a proposed change and existing open intents."""

    def __init__(self, store: MemoryStore, index: SQLiteIndex) -> None:
        self._store = store
        self._index = index

    async def check(
        self,
        *,
        agent_id: str,
        task_id: str,
        file_paths: list[str],
        intent_text: str,
    ) -> dict[str, Any]:
        """
        Check a proposed task/file-change intent for conflicts.

        Returns a dict with keys:
            ``action``          : "proceed" | "warn" | "block"
            ``risk_score``      : float 0..1
            ``channel_scores``  : dict with per-channel scores
            ``conflicting_ids`` : list of record IDs in conflict
            ``recommendation``  : human-readable guidance
        """
        file_score, file_conflicts = self._check_file_overlap(
            agent_id, file_paths
        )
        dep_score, dep_conflicts = self._check_dependency_overlap(file_paths)
        semantic_score, semantic_conflicts = await self._check_semantic_overlap(
            agent_id, intent_text
        )

        composite = (
            file_score * _WEIGHT_FILE
            + dep_score * _WEIGHT_DEP
            + semantic_score * _WEIGHT_SEMANTIC
        )

        all_conflicts = list(
            {*file_conflicts, *dep_conflicts, *semantic_conflicts}
        )

        channel_scores = {
            "file_overlap": round(file_score, 3),
            "dependency_overlap": round(dep_score, 3),
            "semantic_overlap": round(semantic_score, 3),
        }

        if composite >= settings.conflict_block_threshold:
            action = "block"
            recommendation = (
                f"HIGH RISK (score={composite:.2f}): Your proposed changes to "
                f"{file_paths} conflict with active work by other agents. "
                "Wait for conflicting tasks to complete before proceeding."
            )
        elif composite >= settings.conflict_warn_threshold:
            action = "warn"
            recommendation = (
                f"MODERATE RISK (score={composite:.2f}): Potential overlap with "
                f"active changes to {file_paths}. Coordinate with other agents "
                "or sequence your work carefully."
            )
        else:
            action = "proceed"
            recommendation = (
                f"LOW RISK (score={composite:.2f}): No significant conflicts "
                "detected. Proceed with your changes."
            )

        result: dict[str, Any] = {
            "action": action,
            "risk_score": round(composite, 4),
            "channel_scores": channel_scores,
            "conflicting_ids": all_conflicts,
            "recommendation": recommendation,
        }

        # Persist the conflict alert for auditing if risk is non-trivial
        if action in ("warn", "block"):
            alert = MemoryRecord.conflict_alert(
                project_id=self._store.project_id,
                workspace_id=self._store.workspace_id,
                agent_id=agent_id,
                conflicting_record_ids=all_conflicts,
                risk_score=composite,
                recommendation=recommendation,
                channel_scores=channel_scores,
            )
            await self._store.upsert(alert, use_shared=True)
            self._index.upsert(alert)
            result["alert_record_id"] = alert.id

        logger.info(
            "Conflict check: agent=%s task=%s action=%s score=%.3f",
            agent_id,
            task_id,
            action,
            composite,
        )
        return result

    # ── Channel 1: File overlap ───────────────────────────────────────────────

    def _check_file_overlap(
        self, agent_id: str, file_paths: list[str]
    ) -> tuple[float, list[str]]:
        """
        Check whether any of the proposed file paths are already touched by
        another agent's open intent.
        """
        conflict_ids: list[str] = []
        for fp in file_paths:
            rows = self._index.find_by_file_path(fp, status=STATUS_IN_PROGRESS)
            rows += self._index.find_by_file_path(fp, status=STATUS_OPEN)
            for row in rows:
                if row["agent_id"] != agent_id:
                    conflict_ids.append(row["id"])

        score = 1.0 if conflict_ids else 0.0
        return score, conflict_ids

    # ── Channel 2: Dependency overlap ─────────────────────────────────────────

    def _check_dependency_overlap(
        self, file_paths: list[str]
    ) -> tuple[float, list[str]]:
        """
        Check for dependency-edge records that link proposed files to files
        already being modified by other agents.

        A dependency edge record has payload keys ``source`` and ``target``.
        """
        all_open_files: set[str] = set()
        open_records = self._index._conn.execute(
            """
            SELECT file_path FROM records
            WHERE file_path IS NOT NULL
              AND status IN ('open', 'in_progress')
              AND record_type = 'file_change_intent'
            """
        ).fetchall()
        for row in open_records:
            all_open_files.add(row[0])

        # Check if any proposed file imports something that is being changed,
        # or vice versa, using dependency_edge records
        dep_edges = self._index._conn.execute(
            "SELECT * FROM records WHERE record_type = 'dependency_edge'"
        ).fetchall()

        conflict_ids: list[str] = []
        for edge in dep_edges:
            payload = json.loads(edge["payload_json"] or "{}")
            source = payload.get("source", "")
            target = payload.get("target", "")
            # If a proposed file depends on (or is depended upon by) an open file
            if (source in file_paths and target in all_open_files) or (
                target in file_paths and source in all_open_files
            ):
                conflict_ids.append(edge["id"])

        score = min(1.0, len(conflict_ids) * 0.5) if conflict_ids else 0.0
        return score, conflict_ids

    # ── Channel 3: Semantic overlap ───────────────────────────────────────────

    async def _check_semantic_overlap(
        self, agent_id: str, intent_text: str
    ) -> tuple[float, list[str]]:
        """
        Query Moorcheh for semantically similar open intents from other agents.
        """
        results = await self._store.search(
            intent_text,
            top_k=settings.retrieval_top_k,
            use_shared=True,
        )

        conflict_ids: list[str] = []
        max_score = 0.0
        for doc in results:
            # Moorcheh result dicts vary by SDK version; try common key names
            sim_score = doc.get("score") or doc.get("similarity") or 0.0
            metadata = doc.get("metadata") or {}
            rec_agent = metadata.get("agent_id") or doc.get("agent_id", "")
            rec_status = metadata.get("status") or doc.get("status", "")
            rec_type = metadata.get("record_type") or doc.get("record_type", "")

            if (
                rec_agent != agent_id
                and rec_status in (STATUS_OPEN, STATUS_IN_PROGRESS)
                and rec_type == "file_change_intent"
                and sim_score >= settings.semantic_similarity_threshold
            ):
                conflict_ids.append(doc.get("id", ""))
                max_score = max(max_score, sim_score)

        return (max_score if conflict_ids else 0.0), conflict_ids

"""
Conflict detection engine with three-channel scoring.

Dependency order: schemas -> store/index -> conflict
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from src.memory.schemas import MemoryRecord, RecordStatus
from src.memory.store import MoorchehStore
from src.memory.index import SQLiteIndex

logger = structlog.get_logger(__name__)

# Risk thresholds
BLOCK_THRESHOLD = 0.7
WARN_THRESHOLD = 0.4

# Channel weights
WEIGHT_FILE = 0.5
WEIGHT_DEP = 0.3
WEIGHT_SEMANTIC = 0.2

# Semantic similarity threshold for a hit
SEMANTIC_HIT_THRESHOLD = 0.3


@dataclass
class ConflictResult:
    risk_score: float
    channels: dict[str, float]
    conflicting_records: list[MemoryRecord]
    recommendation: str  # "proceed" | "warn" | "block"
    suggested_order: list[str]


class ConflictDetector:
    def __init__(self, store: MoorchehStore, index: SQLiteIndex) -> None:
        self._store = store
        self._index = index

    def detect(
        self,
        new_intent_record: MemoryRecord,
        existing_intents: list[MemoryRecord] | None = None,
    ) -> ConflictResult:
        """
        Detect conflicts for a new file_change_intent record using three channels.
        """
        payload = new_intent_record.payload
        new_files: list[str] = payload.get("file_paths", [])

        # ---------------------------------------------------------------
        # Channel 1: File overlap (weight 0.5)
        # ---------------------------------------------------------------
        file_score, file_conflicts = self._file_overlap_score(new_files)

        # ---------------------------------------------------------------
        # Channel 2: Dependency overlap (weight 0.3)
        # ---------------------------------------------------------------
        dep_score, dep_conflicts = self._dependency_overlap_score(new_files)

        # ---------------------------------------------------------------
        # Channel 3: Semantic overlap (weight 0.2)
        # ---------------------------------------------------------------
        sem_score, sem_conflicts = self._semantic_overlap_score(
            new_intent_record, existing_intents
        )

        composite = (
            WEIGHT_FILE * file_score
            + WEIGHT_DEP * dep_score
            + WEIGHT_SEMANTIC * sem_score
        )

        # Deduplicate conflicting records by id
        seen: set[str] = set()
        all_conflicts: list[MemoryRecord] = []
        for r in file_conflicts + dep_conflicts + sem_conflicts:
            if r.id not in seen:
                seen.add(r.id)
                all_conflicts.append(r)

        if composite >= BLOCK_THRESHOLD:
            recommendation = "block"
        elif composite >= WARN_THRESHOLD:
            recommendation = "warn"
        else:
            recommendation = "proceed"

        # Suggested order: existing conflicting records first, then new intent
        suggested_order = [r.id for r in all_conflicts] + [new_intent_record.id]

        result = ConflictResult(
            risk_score=round(composite, 4),
            channels={
                "file_overlap": round(file_score, 4),
                "dependency_overlap": round(dep_score, 4),
                "semantic_overlap": round(sem_score, 4),
            },
            conflicting_records=all_conflicts,
            recommendation=recommendation,
            suggested_order=suggested_order,
        )

        logger.info(
            "conflict.detect",
            record_id=new_intent_record.id,
            risk_score=result.risk_score,
            recommendation=recommendation,
        )
        return result

    # ------------------------------------------------------------------
    # Private channel implementations
    # ------------------------------------------------------------------

    def _file_overlap_score(
        self, new_files: list[str]
    ) -> tuple[float, list[MemoryRecord]]:
        if not new_files:
            return 0.0, []

        all_intents = self._index.find_active_intents_by_files(new_files)
        if not all_intents:
            return 0.0, []

        overlap_ids: set[str] = {row["id"] for row in all_intents}
        score = min(1.0, len(overlap_ids) / max(1, len(new_files)))

        records: list[MemoryRecord] = []
        for rid in list(overlap_ids)[:10]:
            r = self._store.get(rid)
            if r and r.status not in (RecordStatus.done.value, RecordStatus.superseded.value):
                records.append(r)

        return score, records

    def _dependency_overlap_score(
        self, new_files: list[str]
    ) -> tuple[float, list[MemoryRecord]]:
        if not new_files:
            return 0.0, []

        dep_rows = self._index.find_dependency_overlap(new_files)
        if not dep_rows:
            return 0.0, []

        # Gather related files from dependency edges
        related_files: set[str] = set()
        for row in dep_rows:
            related_files.add(row["source_file"])
            related_files.add(row["target_file"])

        # Find intents touching those related files
        related_intents = self._index.find_active_intents_by_files(list(related_files))
        overlap_ids: set[str] = {row["id"] for row in related_intents}

        if not overlap_ids:
            return 0.0, []

        score = min(1.0, len(overlap_ids) * 0.5 / max(1, len(new_files)))

        records: list[MemoryRecord] = []
        for rid in list(overlap_ids)[:5]:
            r = self._store.get(rid)
            if r:
                records.append(r)

        return score, records

    def _semantic_overlap_score(
        self,
        new_intent: MemoryRecord,
        existing_intents: list[MemoryRecord] | None,
    ) -> tuple[float, list[MemoryRecord]]:
        # If existing intents provided, score against them; otherwise use store search
        if existing_intents is None:
            existing_intents = self._store.similarity_search(
                query=new_intent.text,
                top_k=5,
                filters={
                    "record_type": "file_change_intent",
                    "project_id": new_intent.project_id,
                },
            )

        if not existing_intents:
            return 0.0, []

        from src.memory.store import _similarity  # local import to avoid circular

        hits: list[MemoryRecord] = []
        for r in existing_intents:
            if r.id == new_intent.id:
                continue
            sim = _similarity(new_intent.text, r.text)
            if sim >= SEMANTIC_HIT_THRESHOLD:
                hits.append(r)

        if not hits:
            return 0.0, []

        score = min(1.0, len(hits) / max(1, len(existing_intents)))
        return score, hits

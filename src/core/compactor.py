"""
Compaction worker: clusters old low-importance records, summarizes with LLM,
uploads summaries, and deletes originals.

Dependency order: schemas -> store/index -> compactor
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

from src.config import Settings, get_settings
from src.memory.schemas import (
    MemoryRecord,
    RecordType,
    RecordStatus,
    make_record_id,
)
from src.memory.store import MoorchehStore
from src.memory.index import SQLiteIndex

logger = structlog.get_logger(__name__)


@dataclass
class CompactionResult:
    records_before: int
    records_after: int
    chars_before: int
    chars_after: int
    compression_ratio: float
    clusters_formed: int
    duration_seconds: float


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# LLM summarizer with rule-based fallback
# ---------------------------------------------------------------------------

def _llm_summarize(texts: list[str], settings: Settings) -> str:
    """Try OpenAI; fall back to rule-based concatenation."""
    if not texts:
        return ""

    if settings.llm_provider == "openai" and settings.openai_api_key:
        try:
            from openai import OpenAI  # type: ignore

            client = OpenAI(api_key=settings.openai_api_key)
            prompt = (
                "You are a technical memory compactor for a multi-agent coding system. "
                "Summarize the following agent activity records into a single concise paragraph "
                "preserving all key decisions, file changes, and outcomes:\n\n"
                + "\n---\n".join(texts[:20])
            )
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
                temperature=0.2,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("compactor.llm_failed", error=str(exc))

    # Rule-based fallback: join key sentences
    combined = " | ".join(t[:120] for t in texts[:10])
    return f"[Compacted summary of {len(texts)} records] {combined}"


# ---------------------------------------------------------------------------
# Clustering helpers
# ---------------------------------------------------------------------------

def _extract_keywords(text: str) -> set[str]:
    """Simple keyword extraction: words longer than 4 chars."""
    import re
    words = re.findall(r"[a-z][a-z0-9_]{3,}", text.lower())
    # Remove common stop words
    stopwords = {
        "task", "agent", "file", "step", "plan", "with", "that", "this",
        "from", "into", "have", "been", "will", "them", "their", "about",
        "record", "recorded", "change", "changes",
    }
    return set(words) - stopwords


def _cluster_records(
    records: list[MemoryRecord],
) -> list[list[MemoryRecord]]:
    """
    Cluster records by task_id first, then keyword overlap.
    Returns a list of clusters (each cluster is a list of records).
    """
    # Group by task_id
    task_groups: dict[str, list[MemoryRecord]] = defaultdict(list)
    for r in records:
        task_id = r.payload.get("task_id", "") or ""
        if task_id:
            task_groups[task_id].append(r)
        else:
            task_groups[f"__notask_{r.id}"].append(r)

    clusters = list(task_groups.values())

    # Merge small clusters (<2 records) with keyword-similar clusters
    final_clusters: list[list[MemoryRecord]] = []
    small: list[MemoryRecord] = []

    for cluster in clusters:
        if len(cluster) >= 2:
            final_clusters.append(cluster)
        else:
            small.extend(cluster)

    if small:
        # Try keyword merging for small orphans
        kw_groups: dict[str, list[MemoryRecord]] = defaultdict(list)
        for r in small:
            keywords = _extract_keywords(r.text)
            key = "_".join(sorted(keywords)[:3]) if keywords else r.id
            kw_groups[key].append(r)

        for group in kw_groups.values():
            final_clusters.append(group)

    return [c for c in final_clusters if c]


# ---------------------------------------------------------------------------
# CompactionWorker
# ---------------------------------------------------------------------------

class CompactionWorker:
    def __init__(
        self,
        store: MoorchehStore,
        index: SQLiteIndex,
        settings: Settings | None = None,
    ) -> None:
        self._store = store
        self._index = index
        self._settings = settings or get_settings()

    def compact(self, project_id: str, workspace_id: str) -> CompactionResult:
        start = time.perf_counter()
        logger.info("compactor.start", project_id=project_id, workspace_id=workspace_id)

        # Fetch compactable records
        candidates = self._store.list_records(
            filters={
                "project_id": project_id,
                "workspace_id": workspace_id,
            }
        )
        compactable = [
            r
            for r in candidates
            if r.status == RecordStatus.done.value
            and r.importance <= self._settings.compaction_importance_max
            and r.record_type != RecordType.summary.value
        ]

        if not compactable:
            logger.info("compactor.nothing_to_compact")
            return CompactionResult(
                records_before=0,
                records_after=0,
                chars_before=0,
                chars_after=0,
                compression_ratio=1.0,
                clusters_formed=0,
                duration_seconds=time.perf_counter() - start,
            )

        records_before = len(compactable)
        chars_before = sum(len(r.text) for r in compactable)

        # Cluster
        clusters = _cluster_records(compactable)

        summary_records: list[MemoryRecord] = []
        ids_to_delete: list[str] = []

        for cluster in clusters:
            texts = [r.text for r in cluster]
            summary_text = _llm_summarize(texts, self._settings)

            summary_id = make_record_id(RecordType.summary.value, project_id)
            topic_tags = list(
                set().union(*[_extract_keywords(t) for t in texts])
            )[:10]
            task_ids = list({r.payload.get("task_id") for r in cluster if r.payload.get("task_id")})

            summary_record = MemoryRecord(
                id=summary_id,
                record_type=RecordType.summary.value,
                project_id=project_id,
                workspace_id=workspace_id,
                agent_id="compactor",
                timestamp=_now_iso(),
                text=summary_text,
                importance=5,
                status=RecordStatus.done.value,
                payload={
                    "compressed_from_ids": [r.id for r in cluster],
                    "topic_tags": topic_tags,
                    "task_ids": task_ids,
                    "original_record_count": len(cluster),
                    "chars_before": sum(len(t) for t in texts),
                    "chars_after": len(summary_text),
                },
            )
            summary_records.append(summary_record)
            ids_to_delete.extend(r.id for r in cluster)

        # Upload summaries
        for sr in summary_records:
            self._store.upsert(sr)

        # Delete originals
        for rid in ids_to_delete:
            self._store.delete(rid)

        chars_after = sum(len(sr.text) for sr in summary_records)
        records_after = len(summary_records)
        ratio = chars_before / max(1, chars_after)

        duration = time.perf_counter() - start
        logger.info(
            "compactor.done",
            records_before=records_before,
            records_after=records_after,
            compression_ratio=round(ratio, 2),
            clusters=len(clusters),
            duration_seconds=round(duration, 2),
        )

        return CompactionResult(
            records_before=records_before,
            records_after=records_after,
            chars_before=chars_before,
            chars_after=chars_after,
            compression_ratio=round(ratio, 4),
            clusters_formed=len(clusters),
            duration_seconds=round(duration, 4),
        )

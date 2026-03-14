"""
Compaction worker — reduces memory footprint by clustering low-importance
historical records and replacing them with LLM-generated summaries.

Algorithm:
  1. Fetch all done/superseded records with importance <= compaction_max_importance
  2. Cluster by (task_id or topic_tags)
  3. For each cluster, call the configured LLM to synthesize a summary
  4. Upload summary MemoryRecord to Moorcheh (importance=5, type=summary)
  5. Delete original raw records from Moorcheh + SQLite
  6. Log compression ratio (chars_before / chars_after)

Key design decisions:
  - High-importance records (importance >= 4) are NEVER compacted
  - Summaries reference ``compressed_from_ids`` for provenance
  - Compaction is idempotent (already-compacted windows are no-ops)
  - Rule-based fallback summarizer if LLM call fails

Usage::

    compactor = Compactor(store, index)
    result = await compactor.run()
    # result: {"clusters_processed": N, "docs_deleted": M, "compression_ratio": X}
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from src.config import settings
from src.memory.index import SQLiteIndex
from src.memory.schemas import (
    MemoryRecord,
    RECORD_TYPE_SUMMARY,
    IMPORTANCE_DECISION,
    make_record_id,
    _now_iso,
)
from src.memory.store import MemoryStore

logger = logging.getLogger(__name__)


# ── LLM Summarizers ───────────────────────────────────────────────────────────


async def _openai_summarize(texts: list[str]) -> str:
    """Use OpenAI to produce a concise summary of a list of memory records."""
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        joined = "\n\n".join(f"- {t}" for t in texts[:20])  # cap to avoid token blowout
        resp = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a concise technical writer. "
                        "Summarize the following agent memory records into a single "
                        "paragraph that captures the key decisions, actions, and "
                        "outcomes. Be specific. Omit filler words."
                    ),
                },
                {"role": "user", "content": joined},
            ],
            max_tokens=256,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        logger.warning("OpenAI summarize failed: %s", exc)
        return _rule_based_summarize(texts)


async def _anthropic_summarize(texts: list[str]) -> str:
    """Use Anthropic to produce a concise summary."""
    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        joined = "\n\n".join(f"- {t}" for t in texts[:20])
        msg = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=256,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Summarize these agent memory records into one concise "
                        f"technical paragraph:\n\n{joined}"
                    ),
                }
            ],
        )
        return msg.content[0].text.strip()
    except Exception as exc:
        logger.warning("Anthropic summarize failed: %s", exc)
        return _rule_based_summarize(texts)


def _rule_based_summarize(texts: list[str]) -> str:
    """Fallback: concatenate and truncate to 512 chars."""
    combined = " | ".join(texts)
    if len(combined) > 512:
        combined = combined[:509] + "..."
    return f"[Rule-based summary] {combined}"


async def _summarize(texts: list[str]) -> str:
    provider = settings.summarizer_provider.lower()
    if provider == "openai":
        return await _openai_summarize(texts)
    if provider == "anthropic":
        return await _anthropic_summarize(texts)
    return _rule_based_summarize(texts)


# ── Compactor ─────────────────────────────────────────────────────────────────


class Compactor:
    """Runs the compaction loop to keep memory footprint bounded."""

    def __init__(self, store: MemoryStore, index: SQLiteIndex) -> None:
        self._store = store
        self._index = index

    async def should_run(self) -> bool:
        """Return True if the event count has reached the compaction threshold."""
        count = self._index.count(self._store.project_id)
        return count >= settings.compaction_trigger_count

    async def run(self) -> dict[str, Any]:
        """
        Execute one compaction pass.

        Returns a summary dict:
            ``clusters_processed`` : number of clusters compacted
            ``docs_deleted``       : number of raw records deleted
            ``compression_ratio``  : chars_before / chars_after
        """
        rows = self._index.find_compactable(
            self._store.project_id, settings.compaction_max_importance
        )
        if not rows:
            logger.info("Compaction: no eligible records found.")
            return {"clusters_processed": 0, "docs_deleted": 0, "compression_ratio": 1.0}

        clusters = self._cluster(rows)
        chars_before = sum(
            len(r.get("payload_json", "")) for r in rows
        )
        chars_after = 0
        docs_deleted = 0

        for cluster_key, cluster_rows in clusters.items():
            texts = self._extract_texts(cluster_rows)
            summary_text = await _summarize(texts)
            chars_after += len(summary_text)

            compressed_ids = [r["id"] for r in cluster_rows]
            summary_record = MemoryRecord(
                id=make_record_id(RECORD_TYPE_SUMMARY, self._store.project_id),
                record_type=RECORD_TYPE_SUMMARY,
                project_id=self._store.project_id,
                workspace_id=self._store.workspace_id,
                agent_id="compactor",
                timestamp=_now_iso(),
                text=summary_text,
                importance=IMPORTANCE_DECISION,  # summaries are preserved
                status="done",
                payload={
                    "cluster_key": cluster_key,
                    "compressed_from_ids": compressed_ids,
                    "original_count": len(cluster_rows),
                },
            )
            await self._store.upsert(summary_record, use_shared=True)
            self._index.upsert(summary_record)

            # Delete originals
            for row in cluster_rows:
                await self._store.delete(row["id"], use_shared=True)
                self._index.delete(row["id"])
                docs_deleted += 1

            logger.info(
                "Compacted cluster '%s': %d records → 1 summary",
                cluster_key,
                len(cluster_rows),
            )

        compression_ratio = (
            round(chars_before / chars_after, 2) if chars_after > 0 else 1.0
        )
        logger.info(
            "Compaction complete: clusters=%d deleted=%d ratio=%.2f",
            len(clusters),
            docs_deleted,
            compression_ratio,
        )
        return {
            "clusters_processed": len(clusters),
            "docs_deleted": docs_deleted,
            "compression_ratio": compression_ratio,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _cluster(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        """
        Group records by task_id (if present) then by record_type.
        Returns {cluster_key: [rows]}.
        """
        clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            task_id = row.get("task_id") or ""
            key = task_id if task_id else row.get("record_type", "misc")
            clusters[key].append(row)
        return dict(clusters)

    @staticmethod
    def _extract_texts(rows: list[dict[str, Any]]) -> list[str]:
        """
        Extract text representations from SQLite rows.
        Falls back to payload_json if a dedicated text column is absent.
        """
        import json

        texts = []
        for row in rows:
            if "text" in row and row["text"]:
                texts.append(row["text"])
            elif row.get("payload_json"):
                try:
                    payload = json.loads(row["payload_json"])
                    texts.append(str(payload))
                except Exception:
                    texts.append(row["payload_json"])
        return texts

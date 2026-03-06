"""Shared type definitions for deep-project scripts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class ConflictInfo:
    """Information about conflicting existing tasks."""

    task_list_id: str
    existing_task_count: int
    sample_subjects: tuple[str, ...]

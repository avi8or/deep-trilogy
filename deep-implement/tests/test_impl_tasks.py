"""Tests for impl_tasks.py - cross-repo TaskStatus sync check."""

from scripts.lib.impl_tasks import TaskStatus


def test_task_status_values_match_cross_repo_canonical():
    """Verify TaskStatus values haven't drifted from the cross-repo canonical set.

    TaskStatus is defined independently in deep-plan and deep-implement.
    This test ensures the values stay in sync by checking against a
    hardcoded canonical set. If this test fails, update the sibling repo
    to match.
    """
    expected = {"pending", "in_progress", "completed"}
    actual = {status.value for status in TaskStatus}
    assert actual == expected, (
        f"Cross-repo sync check failed: TaskStatus values drifted. "
        f"Expected {expected}, got {actual}. "
        f"Update deep-plan's TaskStatus to match, or vice versa."
    )

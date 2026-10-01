"""Claim ordering: priority descending, then oldest first."""

from client.github import Issue
from client.scheduling import order_candidates


def issue(number: int, labels: list[str]) -> Issue:
    return Issue(number=number, title=f"t{number}", body="", state="open",
                 labels=labels, assignees=[])


class TestOrdering:
    def test_priority_desc_then_age_asc(self):
        issues = [
            issue(30, ["choir/available"]),                          # normal
            issue(20, ["choir/available", "choir/priority:low"]),
            issue(40, ["choir/available", "choir/priority:high"]),
            issue(10, ["choir/available"]),                          # normal, older
        ]
        assert [i.number for i in order_candidates(issues)] == [40, 10, 30, 20]

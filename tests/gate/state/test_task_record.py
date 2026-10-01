"""TaskRecord validation for the live task types (prove/golf/index).

Historically covered the type-branched target validation from design
note 11 §6.1 (`review` tasks pointed at a PR via `target_pr` instead of
a file); spec D1 removed the review task type, so every remaining type
takes the same file+decl shape.
"""

import pytest
from pydantic import ValidationError

from gate.state.task_record import ProjectRef, TaskRecord

REF = {"repo": "acme/proofs", "commit": "a" * 40, "toolchain": "leanprover/lean4:v4.31.0"}


def make(**kw) -> TaskRecord:
    base = {"choir-task-version": 1, "project_ref": ProjectRef(**REF), "deps": []}
    return TaskRecord(**{**base, **kw})


class TestProveTasks:
    def test_prove_task_requires_target_file(self):
        with pytest.raises(ValidationError, match="requires target_file"):
            make(type="prove", target_decl="Foo.bar")

    def test_target_decl_with_a_trailing_dot_is_rejected(self):
        # A trailing dot splits to an empty leaf downstream, in
        # `compare_reduction`'s own comparison — reject it at the
        # source rather than rely on that function's fail-closed rule
        # alone.
        with pytest.raises(ValidationError, match="target_decl"):
            make(type="prove", target_file="Foo.lean", target_decl="Foo.bar.")

    def test_target_decl_accepts_unicode_identifiers(self):
        # Lean identifiers routinely use non-ASCII letters (Greek,
        # subscripts); a project using them must still be able to
        # declare a task against one.
        rec = make(type="prove", target_file="Foo.lean", target_decl="NS.α_β")
        assert rec.target_decl == "NS.α_β"

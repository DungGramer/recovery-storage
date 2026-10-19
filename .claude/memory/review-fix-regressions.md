# Patching review findings one by one produced new regressions (2026-10-19)

What happened: review round 1 listed 1 Critical / 8 High / 15 Medium. Fixing each finding directly in code, without
first specifying the fix as tests, introduced new High defects found in round 2 (lookalike accepted at gate close,
stale "secured" state reopening writes, guard tokenizer leaks) and again in the narrow round-2 re-review (tokenizer
fallback swallowing later lines, heredoc bodies fed to a shell ignored, redirect targets confusing `cp`).

Why: the green frozen suite never exercised the new code paths, so "all green" was no evidence for the fixes.

How to apply: for any review round, (1) collapse findings into few mechanisms, (2) have test-designer turn the
reviewer's reproductions into spec tests before code (amendment + re-freeze when the contract changes), (3) re-review
only the changed functions with the reviewer's corpora as acceptance checks, (4) stop after one narrow re-review and
list the rest as open questions.

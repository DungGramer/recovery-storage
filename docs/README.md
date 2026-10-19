# Documentation Index

Docs for the `recovery-storage` Claude Code skill. Repo entry point: [../README.md](../README.md).

| Document | Read it to |
|---|---|
| [project-overview-pdr.md](project-overview-pdr.md) | Understand scope, business rules (risk levels, gates, operator console, data-first, verdicts) and acceptance |
| [system-architecture.md](system-architecture.md) | See components, data flow, gate state machine, guard hook path, platform notes |
| [codebase-summary.md](codebase-summary.md) | Find a module, entry point, dev tool or test area (carries the commit stamp) |
| [code-standards.md](code-standards.md) | Follow the coding, JSON/exit-code, fixture, frozen-suite and Windows rules |
| [project-roadmap.md](project-roadmap.md) | Check phase status |
| [project-changelog.md](project-changelog.md) | See what changed and when |

Not present on purpose: `api-docs.md` (the CLI contract is `recovery-storage/scripts/tests/CONTRACT.md`, and `rs.py --help` lists the commands) and `deployment-guide.md` (install is one command, see the root README).

## Other sources of truth

| Source | Content |
|---|---|
| `recovery-storage/SKILL.md` | Orchestrator instructions the agent follows, including the guard hook limits |
| `recovery-storage/references/` | Playbooks per device class, tools, safety and gates, health signals |
| `recovery-storage/scripts/tests/CONTRACT.md` | Signatures, output keys, exit codes, amendment sections |
| `recovery-storage/scripts/tests/fixtures/SOURCES.md` | Origin of every fixture |
| `plans/20261019-1726-recovery-storage-skill/` | `requirements.md`, `plan.md`, phase files, amendments 01 and 02, research |
| `.claude/frozen-tests.json` | Frozen suite manifest and amendment history |
| `.claude/memory/` | Lessons learned (Windows and tooling traps, review-fix regressions) |

Run `python recovery-storage/scripts/rs.py rules` for the live rule tables and thresholds; docs do not copy them.

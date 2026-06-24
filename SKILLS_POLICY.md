# SKILLS_POLICY.md — ODIN Agent Skill Policy

This policy keeps skill usage deterministic despite many locally installed skills.

## Default Rule

Use the smallest useful skill set. Do not stack skills just because their names match.

When multiple skills could apply, prefer this order:

1. Repo instructions in `AGENTS.md`, `CLAUDE.md`, and local task context.
2. Superpowers skills for engineering workflow discipline.
3. Codex Security skills for repository security scans and validated security fixes.
4. Narrow domain skills only when explicitly requested or clearly relevant.
5. External/community skills only as advisory checklists unless explicitly approved.

## Default Engineering Skills

Use Superpowers as the default for implementation work:

- `superpowers:using-git-worktrees` for isolated feature/fix branches.
- `superpowers:test-driven-development` for feature work, bug fixes, and behavior changes.
- `superpowers:systematic-debugging` for failing tests, runtime bugs, and regressions.
- `superpowers:writing-plans` for multi-step implementation plans.
- `superpowers:executing-plans` for executing an approved written plan.
- `superpowers:verification-before-completion` before claiming work is done.
- `superpowers:finishing-a-development-branch` before merge/PR completion.

These override similarly named community skills such as `tdd`, `review`, or `implement`
unless the user explicitly asks for the community skill.

## Security Skills

Use these only for security-specific tasks:

- Codex Security plugin skills are preferred for repo-wide or scoped security work:
  - `codex-security:security-scan`
  - `codex-security:deep-security-scan`
  - `codex-security:security-diff-scan`
  - `codex-security:triage-finding`
  - `codex-security:fix-finding`
- The installed cybersecurity skills under `.agents/skills` are supplementary checklists.
  Use them only when their scope is exact, for example:
  - `testing-api-security-with-owasp-top-10`
  - `testing-websocket-api-security`
  - `testing-cors-misconfiguration`
  - `testing-for-json-web-token-vulnerabilities`

Never claim exhaustive security coverage from a checklist-only skill. State the scope and
whether the work was code review, SAST, DAST, or runtime validation.

## Matt Pocock Skills

Use Matt Pocock skills for design and planning, not as the default implementation workflow:

- Good default use cases:
  - `codebase-design` for module/interface/seam design.
  - `domain-modeling` and `ubiquitous-language` for shared language and domain clarity.
  - `request-refactor-plan` for turning a refactor idea into a safe sequence.
  - `diagnosing-bugs` when a user asks for a diagnosis loop and we need a tight repro.
  - `to-prd` / `to-issues` when converting rough product ideas into durable artifacts.
- Do not use Matt `tdd`, `review`, or `implement` by default. Prefer Superpowers equivalents.
- Treat `ask-matt`, `grill-me`, `grilling`, and writing-focused skills as explicit-only.

## Explicit-Only Skills

Use these only when the user explicitly asks for them by name or task:

- Bulk cybersecurity exploit/playbook skills.
- Malware, red-team, offensive, credential, phishing, or Active Directory attack skills.
- Writing/editorial skills such as `writing-shape`, `writing-beats`, `writing-fragments`.
- Skills that installer output marks as medium/high risk until inspected manually.

## Collision Rules

If a skill name collides with a stronger project default:

- `tdd` means Superpowers TDD unless the user says "Matt tdd".
- `review` means the repo's normal code-review stance unless the user says "Matt review".
- `debug` means Superpowers systematic debugging unless the user says "Matt diagnosing-bugs".
- `security scan` means Codex Security first; use external security skills only as checklists.

If the user names a skill exactly, use that skill after reading its `SKILL.md`.

## Safety Rules

- Read `SKILL.md` completely before using any selected skill.
- Do not run external network scanners, exploit tools, or intrusive tests without explicit approval.
- Do not add installed skills, generated lockfiles, or skill caches to commits unless requested.
- Do not let a skill override repo rules, secrets handling, git safety, or testing requirements.
- If a skill suggests behavior that conflicts with `AGENTS.md`, follow `AGENTS.md`.

## Reporting

When using non-default skills, say which skill was used and why.

For security reviews, always report:

- Scope reviewed.
- Method used: code review, tests, SAST, DAST, runtime validation.
- Findings with severity and file references.
- Explicit limitations.

For implementation work, always report:

- Files changed.
- Tests/checks run.
- Anything not run and why.

# Repository instructions

## Scope

This repository contains `pt`, a native Zsh plugin for named pentest working
environments. Follow `PLAN.md`; implement small, independently testable milestones.
Do not expand scope into a general shell parser or cross-shell framework.

## Language and style

- Write all code comments, documentation, help, and diagnostics in concise English.
- Prefer clear shell functions and small modules over abstractions.
- Keep command output compact and errors actionable.

## Safety and permissions

- Inspect `git status --short` before editing; preserve unrelated changes.
- Use `apply_patch` for file edits. Do not reset or clean the worktree.
- Do not install packages, modify host configuration, or change live shell/history
  files. Provide user-run commands for installation and rollout.
- Never commit real credentials, customer data, or saved user environments.
- Use synthetic values and temporary directories in tests.
- Never print real environment dumps or enable secret-exposing tracing.

## Behavioral contract

- `pentest.env` is the existing master baseline; never write it.
- Save environments only in the current working directory, explicitly, with
  mode `0600`, atomic replacement, and overwrite protection.
- Never modify home templates through `pt save`.
- Source trusted environment files; do not build a custom dotenv parser.
- Assignments capture values, not dynamic references.
- Restore managed scalar variables and their relevant attributes on deactivation.
  Do not claim rollback of arbitrary sourced shell code.
- Show values in cleartext only through requested status, preview, editing, or
  load confirmation; never print unsolicited environment dumps.
- Do not execute command-buffer content during preview or validation.
- Keep Enter validation configurable and disabled by default.
- Avoid `eval` where direct parameter operations suffice.

## Verification

- Test in isolated `zsh -f` processes with temporary HOME/config/work directories.
- Cover unset/empty/exported states, save/load quoting, cancellation, failures,
  overwrite protection, and repeated activation/deactivation.
- Use pseudoterminal tests for editor and prompt integration.
- Check Zsh syntax and run `git diff --check` before handing off changes.
- Report executed tests separately from untested interactive or VM acceptance.
- Update milestone checkboxes only after their acceptance criteria pass.

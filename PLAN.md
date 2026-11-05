# Development plan

## Scope

Build a native Zsh plugin for temporary, named pentest environments. Keep one
active environment, source trusted files, and save only on explicit request.
The existing `pentest.env` baseline is never written by the plugin.

Keep implementation small and Zsh-specific. Full shell parsing, cross-shell
support, automatic activation, and rollback of arbitrary shell code are outside
scope.

## Completed for the initial version

- [x] MIT license, idempotent plugin loading, and command collision diagnostics.
- [x] Local-file, template, and fresh scratch activation with scalar restoration.
- [x] Literal and interactive assignments, explicit unsets, status, and renaming.
- [x] Variable editing with isolated validation and missing-variable placeholders.
- [x] Atomic saves with mode `0600`, overwrite confirmation, and path protections.
- [x] Merge loading with per-variable confirmation, force flags, and rollback.
- [x] Optional simple and Powerlevel10k prompt integration.
- [x] Command preview without buffer execution or history insertion.
- [x] Optional Enter guard with automatic variable detection and explicit bypass.
- [x] Emacs and vi bindings, preview dismissal, and guarded-command cancellation.
- [x] Native history recall and optional Atuin cancellation recording.
- [x] Completion for commands, names, options, and managed variable names.
- [x] Isolated unit, pseudoterminal, and optional integration tests.
- [x] Manual acceptance with Sheldon and vi bindings, reported by the maintainer.
- [x] Installation, workflow, restoration, and history documentation.

The command reference and behavioral details live in [README.md](README.md).
The repeatable manual checklist lives in [docs/acceptance.md](docs/acceptance.md).

## Code organization

| File | Responsibility |
| --- | --- |
| `pt.plugin.zsh` | Module loading, command registration, completion setup |
| `lib/state.zsh` | Scalar capture, change tracking, and restoration |
| `lib/environments.zsh` | File lookup, activation, merging, and deactivation |
| `lib/commands.zsh` | Assignment, status, renaming, saving, listing, and dispatch |
| `lib/edit.zsh`, `lib/edit-worker.zsh` | Editor files, isolated evaluation, value import |
| `lib/inspect.zsh` | Limited variable inspection and preview rendering |
| `lib/editor.zsh` | ZLE widgets, guard state, keymaps, and cancellation |
| `lib/completion.zsh`, `completions/_pt` | Completion candidates and integration |
| `lib/output.zsh` | Compact diagnostics and color policy |

## Verification

- 85 automated tests passed on Zsh 5.9.2. The private tmux screen test runs
  separately from the normal suite.
- Coverage includes unset/empty/exported states, scalar attributes, quoting,
  save/load roundtrips, merge decisions, cancellation, and failure restoration.
- Integration checks cover Sheldon, Powerlevel10k, Atuin, Neovim,
  zsh-autosuggestions, and zsh-syntax-highlighting.
- Prompt checks cover wrapped commands, prior output, duplicate displays,
  preview after Escape, vi mode switching, and preserved custom bindings.
- Syntax and whitespace checks pass. Tests use synthetic data and temporary
  HOME/config/work directories; live shell and history files are not modified.
- Manual acceptance passed in the maintainer's shell setup, including Sheldon
  and vi bindings. Subsequent preview regressions have automated coverage.

## Remaining work

- [ ] Verify compatibility on native Zsh 5.8, including scalar attributes and ZLE.
- [ ] Repeat the acceptance checklist on Zsh 5.8 and record the result.

Package and VM integration are future work outside the initial version.

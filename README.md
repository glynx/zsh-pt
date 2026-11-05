# zsh-pt

`pt` manages temporary pentest variables in your current Zsh. Activate a working
environment, set or edit its values, and restore your baseline when finished.
Saving is explicit. Changing directories never activates an environment.

Requires Linux, Zsh, and GNU coreutils. Tested on Zsh 5.9.2; native Zsh 5.8
validation is pending. MIT licensed.

- [Installation](#installation) with Sheldon or direct sourcing
- [Commands](#commands) and [templates](#templates-merging-and-saving)
- [Variable editor and shortcuts](#editor-and-keyboard-shortcuts)
- [Command preview](#command-preview) and [Enter guard](#enter-guard)
- [Restoration and history](#restoration-and-history)

## Quick test

From this repository, run in an interactive Zsh:

```zsh
source ./examples/quickstart.zsh
```

The sample loads the plugin, enables completion and guard warnings, adds a short
`pt` prompt marker, and starts an empty scratch environment. An existing active
environment is preserved. Powerlevel10k keeps its other segments. Sourcing again
does not duplicate the marker; no startup files or saved environments are written.
Open a new shell to return to your usual setup.

```zsh
pt set TARGET 127.0.0.1
pt set ACCOUNT test-user
pt set PASSWORD              # Visible input; Enter accepts an empty password
pt status                    # Show managed values in cleartext
pt edit                      # Edit defined managed variables
pt save demo                 # Explicitly save ./demo.env with mode 0600
pt deactivate                # Restore baseline values; hide the prompt marker
pt demo                      # Activate the saved environment
```

**Preview before running:** type a command containing variables, then press
**Ctrl-X, Ctrl-P** to see their current values substituted without executing it.
Press the shortcut again to close the preview. See [Command preview](#command-preview).

## Installation

### Direct sourcing

Load your baseline, such as `pentest.env`, through your existing configuration.
Then source the plugin after integrations that customize `accept-line`:

```zsh
source /path/to/zsh-pt/pt.plugin.zsh
```

Loading the plugin does not change your prompt or enable the guard. Repeated
sourcing preserves the active environment and widgets; start a new shell to
load code changes. An existing `pt` command produces a warning and is shadowed.
`command pt` still selects an external executable.

### Sheldon

Add to your existing `plugins.toml`:

```toml
[plugins.pt]
local = "/path/to/zsh-pt"
use = ["pt.plugin.zsh"]
```

This local entry loads the checkout directly. For a published repository, replace
`local` with `github = "OWNER/zsh-pt"`, using the repository owner's name. Keep
the explicit `use` entry. The plugin installs nothing and does not modify host
configuration.

Place the `pt` entry after your other plugins. If integrations such as Atuin load
later in `.zshrc`, leave the guard off during Sheldon loading:

```zsh
PT_GUARD_MODE=off
eval "$(sheldon source)"  # Your existing Sheldon loading line
```

### Powerlevel10k and guard setup

Define the segment in `~/.p10k.zsh` alongside your other
custom prompt functions:

```zsh
function prompt_pt() {
  [[ -n ${PT_ENV_NAME-} ]] || return
  p10k segment -b 0 -f 7 -t 'pt'
}
```

Add `pt` at your preferred position in the existing
`POWERLEVEL9K_LEFT_PROMPT_ELEMENTS` or `POWERLEVEL9K_RIGHT_PROMPT_ELEMENTS` array
in that file, preserving the other elements. The marker appears only while an
environment is active. If you use another prompt, choose the simple prompt
example or your own configuration.

At the end of `~/.zshrc`, after Atuin and all other editor integrations, enable
the guard:

```zsh
pt guard warn >/dev/null
```

This enables the guard around the final `accept-line` widget without startup
output. It does not activate an environment; run `pt activate` when needed.
With the Sheldon setup above, the plugin itself is loaded only through Sheldon.
Open a new shell after editing startup configuration.

## Commands

| Command | Behavior |
| --- | --- |
| `pt NAME` | Activate a local file, template, or new empty environment |
| `pt activate [NAME]` | Explicit activation; no NAME starts fresh scratch |
| `pt activate --template NAME` | Activate a home template, ignoring local files |
| `pt load [-f] [--template] NAME` | Merge values; ask before replacing existing variables |
| `pt set NAME [VALUE]` | Export a literal string; omit VALUE for visible input |
| `pt unset NAME` | Unset a variable until deactivation |
| `pt edit` | Edit defined managed variables in `$VISUAL`, `$EDITOR`, or `vi` |
| `pt status` | Show environment, original source, and managed values |
| `pt rename NAME` | Rename the active environment in memory |
| `pt save [--force] [NAME]` | Save in the current directory and adopt NAME |
| `pt list` | List local environments and templates without their contents |
| `pt deactivate` | Restore managed variables; discard unsaved changes |
| `pt guard [off\|warn\|block]` | Show or change Enter validation |
| `pt help` | Show compact help |

Only one environment is active. Switching first restores the previous baseline;
switching and deactivation discard unsaved changes without confirmation.
`pt activate` never loads a file, even if `scratch.env` exists. Use the explicit
activation form for environments named after commands, such as `pt activate load`.

Environment names contain letters, digits, underscores, and hyphens, and cannot
start with a hyphen. `pentest` is reserved. Variable names must be ordinary Zsh
identifiers. Internal, special, `PT_`, `_pt_`, `LOGCHECK`, and `WATCHFMT` variables
are excluded from management.

Values are captured immediately. The calling shell still expands arguments:
`pt set TARGET "$OTHER_TARGET"` captures the current value. `pt set` removes
numeric and case-conversion attributes so its input stays literal.
An empty value (`pt set PASSWORD ''`) is defined; `pt unset PASSWORD` is not.
Quote `"$PASSWORD"` when a command needs an empty argument.

`pt status` displays empty values as `''` and unset values as `<unset>`.
Its header shows Dirty only for environments activated from a file. Successful
saves clear dirty state. `Source` remains the original activation source.

## Templates, merging, and saving

Lookup prefers `./NAME.env`, then
`${XDG_CONFIG_HOME:-$HOME/.config}/pt/templates/NAME.env`. Set `PT_TEMPLATE_DIR`
to use another template directory. `--template` ignores local files. An invalid
local file is an error, not a reason to fall back to a template.

Create templates as trusted Zsh code:

```zsh
ACCOUNT=$LOWPRIV
PASSWORD=$LOWPRIVPW
DOMAIN=example.test
```

Use ordinary assignments, or `typeset -g` for explicit global attributes.
Files are sourced inside a function, so plain `typeset` declarations are local
to the loading call. Templates must not call `pt` or change reserved plugin state.

Activation creates a new environment; `pt load` merges into the current one:

```zsh
pt activate assessment
pt set TARGET server01
pt load --template lowpriv    # Keep TARGET unless the template assigns or unsets it
pt load overrides            # Require ./overrides.env or a matching template
pt save                      # Explicitly save the merged assessment
```

Loaded assignments replace current values, empty assignments stay empty, and
explicit `unset` removes a variable. Unmentioned values remain unchanged.

When a defined variable would change, `pt load` shows its current and proposed
values, for example `pt: replace ACCOUNT: 'old' -> 'new'? [y/N]`.
Empty strings appear as `''`, explicit unsets as `<unset>`, and control characters
use readable escapes. Attribute-only changes also show the old and new flags.
Answer No (or press Enter) to keep it and continue; answer Yes to accept the
replacement. New variables and identical states do not prompt. Empty strings
count as defined, and attribute changes or explicit unsets also require consent.
`-f` or `--force` skips these prompts:

```zsh
pt load -f overrides
pt load --template --force lowpriv
```

The trusted file is sourced once to capture final values. Managed scalars are
restored before questions, and selected replacements are applied after all
answers. Ctrl-C or end-of-input cancels without applying any selected changes.
Skipping a variable does not reevaluate assignments that referenced it.
Without a terminal, conflicting loads fail unless forced; new or identical
values can still load normally. Arbitrary effects of sourced code remain outside
the scalar restoration guarantee.

The active name and original source stay the same. Actual changes mark the
environment dirty; reloading identical values does not. Unlike activation,
`pt load` requires an existing file and an active environment. A failed merge
attempts to restore the values and attributes present immediately before it.
Deactivation still restores the original activation baseline.

`pt save` writes only managed values and explicit unsets. It publishes an atomic
file with mode `0600` in the current directory. Overwriting requires terminal
confirmation or `--force`; without a terminal, an unforced overwrite fails.
Symlink destinations, directories, traversal, `pentest.env`, and saving inside
template directories are refused. Failure preserves the previous file, name,
and dirty state. Saving after `cd` writes in the new directory. Renaming never
moves or deletes a file, and saving never updates a home template.

## Editor and keyboard shortcuts

`pt edit` shows defined managed variables, not every shell variable. From a
guard warning, **Ctrl-X, E** also includes missing command variables:

```zsh
ACCOUNT=$'test-user'
PASSWORD=''
# DOMAIN=''
```

Uncomment a missing variable to define it. Leaving it commented keeps it unset.
Add assignments, use `unset -- NAME`, or delete a listed assignment to unset it.
Save and quit to apply; quitting without saving leaves values unchanged.
An editor failure status cancels, for example Vim's `:cq`.

The temporary file starts with mode `0600` and is removed on return. Edits are
checked in an isolated Zsh with the exported shell environment before scalar
values and unsets are applied. Syntax errors, evaluation failures, and unsupported
variables leave the environment unchanged. Editor arguments are supported without
evaluating the editor command as shell code. Changes stay in memory until `pt save`.

| Key | Action |
| --- | --- |
| Ctrl-X, Ctrl-P | Preview variable expansion; repeat to close |
| Ctrl-X, E or Ctrl-X, Ctrl-E | Edit variables; include missing names during a guard warning |
| Enter | Run; in warn mode, press twice consecutively to run with missing variables |
| Esc (emacs mode) | Hide an open preview; otherwise abort a guarded command if the binding was available |
| Ctrl-C | Normal shell cancellation, including vi mode |

For Ctrl-X, E, release Ctrl before typing lowercase `e`. Automatic bindings
preserve occupied keys in `emacs` and `viins`. During a guard warning, a temporary
keymap enables both editor shortcuts; normal bindings return afterward.

**Vi bindings:** Escape keeps its normal switch from insert to command mode;
it does not abort. Guard messages show `[Ctrl-C] abort` instead. Preview works
in both insert and command mode, including after Escape. Editor shortcuts are
available in insert mode where their bindings are free.
The guard also handles Enter in command mode. Emacs arrow keys and Alt sequences
remain intact; `KEYTIMEOUT` controls the short wait for standalone Escape.
The plugin and quickstart sample do not select your editing mode.

The editor never executes the original command. After all missing variables
are defined, the guard reports `[Enter] run`; otherwise the warning returns.
Warnings use ZLE's native message area below the command, so autosuggestions
cannot insert them into command text.

## Command preview

Type a command normally, then press **Ctrl-X, Ctrl-P** to show it with supported
variables replaced by their current values. Press the shortcut again to close
the preview. For example:

```zsh
netexec smb "$TARGET" -u "$ACCOUNT" -p "$PASSWORD"
```

With TARGET set to `server01`, ACCOUNT to `test-user`, and PASSWORD to an empty
string, the preview displays:

```text
pt preview: netexec smb "server01" -u "test-user" -p ""
```

The command and cursor stay unchanged; nothing is executed or added to history.
No active pt environment is required. The shortcut works in emacs mode and both
vi modes. In emacs mode, Escape hides an open preview without changing the command,
even with the guard off. If a guard warning is pending, a second Escape aborts.
Escape still switches vi insert mode to command mode, where the same preview
shortcut continues to work. Existing occupied bindings, including custom Escape
bindings, are preserved; use Ctrl-X, Ctrl-P to close the preview in that case.

Preview and the guard support `$NAME`, `${NAME}`, quoting, escaped dollars, and
simple literal defaults such as `${NAME:-}`. Single-quoted and ANSI-C quoted
strings are left alone. Substitutions, heredocs, complex parameter expressions, comments,
unclosed quotes, and unsupported attributes are marked unchecked. Ambiguous
syntax leaves the remaining buffer unchecked. Preview does not perform globbing,
word splitting, alias expansion, or final argument construction.

Set `PT_PREVIEW_KEY` before loading to change the shortcut; an empty value
disables automatic binding. Bind widgets manually after other integrations:

```zsh
bindkey -M emacs '^X^P' pt-preview
bindkey -M viins '^X^P' pt-preview
bindkey -M vicmd '^X^P' pt-preview
```

## Enter guard

The guard only checks commands while a pt environment is active and defaults
to `off`. Its configured mode is retained across deactivation and reactivation.
Set `PT_GUARD_MODE=warn` before loading, or run
`pt guard warn` afterward. `warn` requires a consecutive second Enter on the
same buffer to run with missing variables; `block` refuses until values are
defined or a deliberate bypass widget is invoked.

The guard detects referenced variables automatically, including unmanaged shell
variables. Only unset variables are missing; empty passwords are valid.
`typeset -a PT_OPTIONAL_VARS=(DOMAIN)` exempts DOMAIN. `PT_CHECK_VARS` is only a
completion hint, not a required guard list. Checks use current shell values;
they do not predict assignments or control flow in the command.

The guard wraps `accept-line` when first enabled. Load other editor integrations
first; later replacements and custom execution widgets can bypass it.

To bind a deliberate one-time bypass:

```zsh
bindkey '^X^J' pt-accept-bypass
```

Ctrl-X, Ctrl-J then accepts the current buffer through the original widget;
subsequent commands remain guarded.

## Prompt, completion, and colors

The plugin exports `PT_ENV_NAME` while active and leaves your prompt alone.
Source [examples/prompt.zsh](examples/prompt.zsh) for a short `[pt]` prefix, or use
the [Powerlevel10k setup](#powerlevel10k-and-guard-setup). Both hide the marker
when inactive. [examples/powerlevel10k.zsh](examples/powerlevel10k.zsh) provides
the same function for configurations that prefer sourcing it.
Use `$PT_ENV_NAME` in your own configuration to display the name instead.

Completion suggests commands, options, environment names, and variable names;
it never sources files or suggests values. An existing `compinit` setup works
before or after plugin loading. The plugin does not initialize it; the quickstart
sample uses `compinit -D` if needed, without creating a cache.

Status uses one bold header and plain assignments. Other messages use simple
success/error colors; guard messages stay plain. `PT_COLOR=auto` colors terminals
only, `never` disables colors, and `always` forces them. `NO_COLOR` and `TERM=dumb`
disable colors regardless. Redirected output is plain by default.

## Restoration and history

Before activation, `pt` snapshots global scalar values and attributes. Changed
variables from activation, merge loads, `pt set`, `pt unset`, and editing become
managed. Deactivation restores unset/empty states, export flags, integer bases,
finite float values and precision, case flags, and padding. Unchanged file
assignments are not considered overrides and are not saved. Direct shell edits
are not watched; use the `pt` commands for managed changes.

Arrays, associations, tied, readonly, special, and local parameters are unsupported
for management. Sourced unsupported changes are diagnosed and restoration is
attempted. Irreversible changes, such as creating readonly parameters, can leave
restoration incomplete; the environment remains active for inspection.

Files are trusted executable Zsh code, not dotenv input. Sourcing uses the file's
return status and is not a sandbox. Functions, directories, options, files, and
external effects are outside the scalar restoration guarantee. `pentest.env`
is never written by the plugin.

Literal command arguments can enter Zsh and Atuin history. Use `pt set NAME`
to enter a value visibly without adding it to command history.
Status, preview, load confirmations, and saved files show
cleartext values; recordings and screenshots can capture them. Exclude saved
environments from Git locally, for example `/demo.env` in `.git/info/exclude`.
This repository ignores root-level `.env` files. Do not commit real
credentials or customer data; use targeted exclusions rather than a global
`*.env` rule.

Guard cancellation via the plugin's Escape binding adds the unexpanded command
to native history for immediate Up recall. Active standard Atuin integration
also attempts to record it as cancelled (exit 130), respecting Atuin filters.
No command is executed. Ctrl-C retains normal shell behavior without this
explicit history entry; `pt` does not rewrite or redact history.

## Verification

```sh
make test
PT_TEST_P10K=/path/to/powerlevel10k/powerlevel10k.zsh-theme make test
```

Tests use synthetic data, temporary HOME/config/work directories, isolated
`zsh -f` processes, and pseudoterminals. Optional checks cover installed Sheldon,
Atuin, autosuggestions, syntax highlighting, and a temporary Powerlevel10k copy.
Set `PT_TEST_AUTOSUGGEST` and `PT_TEST_SYNTAX` to their plugin entrypoints.
Missing integrations are reported as skips. `PT_TEST_TMUX=1` with `PT_TEST_P10K`
enables a private tmux screen test, requiring local Unix socket access.

See [PLAN.md](PLAN.md) for development status and
[docs/acceptance.md](docs/acceptance.md) for the manual checklist. Maintainer-reported
manual acceptance passed with Sheldon and vi bindings. Native Zsh 5.8 validation
remains open. Tests do not change live shell/history files or host configuration.

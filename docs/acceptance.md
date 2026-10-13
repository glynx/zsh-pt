# Manual acceptance

Manual acceptance has passed in the maintainer's shell setup, including Sheldon
and vi bindings. Use this checklist after releases or on another system.
Native Zsh 5.8 validation remains open.

Use synthetic values and a disposable working directory. Automated tests use
isolated HOME/config/work directories; the checks below exercise your normal
shell integrations.

## Activation and saving

Start `zsh -f` in the disposable directory:

```zsh
source /path/to/zsh-pt/pt.plugin.zsh
export ACCOUNT=baseline-user
TARGET=baseline-target
pt demo
pt set ACCOUNT test-user
pt set TARGET server01
pt set PASSWORD
pt status
pt save
pt deactivate
print -r -- "$ACCOUNT / $TARGET"
pt demo
pt status
```

- Enter a synthetic password; input must not echo.
- Deactivation must restore ACCOUNT and TARGET to their baseline values.
- Reloading demo must restore the saved values.
- `stat -c %a demo.env` must report `600`.
- While demo is active, repeat `pt save`: answer No and verify the file is
  unchanged, then repeat and approve the overwrite.
- `pt save pentest` must fail. Saved environments must stay outside source control.
- Run `pt deactivate` when finished.

## Startup and prompt

- Load pt through Sheldon using the README configuration. Keep the guard off
  during plugin loading, then enable it at the end of `.zshrc`, after Atuin and
  other editor integrations.
- Start a new shell. Pt must be inactive; `pt guard` must report warn.
- Add `prompt_pt` and the `pt` element in `~/.p10k.zsh`. The short marker must
  appear only while active. Custom name segments must track renaming/switching.
- Source the quickstart sample twice: it must preserve the active environment
  and avoid duplicate prompt markers.
- Check status colors, `PT_COLOR=never`, and plain guard messages.

## Command preview

Activate demo and set synthetic TARGET, ACCOUNT, and PASSWORD values.

- Type `netexec smb "$TARGET" -u "$ACCOUNT" -p "$PASSWORD"` without executing it.
  Ctrl-X, Ctrl-P must show the substituted command; repeating the shortcut closes
  it. The command and cursor must stay unchanged.
- With emacs bindings, Escape must hide an open preview without changing the
  command, including when the guard is off.
- Preview `print "$TARGET" $(touch should-not-exist)`. The substitution must be
  marked unchecked and the file must not exist. Cancel the command.
- From a guard warning, open a preview and press Escape. The command must remain;
  a second Escape must cancel it.
- Repeat with autosuggestions enabled. Suggestion-accept and end-of-line keys
  must never insert the preview or warning into the command.

## Enter guard and cancellation

- Set `pt set PASSWORD ''` and `pt guard warn`. `print "$PASSWORD"` must run
  without warning.
- Run `pt unset TARGET`. For `print "$TARGET"`, the first Enter must warn and a
  consecutive second Enter must execute.
- With `pt guard block`, repeated Enter must remain blocked. A reference using
  `${TARGET:-}` must be allowed.
- Bind `bindkey '^X^J' pt-accept-bypass`. One bypass must accept the command;
  subsequent commands must remain guarded.
- In emacs mode, Escape after a guard warning must clear the command. Define the
  missing variable, then use Up to recall the original unexpanded command.
  Cancellation must not execute it. Arrow keys and Alt shortcuts must still work.
- Repeat with a wrapped command and Enter pressed at its start. The warning must
  stay below one editable command; earlier output must remain visible.
- Set `PT_GUARD_MODE=warn` before plugin loading in a fresh shell to verify the
  startup default. Restore your desired setting afterward.

## Variable editor

- `pt edit` must list only defined managed variables. Check new assignments,
  empty values, explicit unsets, deletion, and quitting without saving.
- From a warning, Ctrl-X then lowercase `e` or Ctrl-X then Ctrl-E must open the
  variable editor, including commented placeholders for missing names.
- Save assignments. The original command and cursor must remain unchanged, and
  execution must require a separate Enter.
- Leave placeholders commented. The missing-variable warning must return, and
  cancellation must remain available.
- In emacs mode, Escape must also cancel after editing resolves every missing
  variable.
- Repeat with autosuggestions and syntax highlighting. Existing editor bindings
  must return after editing, cancellation, acceptance, or a changed command.

## Merge loading

```zsh
export ACCOUNT=baseline
pt activate assessment
pt set ACCOUNT working
pt set TARGET 127.0.0.1
print -r -- "ACCOUNT=merged; PASSWORD=''" > overlay.env
pt load overlay
pt status
print -r -- 'ACCOUNT=broken; return 1' > broken.env
pt load broken
pt status
pt deactivate
```

- Approve ACCOUNT's replacement. The name must remain assessment, TARGET must be
  retained, and PASSWORD must be defined but empty.
- The failed load must leave ACCOUNT at merged. Deactivation must restore its
  baseline and remove variables created by pt.
- Repeat with `pt load --template NAME` and explicit unsets. Loading must not
  write saved files.
- Decline one replacement and approve another. Prompts must show current and
  proposed values, distinguishing `''` from `<unset>`. Control bytes and
  multiline values must use readable escapes.
- New or identical values must not ask; an empty string must count as defined.
- Cancel after an earlier Yes: no selected changes must be applied.
- `pt load -f overlay` must bypass questions. Without a terminal, conflicts must
  fail unless forced; new values can load normally.

## Vi bindings

- Select `bindkey -v` before loading the plugin. Preview, close/reopen, press
  Escape, and preview again. Command-mode preview must not recall history or
  change the buffer.
- Enable the guard and enter a command using an unset variable. The hint must
  show `[Ctrl-C] abort`. Escape must switch to command mode and retain the buffer;
  Enter must still validate.
- In insert mode, check preview and variable editing. Returning from the editor
  must not execute the command. Ctrl-C must cancel normally.
- Repeat after selecting vi mode in an already loaded shell. The quickstart
  sample must preserve the selected mode.

## History and completion

- Check normal Atuin recall/edit behavior. A command cancelled through the pt
  Escape binding must have exit status 130 in Atuin when its hook is active.
- Hidden password input and preview expansions must not appear as command
  literals in synthetic test history. Literal command arguments still enter
  history normally.
- Check Tab completion for subcommands, local/template names, `pt load --template`,
  `pt set TARGET`, force options, and guard modes.
- Completion must never suggest values or source a file.

Record the Zsh, Sheldon, Atuin, and Powerlevel10k versions with the results.
Native Zsh 5.8 compatibility remains unverified until tested on that version.

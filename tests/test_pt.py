"""Isolated tests; never use the operator's shell files or environment."""

import os
import errno
import json
from pathlib import Path
import pty
import re
import select
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
ZSH = shutil.which("zsh")


class IsolatedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pt-test-")
        self.addCleanup(self.cleanup_tmp)
        self.home = Path(self.tmp.name) / "home"
        self.work = Path(self.tmp.name) / "work"
        self.config = self.home / ".config"
        self.templates = self.config / "pt" / "templates"
        self.templates.mkdir(parents=True)
        self.work.mkdir()
        self.env = {
            "PATH": "/usr/bin:/bin", "HOME": str(self.home),
            "ZDOTDIR": str(self.home), "XDG_CONFIG_HOME": str(self.config),
            "XDG_CACHE_HOME": str(self.home / ".cache"),
            "XDG_DATA_HOME": str(self.home / ".local" / "share"),
            "TERM": "xterm-256color", "LANG": "C.UTF-8",
            "PT_PLUGIN": str(ROOT / "pt.plugin.zsh"),
        }

    def cleanup_tmp(self):
        # Atuin ends history entries asynchronously, after the shell exits.
        deadline = time.monotonic() + 3
        while True:
            try:
                self.tmp.cleanup()
                return
            except OSError as error:
                if error.errno != errno.ENOTEMPTY or time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)

    def run_zsh(self, body, *, load=True):
        script = 'source "$PT_PLUGIN" || exit 90\n' if load else ""
        script += """
function fail { print -u2 -r -- "assertion failed: $*"; exit 91; }
function eq { [[ $1 == $2 ]] || fail "${3:-equality}"; }
""" + body
        result = subprocess.run(
            [ZSH, "-f"], input=script, text=True, capture_output=True,
            cwd=self.work, env=self.env, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def fake_editor(self, body):
        editor = self.home / "fake editor"
        editor.write_text(f"#!{ZSH} -f\n" + r"""
command cp -- "$1" "$HOME/editor-before"
command stat -c %a -- "$1" > "$HOME/editor-mode"
print -r -- "$1" > "$HOME/editor-path"
""" + body)
        editor.chmod(0o700)
        self.env["EDITOR"] = f"'{editor}'"
        return editor


class CoreTests(IsolatedTest):
    def test_loading_help_and_reloading_write_nothing(self):
        self.run_zsh("""
pt help || fail help
pt scratch || fail activate
pt set TARGET sample || fail set
source "$PT_PLUGIN" || fail reload
eq "$TARGET" sample reload-value
eq "$PT_ENV_NAME" scratch reload-state
pt deactivate || fail deactivate
""")
        self.assertEqual(list(self.work.iterdir()), [])
        self.assertEqual(list(self.home.iterdir()), [self.config])

    def test_collision_warns_and_keeps_pt(self):
        result = self.run_zsh("""
alias pt='print WRONG'
function pt { print WRONG; }
source "$PT_PLUGIN" || fail load
pt help || fail help
""", load=False)
        self.assertIn("warning", result.stderr)
        self.assertIn("Usage: pt", result.stdout)
        self.assertNotIn("WRONG", result.stdout)

    def test_names_and_reserved_commands(self):
        self.run_zsh("""
for name in pentest ../escape /absolute .hidden bad.name '-option' 'with space' ''; do
  if pt activate "$name"; then fail invalid-name; fi
done
pt activate status || fail reserved-command
eq "$PT_ENV_NAME" status
pt rename good_name-2 || fail rename
eq "$PT_ENV_NAME" good_name-2
pt deactivate
""")

    def test_activation_without_name_starts_fresh(self):
        self.run_zsh("""
mkdir -p "$XDG_CONFIG_HOME/pt/templates"
print -r -- 'TARGET=local-source; touch sourced-local' > scratch.env
print -r -- 'TARGET=template-source; touch sourced-template' > "$XDG_CONFIG_HOME/pt/templates/scratch.env"
TARGET=baseline
pt activate || fail unnamed-activation
eq "$PT_ENV_NAME" scratch unnamed-label
eq "$_pt_source" '<empty>' unnamed-source
eq "$TARGET" baseline untouched-baseline
[[ ! -e sourced-local && ! -e sourced-template ]] || fail sourced-file
pt set TARGET temporary || fail set
pt activate || fail repeat
eq "$TARGET" baseline restored-on-switch
if pt activate --template; then fail missing-template-name; fi
eq "$PT_ENV_NAME" scratch preserved-after-invalid
pt set TARGET saved-value || fail set-again
pt save named || fail save
eq "$PT_ENV_NAME" named saved-label
[[ -f named.env ]] || fail saved-file
pt deactivate || fail deactivate
eq "$TARGET" baseline restored
pt activate scratch || fail explicit-name
eq "$TARGET" local-source explicit-load
pt deactivate || fail explicit-deactivate
eq "$TARGET" baseline explicit-restoration
""")

    def test_load_merges_values_unsets_attributes_and_preserves_identity(self):
        self.run_zsh(r"""
export ACCOUNT=baseline PASSWORD=baseline-password
TARGET=baseline-target
typeset -gi16 NUMBER=31
print -r -- 'ACCOUNT=initial' > initial.env
print -r -- "ACCOUNT=merged; PASSWORD=''; unset -- TARGET; typeset -gi8 NUMBER=9; EXTRA=added" > overlay.env
pt initial || fail activate
pt set KEEP unchanged
pt load -f overlay || fail load
eq "$PT_ENV_NAME" initial name
eq "$_pt_source" "$PWD/initial.env" source
eq "$_pt_dirty" 1 dirty
eq "$ACCOUNT" merged replaced
eq "$PASSWORD" '' empty
(( ${+PASSWORD} && ! ${+TARGET} )) || fail empty-unset
eq "$NUMBER" '8#11' attributes
eq "$KEEP" unchanged untouched
eq "$EXTRA" added added
pt save merged || fail save
pt deactivate || fail deactivate
eq "$ACCOUNT" baseline baseline-account
eq "$PASSWORD" baseline-password baseline-password
eq "$TARGET" baseline-target baseline-target
eq "$NUMBER" '16#1F' baseline-attributes
(( ! ${+KEEP} && ! ${+EXTRA} )) || fail new-restored
pt merged || fail saved-reload
eq "$ACCOUNT" merged saved-merge
eq "$PASSWORD" '' saved-empty
(( ! ${+TARGET} )) || fail saved-unset
eq "$NUMBER" '8#11' saved-attributes
pt deactivate || fail final-restore
""")

    def test_load_resolution_validation_and_unchanged_dirty_state(self):
        self.run_zsh(r"""
print -r -- 'TARGET=local' > overlay.env
LOWPRIV=template
print -r -- 'TARGET=$LOWPRIV' > "$XDG_CONFIG_HOME/pt/templates/overlay.env"
if pt load overlay; then fail inactive; fi
pt activate || fail activate
pt load overlay || fail local
eq "$TARGET" local local-first
eq "$PT_ENV_NAME" scratch scratch-name
eq "$_pt_source" '<empty>' original-source
pt load --template --force overlay || fail template
eq "$TARGET" template template-selected
pt save saved || fail save
pt load --template overlay || fail unchanged
eq "$_pt_dirty" 0 no-change-clean
for args in '' '--template' 'missing' '--template missing' '../overlay' 'pentest' 'one two'; do
  if pt load ${=args}; then fail invalid-load; fi
done
mkdir broken.env
print -r -- 'TARGET=wrong' > "$XDG_CONFIG_HOME/pt/templates/broken.env"
if pt load broken; then fail invalid-local-fallback; fi
eq "$TARGET" template preserved
eq "$PT_ENV_NAME" saved name-preserved
eq "$_pt_dirty" 0 failures-clean
pt deactivate || fail deactivate
""")

    def test_failed_load_restores_pre_merge_values_and_management(self):
        self.run_zsh(r"""
export ACCOUNT=baseline
typeset -gi16 NUMBER=31
pt activate || fail activate
pt set ACCOUNT active
pt set EMPTY ''
pt save saved || fail save
print -r -- 'ACCOUNT=broken; unset -- EMPTY; NUMBER=42; ADDED=new; return 7' > bad.env
if pt load bad; then fail failed-source; fi
eq "$ACCOUNT" active active-restored
eq "$EMPTY" '' empty-restored
eq "$NUMBER" '16#1F' attributes-restored
(( ${+EMPTY} && ! ${+ADDED} )) || fail states-restored
eq "${(j: :)${(ok)_pt_managed}}" 'ACCOUNT EMPTY' management-restored
eq "$_pt_dirty" 0 dirty-restored
eq "$_pt_active" 1 still-active
eq "$_pt_loading" 0 loading-reset
print -r -- 'ACCOUNT=broken; pt deactivate' > nested.env
if pt load nested; then fail reentrant-load; fi
eq "$ACCOUNT" active nested-restored
pt set ACCOUNT changed
if pt load bad; then fail dirty-failure; fi
eq "$ACCOUNT" changed dirty-value-restored
eq "$_pt_dirty" 1 dirty-preserved
pt deactivate || fail deactivate
eq "$ACCOUNT" baseline baseline-restored
""")

    def test_load_without_terminal_refuses_conflicts_but_accepts_new_and_equal(self):
        result = self.run_zsh(r"""
ACCOUNT=baseline PASSWORD=''
pt activate
print -r -- "ACCOUNT=baseline; NEW=added" > equal.env
pt load equal || fail equal-and-new
eq "$NEW" added new
pt save saved
print -r -- "ACCOUNT=changed; PASSWORD=new; NEW=changed; ADDED=new" > conflict.env
if pt load conflict; then fail nonterminal-conflict; fi
eq "$ACCOUNT" baseline kept-account
eq "$PASSWORD" '' kept-empty
eq "$NEW" added kept-new
(( ! ${+ADDED} )) || fail no-partial-apply
eq "$_pt_dirty" 0 dirty-kept
pt load --force conflict || fail forced
eq "$ACCOUNT" changed forced-account
eq "$PASSWORD" new forced-empty
eq "$ADDED" new forced-added
pt deactivate
eq "$ACCOUNT" baseline restored
eq "$PASSWORD" '' empty-restored
""")
        self.assertIn("use -f without a terminal", result.stderr)

    def test_load_attribute_only_changes_require_confirmation(self):
        self.run_zsh(r"""
typeset -gi16 NUMBER=31
pt activate
print -r -- 'typeset -gi10 NUMBER=31' > attributes.env
if pt load attributes; then fail attribute-conflict; fi
eq "$NUMBER" '16#1F' attributes-kept
pt load --template -f missing && fail missing-template
pt load -f attributes || fail forced-attributes
eq "$NUMBER" 31 new-attributes
pt deactivate
eq "$NUMBER" '16#1F' original-attributes
""")

    def test_load_unsupported_changes_and_irreversible_failure(self):
        result = self.run_zsh(r"""
TARGET=baseline
typeset -a ARRAY=(original)
pt activate || fail activate
pt set TARGET active
print -r -- 'TARGET=broken; typeset -ga NEW_ARRAY=(one two)' > array.env
if pt load array; then fail new-array-accepted; fi
eq "$TARGET" active scalar-restored
(( ! ${+NEW_ARRAY} )) || fail new-array-restored
# A parameter unsupported at activation must not become managed through a merge.
unset ARRAY
ARRAY=manual
print -r -- 'ARRAY=merged' > original.env
if pt load original; then fail unsupported-original; fi
eq "$ARRAY" manual pre-merge-restored
print -r -- 'TARGET=broken; typeset -gr LOCKED=value; return 1' > readonly.env
if pt load readonly; then fail readonly-accepted; fi
eq "$TARGET" active scalar-restored-again
eq "$_pt_active" 1 active-on-incomplete
(( ${+_pt_managed[LOCKED]} )) || fail incomplete-tracked
if pt deactivate; then fail irreversible-deactivate; fi
""")
        self.assertIn("restoration incomplete", result.stderr)

    def test_unset_and_empty_roundtrip_and_restore(self):
        result = self.run_zsh(r"""
export PASSWORD=baseline
PLAIN=original EMPTY=''
typeset -gi16 NUMBER=31
unset NEW
pt activate || fail activate
pt set PASSWORD '' || fail empty-password
_pt_guard_check 'tool -p "$PASSWORD"'
eq "${#_pt_guard_missing}" 0 empty-valid
pt unset PLAIN || fail unset-plain
pt unset NUMBER || fail unset-number
pt unset EMPTY || fail unset-empty
pt unset NEW || fail unset-new
pt unset NEW || fail repeat-unset
(( ! ${+PLAIN} && ! ${+NUMBER} && ! ${+EMPTY} && ! ${+NEW} )) || fail still-set
eq "$_pt_dirty" 1 dirty
pt status
pt rename roundtrip || fail rename
pt save || fail save
pt deactivate || fail deactivate
eq "$PASSWORD" baseline password-restored
eq "${parameters[PASSWORD]}" scalar-export password-export-restored
eq "$PLAIN" original plain-restored
eq "$NUMBER" '16#1F' numeric-restored
(( ${+EMPTY} && ! ${+NEW} )) || fail original-states
pt roundtrip || fail reload
(( ${+PASSWORD} && ! ${+PLAIN} && ! ${+NUMBER} && ! ${+EMPTY} && ! ${+NEW} )) || fail roundtrip-states
eq "$PASSWORD" '' roundtrip-empty
pt unset PASSWORD || fail unset-password
_pt_guard_check 'tool -p "$PASSWORD"'
eq "${(j: :)_pt_guard_missing}" PASSWORD unset-missing
pt set PASSWORD '' || fail set-after-unset
_pt_guard_check 'tool -p "$PASSWORD"'
eq "${#_pt_guard_missing}" 0 set-empty-again
pt deactivate || fail restore-again
eq "$PASSWORD" baseline baseline-again
""")
        self.assertIn("PASSWORD=''", result.stdout)
        self.assertIn("PLAIN=<unset>", result.stdout)
        self.assertIn("NEW=<unset>", result.stdout)
        saved = (self.work / "roundtrip.env").read_text()
        self.assertIn("unset -- PLAIN", saved)
        self.assertIn("PASSWORD=$''", saved)

    def test_unset_rejects_invalid_or_unsupported_parameters(self):
        self.run_zsh(r"""
if pt unset VALUE; then fail inactive-unset; fi
typeset -a ARRAY=(synthetic)
typeset -r FIXED=synthetic
pt activate || fail activate
for name in ARRAY FIXED PATH HOME PT_ENV_NAME _pt_active 'BAD-NAME' 'A[1]' ''; do
  if pt unset "$name"; then fail unsafe-unset; fi
done
if pt unset; then fail missing-name; fi
if pt unset ONE TWO; then fail extra-argument; fi
eq "$_pt_dirty" 0 failure-dirty
eq "$ARRAY[1]" synthetic array-preserved
eq "$FIXED" synthetic readonly-preserved
pt deactivate || fail deactivate
""")

    def test_output_color_policy_and_literal_text(self):
        result = self.run_zsh(r"""
_pt_output heading 'AUTO_PLAIN'
PT_COLOR=always
_pt_output success 'FORCED_COLOR'
NO_COLOR=''
_pt_output error 'NO_COLOR_PLAIN' 2
unset NO_COLOR
TERM=dumb
_pt_output warning 'DUMB_PLAIN'
TERM=xterm
PT_COLOR=never
_pt_output heading 'NEVER_PLAIN'
PT_COLOR=always
_pt_output heading '%F{red}$(touch executed)'
[[ ! -e executed ]] || fail text-evaluated
""")
        self.assertIn("AUTO_PLAIN\n", result.stdout)
        self.assertNotIn("\x1b[1;36mAUTO_PLAIN", result.stdout)
        self.assertIn("\x1b[32mFORCED_COLOR\x1b[0m", result.stdout)
        self.assertEqual(result.stderr, "NO_COLOR_PLAIN\n")
        self.assertNotIn("\x1b[33mDUMB_PLAIN", result.stdout)
        self.assertNotIn("\x1b[1;36mNEVER_PLAIN", result.stdout)
        self.assertIn("%F{red}$(touch executed)", result.stdout)

    def test_status_dirty_only_for_loaded_environments(self):
        result = self.run_zsh(r"""
pt activate >/dev/null || fail activate
pt set PASSWORD '' || fail empty
fresh=$(pt status)
[[ $fresh != *Dirty:* ]] || fail fresh-dirty
[[ $fresh == *$'\n\nPASSWORD=\'\'' ]] || fail assignments-block
pt save saved >/dev/null || fail save
[[ $(pt status) != *Dirty:* ]] || fail saved-scratch-dirty
pt deactivate || fail deactivate
pt saved >/dev/null || fail reload
pt status
pt set ACCOUNT synthetic || fail edit
pt status
""")
        self.assertIn("Dirty: no\n\nPASSWORD=''", result.stdout)
        self.assertIn("Dirty: yes\n\nACCOUNT=", result.stdout)

    def test_edit_defined_variables_add_delete_empty_and_restore(self):
        self.fake_editor('command cp -- "$HOME/replacement" "$1"\n')
        (self.home / "replacement").write_text(
            "ACCOUNT='edited user'\nPASSWORD=''\nNEW=$'literal $(touch executed)\\nü'\n"
        )
        self.run_zsh(r"""
TARGET=baseline
pt activate || fail activate
pt set TARGET previous || fail set-target
pt set ACCOUNT initial || fail set-account
pt unset OMIT || fail unset
pt edit || fail edit
eq "$ACCOUNT" 'edited user' edited
eq "$PASSWORD" '' empty
eq "$NEW" $'literal $(touch executed)\nü' literal
(( ! ${+TARGET} && ! ${+OMIT} )) || fail deleted
eq "$_pt_dirty" 1 dirty
[[ ! -e executed ]] || fail evaluated-value
pt save edited || fail save
pt deactivate || fail deactivate
eq "$TARGET" baseline restored
(( ! ${+ACCOUNT} && ! ${+PASSWORD} && ! ${+NEW} )) || fail new-restoration
pt edited || fail reload
eq "$ACCOUNT" 'edited user' saved
eq "$PASSWORD" '' saved-empty
pt deactivate || fail restored-again
""")
        initial = (self.home / "editor-before").read_text()
        self.assertIn("ACCOUNT=", initial)
        self.assertIn("TARGET=", initial)
        self.assertNotIn("OMIT", initial)
        self.assertNotIn("HOME=", initial)
        self.assertEqual((self.home / "editor-mode").read_text(), "600\n")
        self.assertFalse(Path((self.home / "editor-path").read_text().strip()).exists())

    def test_edit_missing_placeholders_remain_unset_until_uncommented(self):
        self.fake_editor('command cp -- "$HOME/replacement" "$1"\n')
        (self.home / "replacement").write_text("ACCOUNT=changed\n# DOMAIN=''\n")
        self.run_zsh(r"""
pt activate || fail activate
pt set ACCOUNT original || fail set
_pt_edit DOMAIN || fail edit-commented
eq "$ACCOUNT" changed edited-account
(( ! ${+DOMAIN} )) || fail implicitly-empty
_pt_guard_check 'tool -d "$DOMAIN"'
eq "${(j: :)_pt_guard_missing}" DOMAIN still-required
""")
        self.assertIn("# DOMAIN=''", (self.home / "editor-before").read_text())
        (self.home / "replacement").write_text("ACCOUNT=changed\nDOMAIN=''\n")
        self.run_zsh(r"""
pt activate || fail activate
_pt_edit DOMAIN || fail edit-uncommented
(( ${+DOMAIN} )) || fail not-set
eq "$DOMAIN" '' explicitly-empty
_pt_guard_check 'tool -d "$DOMAIN"'
eq "${#_pt_guard_missing}" 0 empty-accepted
pt deactivate || fail deactivate
(( ! ${+DOMAIN} )) || fail restoration
""")

    def test_edit_no_change_and_editor_precedence(self):
        editor = self.fake_editor('exit 0\n')
        self.env["VISUAL"] = f"'{editor}'"
        self.env["EDITOR"] = "/does-not-exist"
        self.run_zsh(r"""
if pt edit; then fail inactive; fi
pt activate || fail activate
pt edit || fail empty-edit
eq "$_pt_dirty" 0 unchanged-empty
pt set ACCOUNT initial || fail set
pt save saved || fail save
pt edit || fail no-change
eq "$_pt_dirty" 0 unchanged
if pt edit unexpected; then fail arguments; fi
""")

    def test_edit_failure_preserves_environment_and_cleans_up(self):
        for replacement, editor_status in [
            ("TARGET=wrong\n", 1),
            ("TARGET='broken\n", 0),
            ("TARGET=wrong\nreturn 1\n", 0),
            ("typeset -a TARGET=(wrong)\n", 0),
            ("typeset -r TARGET=wrong\n", 0),
            ("typeset -A MAP=(key wrong)\nTARGET=wrong\n", 0),
        ]:
            with self.subTest(replacement=replacement, editor_status=editor_status):
                self.fake_editor(f'command cp -- "$HOME/replacement" "$1"\nexit {editor_status}\n')
                (self.home / "replacement").write_text(replacement)
                self.run_zsh(r"""
pt activate || fail activate
pt set TARGET original || fail set
pt save --force saved || fail save
if pt edit; then fail accepted-invalid-edit; fi
eq "$TARGET" original preserved
eq "$_pt_dirty" 0 clean-after-failure
eq "$PT_ENV_NAME" saved name-preserved
""")
                self.assertFalse(Path((self.home / "editor-path").read_text().strip()).exists())

    def test_watch_configuration_is_not_managed_or_resaved(self):
        source = self.work / "legacy.env"
        source.write_text("ACCOUNT=synthetic\nLOGCHECK=60\nWATCHFMT='synthetic watch format'\n")
        before = source.read_bytes()
        result = self.run_zsh(r"""
pt legacy || fail activate
pt status
pt save cleaned || fail save
if pt set LOGCHECK 1; then fail shell-setting; fi
if pt unset WATCHFMT; then fail shell-setting-unset; fi
pt deactivate || fail deactivate
""")
        self.assertNotIn("LOGCHECK=", result.stdout)
        self.assertNotIn("WATCHFMT=", result.stdout)
        self.assertNotIn("LOGCHECK", (self.work / "cleaned.env").read_text())
        self.assertNotIn("WATCHFMT", (self.work / "cleaned.env").read_text())
        self.assertEqual(source.read_bytes(), before)

    def test_unsupported_signatures_preserve_array_boundaries_and_associations(self):
        self.run_zsh(r"""
typeset -a ARRAY=('a b' c '')
typeset -A MAP=('a b' c x '')
_pt_capture ARRAY && fail array-supported
signature=$_pt_result_signature
ARRAY=(a 'b c' '')
_pt_capture ARRAY && fail array-supported-again
[[ $_pt_result_signature != $signature ]] || fail lost-boundaries
_pt_capture MAP && fail map-supported
signature=$_pt_result_signature
MAP=(x '' 'a b' c)
_pt_capture MAP && fail map-supported-again
eq "$_pt_result_signature" "$signature" stable-map-order
MAP['a b']=changed
_pt_capture MAP && fail map-supported-third
[[ $_pt_result_signature != $signature ]] || fail lost-value-change
""")

    def test_exported_negative_integer_bases_restore(self):
        self.run_zsh(r"""
for base in 2 8 10 16 36; do
  unset NEGATIVE
  typeset -g -i$base NEGATIVE=-31
  export NEGATIVE
  before=$(typeset -p NEGATIVE)
  pt activate || fail activate
  pt set NEGATIVE temporary || fail set
  pt deactivate || fail deactivate
  eq "$(typeset -p NEGATIVE)" "$before" restored-integer-base
done
""")

    def test_scalar_states_and_attributes_restore_repeatedly(self):
        self.run_zsh("""
unset NEW
EMPTY=''
PLAIN=baseline
export EXPORTED=baseline
typeset -i16 NUMBER=31
typeset -F 3 FIXED=1.234567891234567
typeset -E 4 SCI=1234.56789
typeset -u UPPER=abc
typeset -L 5 PAD=ab
typeset -H HIDDEN=hidden-baseline
old_fixed=$(printf '%.17g' FIXED)
old_sci=$(printf '%.17g' SCI)
for iteration in 1 2 3; do
  pt scratch || fail activate
  for name in NEW EMPTY PLAIN EXPORTED NUMBER FIXED SCI UPPER PAD HIDDEN; do
    pt set "$name" 'literal $(touch should-not-exist)' || fail set
    eq "${parameters[$name]}" scalar-export assigned-attributes
  done
  pt deactivate || fail deactivate
  (( ! ${+NEW} )) || fail unset
  eq "$EMPTY" '' empty
  eq "$PLAIN" baseline plain
  eq "${parameters[PLAIN]}" scalar plain-attributes
  eq "$EXPORTED" baseline exported
  eq "${parameters[EXPORTED]}" scalar-export exported-attributes
  eq "$NUMBER" '16#1F' integer
  eq "$FIXED" 1.235 float-display
  eq "$(printf '%.17g' FIXED)" "$old_fixed" float-value
  eq "$SCI" 1.235e+03 scientific-display
  eq "$(printf '%.17g' SCI)" "$old_sci" scientific-value
  eq "$(typeset -p UPPER)" 'typeset -u UPPER=abc' case-attribute
  eq "$PAD" 'ab   ' padding
  eq "$HIDDEN" hidden-baseline hidden
  eq "${parameters[HIDDEN]}" scalar-hideval hidden-attribute
  (( ! ${+PT_ENV_NAME} )) || fail prompt-cleared
done
[[ ! -e should-not-exist ]] || fail executed
""")

    def test_local_template_precedence_and_captured_values(self):
        (self.work / "sample.env").write_text("ACCOUNT=local\n")
        (self.templates / "sample.env").write_text("ACCOUNT=$LOWPRIV\nPASSWORD=$LOWPRIVPW\n")
        self.run_zsh("""
LOWPRIV=synthetic-user LOWPRIVPW=synthetic-password
ACCOUNT=baseline
pt sample || fail local
eq "$ACCOUNT" local precedence
pt activate --template sample || fail template
eq "$ACCOUNT" synthetic-user captured
LOWPRIV=changed
eq "$ACCOUNT" synthetic-user static-value
eq "$PASSWORD" synthetic-password template-value
pt deactivate || fail deactivate
eq "$ACCOUNT" baseline restore
(( ! ${+PASSWORD} )) || fail remove-new
if pt activate --template missing; then fail missing-template; fi
""")

    def test_source_tracks_unsets_and_attribute_only_changes(self):
        (self.work / "changes.env").write_text(
            "unset EXPORTED\nexport SAME\ntypeset -g -H HIDDEN=changed\n"
        )
        self.run_zsh("""
export EXPORTED=baseline
SAME=unchanged
typeset -H HIDDEN=baseline
pt changes || fail activate
(( ${+_pt_managed[EXPORTED]} && ${+_pt_managed[SAME]} && ${+_pt_managed[HIDDEN]} )) || fail tracking
pt status
pt deactivate || fail deactivate
eq "$EXPORTED" baseline unset-restoration
eq "${parameters[EXPORTED]}" scalar-export export-restoration
eq "${parameters[SAME]}" scalar attribute-restoration
eq "$HIDDEN" baseline hidden-restoration
""")

    def test_protected_and_unsupported_parameters(self):
        self.run_zsh("""
typeset -a ARRAY=(one two)
typeset -A MAP=(key value)
readonly FIXED=constant
pt scratch || fail activate
for name in ARRAY MAP FIXED PATH path HOME PWD status _pt_dirty PT_ENV_NAME PT_GUARD_MODE 'A[1]' 'A=x'; do
  if pt set "$name" changed; then fail protected; fi
done
eq "$FIXED" constant readonly
eq "$ARRAY[1]" one array
pt deactivate || fail deactivate
""")

    def test_failed_load_restores_scalars(self):
        (self.work / "broken.env").write_text("ORIGINAL=changed\nNEW=created\nreturn 1\n")
        self.run_zsh("""
ORIGINAL=baseline
if pt broken; then fail failed-load; fi
eq "$ORIGINAL" baseline rollback
(( ! ${+NEW} && ! ${+PT_ENV_NAME} && ! _pt_active )) || fail rollback-state
""")

    def test_unsupported_source_changes_are_diagnosed(self):
        (self.work / "array.env").write_text("typeset -ga ARRAY=(changed)\nNORMAL=changed\n")
        result = self.run_zsh("""
NORMAL=baseline
if pt array; then fail unsupported-load; fi
eq "$NORMAL" baseline scalar-rollback
""")
        self.assertIn("unsupported change to ARRAY", result.stderr)

    def test_loading_is_not_reentrant_and_irreversible_changes_are_explicit(self):
        (self.work / "recursive.env").write_text("TARGET=changed\npt nested\n")
        (self.work / "readonly.env").write_text("typeset -gr TARGET=locked\n")
        result = self.run_zsh("""
TARGET=baseline
if pt recursive; then fail recursive-load; fi
eq "$TARGET" baseline recursive-rollback
(( ! _pt_active )) || fail recursive-state
if pt readonly; then fail readonly-load; fi
(( _pt_active )) || fail incomplete-state
if pt deactivate; then fail incomplete-restoration; fi
""")
        self.assertIn("cannot run while loading", result.stderr)
        self.assertIn("restoration incomplete", result.stderr)

    def test_save_refuses_template_directories_including_symlinks(self):
        template = self.templates / "saved.env"
        template.write_text("TARGET=original\n")
        (self.work / "template-link").symlink_to(self.templates, target_is_directory=True)
        self.run_zsh("""
pt scratch || fail activate
pt set TARGET synthetic || fail set
cd template-link || fail cd
if pt save --force saved; then fail template-overwrite; fi
mkdir nested
cd nested || fail cd-nested
if pt save new; then fail template-nested; fi
""")
        self.assertEqual(template.read_text(), "TARGET=original\n")
        self.assertFalse((self.templates / "nested" / "new.env").exists())

    def test_switch_discards_without_confirmation_or_nesting(self):
        self.run_zsh("""
TARGET=baseline
pt first || fail first
pt set TARGET override || fail set
pt second || fail switch
eq "$TARGET" baseline switch-restored
eq "$PT_ENV_NAME" second switch-name
pt set TARGET other || fail set
pt deactivate || fail discard
eq "$TARGET" baseline no-nesting
""")

    def test_quoting_save_load_and_explicit_status(self):
        result = self.run_zsh(r"""
BASE=baseline
pt scratch || fail activate
value=$'spaces "double" \'single\' $HOME $(touch executed) `touch executed` \\ ü\nsecond line\n'
pt set PAYLOAD "$value" || fail set
pt set EMPTY '' || fail empty
pt set BASE temporary || fail baseline
pt save saved || fail save
eq "$PT_ENV_NAME" saved saved-name
eq "$_pt_dirty" 0 clean
[[ $(stat -c %a saved.env) == 600 ]] || fail permissions
[[ $(<saved.env) != *'HOME='* ]] || fail full-environment
pt deactivate || fail deactivate
eq "$BASE" baseline restoration
pt saved || fail reload
eq "$PAYLOAD" "$value" literal-roundtrip
eq "$EMPTY" '' empty-roundtrip
eq "${parameters[PAYLOAD]}" scalar-export export-roundtrip
pt status
[[ ! -e executed ]] || fail code-execution
pt deactivate || fail deactivate
""")
        self.assertIn("Dirty: no", result.stdout)
        self.assertIn("EMPTY=''", result.stdout)
        self.assertIn("PAYLOAD=", result.stdout)

    def test_save_unset_and_numeric_attributes(self):
        (self.work / "typed.env").write_text(
            "unset REMOVE\ntypeset -gi16 NUMBER=31\ntypeset -gF 3 FIXED=1.234567891234567\n"
            "typeset -gu CASE=abc\ntypeset -gH HIDDEN=hidden-value\n"
        )
        self.run_zsh("""
REMOVE=baseline
pt typed || fail activate
old=$(printf '%.17g' FIXED)
pt save saved || fail save
pt deactivate || fail deactivate
eq "$REMOVE" baseline restore-unset
pt saved || fail reload
(( ! ${+REMOVE} )) || fail explicit-unset
eq "$NUMBER" '16#1F' numeric-flags
eq "$FIXED" 1.235 float-flags
eq "$(printf '%.17g' FIXED)" "$old" float-exact
eq "$(typeset -p CASE)" 'typeset -u CASE=abc' case-flags
eq "$HIDDEN" hidden-value hidden-value
eq "${parameters[HIDDEN]}" scalar-hideval hidden-flags
pt status
pt deactivate || fail deactivate
""")

    def test_save_protections_and_preserved_state(self):
        (self.work / "existing.env").write_text("ORIGINAL=preserved\n")
        (self.work / "pentest.env").write_text("MASTER=untouched\n")
        (self.work / "linked.env").symlink_to("existing.env")
        (self.work / "directory.env").mkdir()
        self.run_zsh("""
pt scratch || fail activate
pt set TARGET synthetic || fail set
for name in existing linked directory pentest ../escape; do
  if pt save "$name"; then fail unsafe-save; fi
done
if pt save --force linked; then fail forced-symlink; fi
eq "$(<existing.env)" ORIGINAL=preserved preserved
eq "$(<pentest.env)" MASTER=untouched master
eq "$PT_ENV_NAME" scratch name-on-failure
eq "$_pt_dirty" 1 dirty-on-failure
pt save --force existing || fail force
eq "$PT_ENV_NAME" existing adopt
[[ $(stat -c %a existing.env) == 600 ]] || fail overwrite-permissions
[[ -z $(print -rl -- .pt-save.*(N)) ]] || fail temporary-cleanup
""")

    def test_failed_publish_and_failed_permissions_preserve_destination(self):
        (self.work / "existing.env").write_text("ORIGINAL=preserved\n")
        self.run_zsh("""
pt scratch || fail activate
pt set TARGET value || fail set
mkdir bin
print -r -- '#!/bin/sh\nexit 1' > bin/mv
chmod +x bin/mv
PATH=$PWD/bin:$PATH
if pt save --force existing; then fail failed-move; fi
eq "$(<existing.env)" ORIGINAL=preserved old-file
eq "$PT_ENV_NAME" scratch old-name
eq "$_pt_dirty" 1 old-dirty
print -r -- '#!/bin/sh\nexit 1' > bin/chmod
chmod +x bin/chmod
rehash
if pt save new; then fail failed-permissions; fi
[[ ! -e new.env ]] || fail unpublished
[[ -z $(print -rl -- .pt-save.*(N)) ]] || fail cleanup
""")

    def test_list_and_rename_never_modify_templates(self):
        (self.work / "local.env").write_text("SECRET=local-marker\n")
        (self.work / "pentest.env").write_text("SECRET=master-marker\n")
        template = self.templates / "template.env"
        template.write_text("SECRET=template-marker\n")
        before = template.read_bytes()
        result = self.run_zsh("""
pt list
pt activate --template template || fail template
pt rename renamed || fail rename
[[ ! -e renamed.env ]] || fail rename-wrote
pt save || fail save
[[ -e renamed.env ]] || fail save-local
""")
        self.assertIn("local     local", result.stdout)
        self.assertIn("template  template", result.stdout)
        self.assertNotIn("SECRET=", result.stdout)
        self.assertNotIn("master-marker", result.stdout)
        self.assertEqual(template.read_bytes(), before)

    def test_guard_configuration_and_static_analysis(self):
        self.run_zsh(r"""
eq "$PT_GUARD_MODE" off default
pt guard warn || fail warn
eq "$PT_GUARD_MODE" warn mode
pt guard block || fail block
if pt guard invalid; then fail invalid; fi
pt scratch || fail activate
pt unset TARGET || fail unset-target
typeset -ga PT_OPTIONAL_VARS=(ACCOUNT)
_pt_guard_check 'nxc smb "$TARGET" -u "$ACCOUNT" -p "${PASSWORD:-}" $UNRELATED'
eq "${(j: :)_pt_guard_missing}" 'TARGET UNRELATED' missing
_pt_guard_check 'echo ${PASSWORD:-fallback} ${TARGET:-}'
eq "${#_pt_guard_missing}" 0 defaults
_pt_guard_check 'echo ${TARGET:-fallback} "$TARGET"'
eq "${(j: :)_pt_guard_missing}" TARGET mixed-required
_pt_guard_check 'echo ${TARGET:=mutated} $(touch executed)'
(( ! ${+TARGET} )) || fail no-assignment
[[ ! -e executed ]] || fail no-execution
(( ${#_pt_scan_unchecked} )) || fail unchecked
""")

    def test_guard_detects_unmanaged_variables_without_configuration(self):
        self.run_zsh(r"""
unset PT_CHECK_VARS DOMAIN EMPTY UNKNOWN
TARGET=server01 ACCOUNT=test-user PASSWORD=synthetic-password EMPTY=''
_pt_guard_check 'netexec smb $TARGET -u $ACCOUNT -p $PASSWORD -d $DOMAIN'
eq "${(j: :)_pt_guard_missing}" DOMAIN unmanaged-unset
_pt_guard_check 'print "$EMPTY" "${UNKNOWN}" "$DOMAIN" "$DOMAIN"'
eq "${(j: :)_pt_guard_missing}" 'UNKNOWN DOMAIN' empty-valid-and-deduplicated
DOMAIN=example
_pt_guard_check 'print "$DOMAIN"'
eq "${#_pt_guard_missing}" 0 populated
unset DOMAIN
typeset -ga PT_OPTIONAL_VARS=(DOMAIN)
_pt_guard_check 'print "$DOMAIN" "${UNKNOWN:-}"'
eq "${#_pt_guard_missing}" 0 exemptions
PT_OPTIONAL_VARS=()
_pt_guard_check "print '\$DOMAIN' \\\$UNKNOWN \"\${DOMAIN:-fallback}\""
eq "${#_pt_guard_missing}" 0 literal-and-default
""")

    def test_preview_renders_commands_without_evaluating_values(self):
        self.run_zsh(r"""
TARGET=server01 ACCOUNT='user name' PASSWORD='literal $(touch executed)'
_pt_render_preview 'nxc smb "$TARGET" -u "$ACCOUNT" -p "$PASSWORD"'
eq "$_pt_preview_command" 'nxc smb "server01" -u "user name" -p "literal \$(touch executed)"' rendered-nxc
DOMAIN=example
_pt_render_preview 'impacket-smbclient "${DOMAIN}/${ACCOUNT}:${PASSWORD}@${TARGET}"'
eq "$_pt_preview_command" 'impacket-smbclient "example/user name:literal \$(touch executed)@server01"' rendered-impacket
_pt_render_preview 'echo $ACCOUNT $TARGET $ACCOUNT'
eq "$_pt_preview_command" "echo 'user name' server01 'user name'" repeated-unquoted
_pt_render_preview 'echo '\''$TARGET'\'' \$TARGET "$TARGET"'
eq "$_pt_preview_command" 'echo '\''$TARGET'\'' \$TARGET "server01"' literal-contexts
PASSWORD=$'a"$`\\b\nü'
_pt_render_preview 'echo "$PASSWORD"'
[[ $_pt_preview_command != *$'\n'* && $_pt_preview_command == *'\n'* ]] || fail control-byte-display
[[ ! -e executed ]] || fail no-execution
""")

    def test_preview_defaults_and_partial_commands(self):
        self.run_zsh(r"""
unset MISSING
EMPTY='' TARGET=server01
_pt_render_preview 'echo "${MISSING:-fallback}" "${EMPTY:-fallback}" "${EMPTY-fallback}" "${TARGET:-fallback}"'
eq "$_pt_preview_command" 'echo "fallback" "fallback" "" "server01"' defaults
_pt_render_preview 'echo "${MISSING:-}" "$MISSING"'
eq "$_pt_preview_command" 'echo "" ""' unset-values
_pt_render_preview 'echo "$TARGET" $(touch executed) "$EMPTY"'
eq "$_pt_preview_command" 'echo "server01" $(touch executed) "$EMPTY"' partial
(( ${#_pt_scan_unchecked} )) || fail unchecked
_pt_render_preview 'echo ${TARGET:=changed}'
eq "$_pt_preview_command" 'echo ${TARGET:=changed}' unsupported-expression
eq "$TARGET" server01 no-side-effect
[[ ! -e executed ]] || fail no-execution
""")

    def test_completion_names_never_source_files_or_expose_values(self):
        (self.work / "localonly.env").write_text("touch sourced\nPASSWORD=never-display\n")
        (self.work / "pentest.env").write_text("touch sourced\n")
        (self.templates / "templonly.env").write_text("touch sourced\n")
        self.run_zsh("""
_pt_completion_names all
eq "${(j: :)_pt_completion_candidates}" 'localonly templonly' environments
_pt_completion_names templates
eq "${(j: :)_pt_completion_candidates}" templonly templates
ZTEST_TARGET=never-display
readonly ZTEST_READONLY=never-display
pt scratch || fail activate
pt set ZTEST_GONE synthetic || fail managed
unset ZTEST_GONE
typeset -a PT_CHECK_VARS=(ZTEST_CONFIGURED)
_pt_completion_names parameters
(( ${_pt_completion_candidates[(Ie)ZTEST_TARGET]} )) || fail variable-name
(( ${_pt_completion_candidates[(Ie)ZTEST_GONE]} && ${_pt_completion_candidates[(Ie)ZTEST_CONFIGURED]} )) || fail unset-names
(( ! ${_pt_completion_candidates[(Ie)ZTEST_READONLY]} && ! ${_pt_completion_candidates[(Ie)PWD]} )) || fail protected
[[ ${(j: :)_pt_completion_candidates} != *never-display* ]] || fail value-leak
[[ ! -e sourced ]] || fail file-execution
""")

    def test_scanner_quotes_escapes_and_unsupported_syntax(self):
        self.run_zsh(r"""
MATCH=baseline-match
typeset -a match=(baseline-capture)
_pt_scan 'nxc smb "$TARGET" -u ${ACCOUNT} -p '\''$LITERAL'\'' \$ESCAPED $REAL'
eq "${(j: :)_pt_scan_names}" 'TARGET ACCOUNT REAL' quotes
eq "${#_pt_scan_unchecked}" 0 supported
eq "$MATCH" baseline-match regex-state
eq "$match[1]" baseline-capture regex-captures
_pt_scan 'impacket-smbclient "${DOMAIN}/${ACCOUNT}:${PASSWORD}@${TARGET}"'
eq "${(j: :)_pt_scan_names}" 'DOMAIN ACCOUNT PASSWORD TARGET' impacket
_pt_scan 'echo "$DOUBLE" "\$ESCAPED" $'\''$ANSI\'\''quoted'\'''
eq "${(j: :)_pt_scan_names}" DOUBLE ansi-and-double
for text in 'echo $(touch executed)' 'echo `touch executed`' 'echo $((1+2))' 'cat <<EOF' 'cat <(touch executed)' 'echo ${TARGET[1]}' 'echo ${TARGET:-$OTHER}' 'echo "unfinished'; do
  _pt_scan "$text"
  (( ${#_pt_scan_unchecked} )) || fail unsupported
done
[[ ! -e executed ]] || fail no-execution
""")


class Terminal:
    @staticmethod
    def plain(output):
        return re.sub(rb"\x1b\[[0-9;]*m", b"", output)

    def __init__(self, case, rc):
        (case.home / ".zshrc").write_text(rc)
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(case.work)
            os.execve(ZSH, [ZSH, "-i"], case.env)
        self.output = b""
        self.sequence = 0
        case.addCleanup(self.close)
        self.expect("PTREADY> ")

    def send(self, text):
        os.write(self.fd, text.encode())

    def expect(self, text, timeout=5):
        target = text.encode()
        deadline = time.monotonic() + timeout
        while target not in self.plain(self.output):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(f"terminal did not show {text!r}: {self.output!r}")
            if select.select([self.fd], [], [], remaining)[0]:
                try:
                    chunk = os.read(self.fd, 65536)
                except OSError as error:
                    raise AssertionError(f"terminal closed: {self.output!r}") from error
                if not chunk:
                    raise AssertionError(f"terminal exited: {self.output!r}")
                self.output += chunk
        end = self.plain(self.output).index(target) + len(target)
        for escape in re.finditer(rb"\x1b\[[0-9;]*m", self.output):
            if escape.start() > end:
                break
            end += escape.end() - escape.start()
        consumed, self.output = self.output[:end], self.output[end:]
        return consumed

    def command(self, text):
        self.sequence += 1
        marker = f"PTSYNC{self.sequence}"
        self.send(text + f"; print -r -- PT''SYNC{self.sequence}\r")
        output = self.expect(marker + "\r\n")
        return output + self.expect("PTREADY> ")

    def close(self):
        try:
            os.kill(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        os.waitpid(self.pid, 0)
        os.close(self.fd)


class TerminalTests(IsolatedTest):
    def terminal(self, before="", after=""):
        return Terminal(self, """
setopt no_beep
bindkey -e
""" + before + """
source "$PT_PLUGIN"
PROMPT='PTREADY> '
RPROMPT=''
""" + after)

    def test_load_confirms_only_changed_defined_variables(self):
        (self.work / "overlay.env").write_text(
            "ACCOUNT=merged; PASSWORD=new-password; unset -- TARGET; NEW=added; EQUAL=same\n"
            "print -r -- sourced >> source-count\n"
        )
        term = self.terminal()
        term.command("ACCOUNT=baseline; PASSWORD=''; TARGET=baseline-target; EQUAL=same")
        term.command("pt activate")
        term.send("pt load overlay\r")
        output = term.expect("pt: replace ACCOUNT: 'baseline' -> 'merged'? [y/N] ")
        term.send("y\r")
        output += term.expect("pt: replace PASSWORD: '' -> 'new-password'? [y/N] ")
        term.send("\r")  # Empty reply keeps an explicitly empty password.
        output += term.expect("pt: replace TARGET: 'baseline-target' -> <unset>? [y/N] ")
        term.send("y\r")
        output += term.expect("PTREADY> ")
        self.assertNotIn(b"replace EQUAL", output)
        self.assertNotIn(b"replace NEW", output)
        self.assertEqual((self.work / "source-count").read_text(), "sourced\n")
        output = term.command('[[ $ACCOUNT == merged && $PASSWORD == "" && ${+PASSWORD} == 1 && ${+TARGET} == 0 && $NEW == added ]] && print MERGE_OK')
        self.assertIn(b"\r\nMERGE_OK\r\n", output)
        term.command("pt deactivate")
        output = term.command('[[ $ACCOUNT == baseline && $TARGET == baseline-target && ${+NEW} == 0 ]] && print RESTORE_OK')
        self.assertIn(b"\r\nRESTORE_OK\r\n", output)

    def test_load_declining_all_conflicts_keeps_dirty_and_managed_state(self):
        (self.work / "overlay.env").write_text("ACCOUNT=merged\n")
        term = self.terminal()
        term.command("pt activate")
        term.command("pt set ACCOUNT working")
        term.command("pt save saved")
        term.send("pt load overlay\r")
        term.expect("pt: replace ACCOUNT: 'working' -> 'merged'? [y/N] ")
        term.send("n\r")
        term.expect("PTREADY> ")
        output = term.command('[[ $ACCOUNT == working && $_pt_dirty == 0 && ${+_pt_managed[ACCOUNT]} == 1 ]] && print KEPT_OK')
        self.assertIn(b"\r\nKEPT_OK\r\n", output)

    def test_load_confirmation_quotes_control_bytes_and_shows_attribute_changes(self):
        (self.work / "baseline.env").write_text(r"VALUE=$'old\nline\e[31m'" + "\n")
        (self.work / "overlay.env").write_text(r"VALUE=$'new\t$(touch should-not-exist)'" + "\n")
        (self.work / "attributes.env").write_text("typeset -gi10 NUMBER=31\n")
        term = self.terminal()
        term.command("pt baseline")
        term.send("pt load overlay\r")
        output = term.expect("[y/N] ")
        self.assertIn(b"old\\nline", output)
        self.assertIn(b"new\\t$(touch should-not-exist)", output)
        self.assertNotIn(b"\x1b[31m", output)
        self.assertRegex(output, rb"replace VALUE: [^\r\n]* -> [^\r\n]*\? \[y/N\]")
        term.send("n\r")
        term.expect("PTREADY> ")
        self.assertFalse((self.work / "should-not-exist").exists())
        term.command("typeset -gi16 NUMBER=31")
        term.send("pt load attributes\r")
        term.expect("pt: replace NUMBER: '31' (-i16) -> '31' (-i10)? [y/N] ")
        term.send("n\r")
        term.expect("PTREADY> ")

    def test_load_cancel_after_approval_keeps_all_pre_load_variables(self):
        (self.work / "overlay.env").write_text("ACCOUNT=merged; PASSWORD=new; NEW=added\n")
        for cancel in ("\x04", "\x03"):
            with self.subTest(cancel=repr(cancel)):
                term = self.terminal()
                term.command("ACCOUNT=baseline; PASSWORD=''")
                term.command("pt activate")
                term.send("pt load overlay\r")
                term.expect("pt: replace ACCOUNT: 'baseline' -> 'merged'? [y/N] ")
                term.send("y\r")
                term.expect("pt: replace PASSWORD: '' -> 'new'? [y/N] ")
                term.send(cancel)
                term.expect("PTREADY> ")
                output = term.command('[[ $ACCOUNT == baseline && $PASSWORD == "" && ${+NEW} == 0 && $_pt_dirty == 0 ]] && print CANCEL_OK')
                self.assertIn(b"\r\nCANCEL_OK\r\n", output)

    def test_hidden_input_and_cancellation(self):
        term = self.terminal()
        term.command("pt scratch")
        term.send("pt set PASSWORD\r")
        term.expect("Ctrl-C to cancel): ")
        term.send("synthetic-hidden-input\r")
        output = term.expect("PTREADY> ")
        self.assertNotIn(b"synthetic-hidden-input", output)
        output = term.command('[[ $PASSWORD == synthetic-hidden-input ]] && print INPUT_OK')
        self.assertIn(b"\r\nINPUT_OK\r\n", output)
        term.send("pt set PASSWORD\r")
        term.expect("Ctrl-C to cancel): ")
        term.send("discarded\x03")
        term.expect("PTREADY> ")
        output = term.command('[[ $PASSWORD == synthetic-hidden-input ]] && print CANCEL_OK')
        self.assertIn(b"\r\nCANCEL_OK\r\n", output)

    def test_overwrite_cancel_and_accept(self):
        destination = self.work / "saved.env"
        destination.write_text("BASELINE=old\n")
        term = self.terminal()
        term.command("pt scratch")
        term.command("pt set TARGET synthetic")
        term.send("pt save saved\r")
        term.expect("[y/N] ")
        term.send("n\r")
        term.expect("PTREADY> ")
        self.assertEqual(destination.read_text(), "BASELINE=old\n")
        term.send("pt save saved\r")
        term.expect("[y/N] ")
        term.send("y\r")
        term.expect("pt: saved ./saved.env")
        self.assertIn("TARGET=", destination.read_text())

    def test_preview_never_executes_or_changes_buffer(self):
        term = self.terminal(after="""
test_buffer() { print -rn -- "$BUFFER" > buffer-copy; print -r -- "$CURSOR" > cursor-copy; }
zle -N test-buffer test_buffer
bindkey '^X^B' test-buffer
HISTFILE=$HOME/test-history
SAVEHIST=100
""")
        term.command("pt scratch")
        term.command("pt set TARGET synthetic-preview-only")
        buffer = 'print -r -- "$TARGET" $(touch executed)'
        term.send(buffer + "\x18\x10")
        output = term.expect("Unchecked:")
        self.assertIn(b'pt preview: print -r -- "synthetic-preview-only"', output)
        self.assertNotIn(b"TARGET=", output)
        self.assertNotIn(b"Command (", output)
        self.assertFalse((self.work / "executed").exists())
        term.send("\x18\x02")
        deadline = time.monotonic() + 2
        while not (self.work / "buffer-copy").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual((self.work / "buffer-copy").read_text(), buffer)
        self.assertEqual(int((self.work / "cursor-copy").read_text()), len(buffer))
        term.send("\x03")
        term.expect("PTREADY> ")
        self.assertFalse((self.work / "executed").exists())
        term.command("fc -W")
        history = (self.home / "test-history").read_text()
        self.assertNotIn("$(touch executed)", history)
        self.assertNotIn('print -r -- "synthetic-preview-only"', history)

    def test_preview_escape_then_preview_preserves_buffer_in_both_keymaps(self):
        for mode in ("emacs", "vi"):
            with self.subTest(mode=mode):
                before = "bindkey -v\n" if mode == "vi" else ""
                if all(os.environ.get(key) for key in ("PT_TEST_AUTOSUGGEST", "PT_TEST_SYNTAX")):
                    for key in ("PT_TEST_AUTOSUGGEST", "PT_TEST_SYNTAX"):
                        self.env[key] = os.environ[key]
                        before += f'source "${key}"\n'
                term = self.terminal(before=before, after='''
test_preview_state() {
  print -rl -- "$BUFFER" "$CURSOR" "$KEYMAP" "$_pt_preview_open" > preview-state
  zle -M STATE_CAPTURED
}
zle -N test-preview-state test_preview_state
bindkey -M emacs '^X^B' test-preview-state
bindkey -M viins '^X^B' test-preview-state
bindkey -M vicmd '^X^B' test-preview-state
''')
                term.command("TARGET=synthetic-preview; print -sr -- HISTORY_SENTINEL")
                original = 'netexec smb "$TARGET"; touch preview-executed'
                expected = 'pt preview: netexec smb "synthetic-preview"; touch preview-executed'
                term.send(original + "\x18\x10")
                term.expect(expected)
                term.send("\x18\x10\x18\x10")
                term.expect(expected)
                term.send("\x1b")
                time.sleep(0.6)
                term.send("\x18\x02")
                term.expect("STATE_CAPTURED")
                if mode == "emacs":
                    state = (self.work / "preview-state").read_text().splitlines()
                    self.assertEqual(state[0], original)
                    self.assertEqual(state[3], "0")
                term.send("\x18\x10")
                term.expect(expected)
                term.send("\x18\x02")
                term.expect("STATE_CAPTURED")
                state = (self.work / "preview-state").read_text().splitlines()
                self.assertEqual(state[0], original)
                self.assertEqual(int(state[1]), len(original) - (mode == "vi"))
                if mode == "vi":
                    self.assertEqual(state[2], "vicmd")
                self.assertFalse((self.work / "preview-executed").exists())

    def test_escape_dismisses_preview_before_cancelling_guarded_command(self):
        term = self.terminal(after='''
test_preview_guard_state() {
  print -rl -- "$_pt_preview_open" "$_pt_guard_pending" "$BUFFER" > preview-guard-state
  zle -M STATE_CAPTURED
}
zle -N test-preview-guard-state test_preview_guard_state
bindkey '^X^B' test-preview-guard-state
''')
        term.command("pt activate")
        term.command("pt guard block")
        original = 'print "$MISSING"; touch preview-guard-executed'
        term.send(original + "\r")
        term.expect("[Esc] abort")
        term.send("\x18\x10")
        term.expect('pt preview: print ""; touch preview-guard-executed')
        term.send("\x1b")
        time.sleep(0.6)
        term.send("\x18\x02")
        term.expect("STATE_CAPTURED")
        self.assertEqual((self.work / "preview-guard-state").read_text(), "0\n1\n" + original + "\n")
        term.send("\x1b")
        term.expect("PTREADY> ")
        self.assertFalse((self.work / "preview-guard-executed").exists())

    def test_empty_hidden_password_passes_guard_but_unset_blocks(self):
        term = self.terminal()
        term.command("pt activate")
        term.command("pt guard block")
        term.send("pt set PASSWORD\r")
        term.expect("Ctrl-C to cancel): ")
        term.send("\r")
        term.expect("PTREADY> ")
        term.command('print -rn -- "$PASSWORD" > empty-password; touch empty-accepted')
        self.assertTrue((self.work / "empty-accepted").exists())
        self.assertEqual((self.work / "empty-password").read_text(), "")
        term.command("pt unset PASSWORD")
        term.send('print -rn -- "$PASSWORD"; touch unset-accepted\r')
        output = term.expect("Define variables to run;")
        self.assertIn(b"pt: missing PASSWORD.", term.plain(output))
        self.assertFalse((self.work / "unset-accepted").exists())
        term.send("\x03")
        term.expect("PTREADY> ")

    def test_terminal_status_and_guard_colors(self):
        term = self.terminal()
        term.command("pt activate")
        term.command("pt set PASSWORD ''")
        term.command("pt unset DOMAIN")
        output = term.command("pt status")
        self.assertIn(b"\x1b[1mEnvironment: scratch\r\nSource: <empty>\x1b[0m", output)
        self.assertIn(b"PASSWORD=''", output)
        self.assertIn(b"DOMAIN=<unset>", output)
        self.assertNotIn(b"Dirty:", output)
        self.assertNotIn(b"\x1b[32mPASSWORD", output)
        term.command("pt guard warn")
        term.send('print "$DOMAIN"\r')
        output = term.expect("[Esc] abort")
        self.assertNotIn(b"^[[33m", output)
        # Guard messages use native plain text even when status colors are enabled.
        self.assertIn(b"pt: missing DOMAIN. [Enter]", output)
        self.assertNotRegex(output, rb"\x1b\[[0-9;]*(?:31|33|36)m")
        term.send("\x1b")
        time.sleep(0.6)
        term.command("PT_COLOR=never")
        output = term.command("pt status")
        self.assertNotIn(b"\x1b[33mDOMAIN", output)
        self.assertIn(b"DOMAIN=<unset>", output)
        term.send('print "$DOMAIN"\r')
        output = term.expect("[Esc] abort")
        self.assertNotRegex(output, rb"\x1b\[[0-9;]*(?:31|33)m")

    def test_escape_clears_guarded_command_and_preserves_longer_sequences(self):
        term = self.terminal(after="""
test_guard_buffer() { print -rn -- "$BUFFER" > guard-buffer; print -r -- "$_pt_guard_pending" > guard-pending; }
zle -N test-guard-buffer test_guard_buffer
bindkey '^X^B' test-guard-buffer
""")
        term.command("pt guard warn")
        original = 'print "$TARGET" "$DOMAIN"; touch never-executed'
        term.send(original + "\r")
        output = term.expect("[Esc] abort")
        self.assertIn(b"pt: missing TARGET, DOMAIN.", output)
        # Arrow and Alt sequences must not invoke the standalone Escape binding.
        term.send("\x1b[D\x1bb\x18\x02")
        deadline = time.monotonic() + 2
        while not (self.work / "guard-buffer").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual((self.work / "guard-buffer").read_text(), original)
        term.send("\x1b")
        time.sleep(0.6)  # Standalone Escape is resolved using Zsh's KEYTIMEOUT.
        term.command("touch after-escape")
        self.assertTrue((self.work / "after-escape").exists())
        self.assertFalse((self.work / "never-executed").exists())
        term.command("pt activate")
        term.command("pt set TARGET synthetic")
        term.command("pt set DOMAIN example")
        term.command('print "$TARGET" "$DOMAIN" > recovered')
        self.assertEqual((self.work / "recovered").read_text(), "synthetic example\n")

    def test_guard_cancel_keeps_literal_command_in_history_for_recall(self):
        term = self.terminal(after="""
HISTFILE=$HOME/test-history
SAVEHIST=100
test_history_buffer() { print -rn -- "$BUFFER" > recalled-buffer; }
zle -N test-history-buffer test_history_buffer
bindkey '^X^B' test-history-buffer
""")
        term.command("pt guard block")
        original = 'print -r -- "$DOMAIN" "$(touch cancelled-substitution)"; touch cancelled-executed'
        term.send(original + "\r")
        term.expect("[Esc] abort")
        term.send("\x1b")
        time.sleep(0.6)
        # Run the missing-variable assignment, then recall through native history.
        term.command("DOMAIN=example")
        term.send("\x10\x10\x18\x02")
        deadline = time.monotonic() + 2
        while not (self.work / "recalled-buffer").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual((self.work / "recalled-buffer").read_text(), original)
        self.assertFalse((self.work / "cancelled-executed").exists())
        self.assertFalse((self.work / "cancelled-substitution").exists())
        term.send("\x15")
        term.command("fc -W")
        history = (self.home / "test-history").read_text()
        self.assertEqual(history.count(original), 1)
        self.assertNotIn("pt: missing", history)
        self.assertNotIn('print -r -- "example"', history)

    def test_edit_from_guard_includes_missing_variables_and_keeps_command(self):
        self.fake_editor(r"""
print -r -- EDITOR_READY
IFS= read -r reply
print -r -- "ACCOUNT='edited user'" "DOMAIN=example" "TARGET=server01" > "$1"
""")
        term = self.terminal(after="""
test_edited_buffer() { print -rn -- "$BUFFER" > edited-buffer; print -r -- "$CURSOR" > edited-cursor; }
zle -N test-edited-buffer test_edited_buffer
bindkey '^X^B' test-edited-buffer
""")
        term.command("pt activate")
        term.command("pt set ACCOUNT initial")
        term.command("pt guard block")
        original = 'print "$TARGET" "$DOMAIN" "$ACCOUNT"; touch editor-command-executed'
        term.send(original + "\r")
        term.expect("[Ctrl-X, E] edit;")
        term.send("\x18e")
        term.expect("EDITOR_READY")
        term.send("\r")
        term.expect("pt: all required variables defined.")
        term.expect(original)
        term.send("\x18\x02")
        deadline = time.monotonic() + 2
        while not (self.work / "edited-buffer").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual((self.work / "edited-buffer").read_text(), original)
        self.assertEqual(int((self.work / "edited-cursor").read_text()), len(original))
        initial = (self.home / "editor-before").read_text()
        self.assertIn("ACCOUNT=", initial)
        self.assertIn("# DOMAIN=''", initial)
        self.assertIn("# TARGET=''", initial)
        self.assertFalse((self.work / "editor-command-executed").exists())
        term.send("\r")
        term.expect("PTREADY> ")
        self.assertTrue((self.work / "editor-command-executed").exists())

    def test_guard_edit_cancellation_keeps_environment_and_command(self):
        self.fake_editor('exit 1\n')
        term = self.terminal(after="""
test_cancelled_edit_buffer() { print -rn -- "$BUFFER" > cancelled-edit-buffer; }
zle -N test-cancelled-edit-buffer test_cancelled_edit_buffer
bindkey '^X^B' test-cancelled-edit-buffer
""")
        term.command("pt activate")
        term.command("pt set ACCOUNT original")
        term.command("pt guard block")
        original = 'print "$TARGET"; touch cancelled-editor-command'
        term.send(original + "\r")
        term.expect("[Ctrl-X, E] edit;")
        term.send("\x18e")
        term.expect("pt: missing TARGET.")
        term.send("\x18\x02")
        deadline = time.monotonic() + 2
        while not (self.work / "cancelled-edit-buffer").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual((self.work / "cancelled-edit-buffer").read_text(), original)
        self.assertFalse((self.work / "cancelled-editor-command").exists())
        term.send("\x15")
        self.assertIn(b"ACCOUNT=$'original'", term.command("pt status"))

    def test_guard_after_unchanged_edit_keeps_command_warning_and_escape(self):
        self.fake_editor('print -r -- EDITOR_RETAINED\nexit 0\n')
        term = self.terminal(after="""
test_returned_guard() { print -rn -- "$BUFFER" > returned-buffer; print -r -- "$_pt_guard_pending" > returned-pending; }
zle -N test-returned-guard test_returned_guard
bindkey '^X^B' test-returned-guard
""")
        term.command("pt activate")
        term.command("pt guard block")
        original = 'print "$TARGET" "$PASSWORD"; touch returned-edit-executed'
        term.send(original + "\r")
        term.expect("[Esc] abort")
        # Native ZLE redisplay keeps the command available beside its prompt.
        redraw = term.expect(original)
        self.assertIn(original.encode(), term.plain(redraw))
        term.send("\x18e")
        term.expect("EDITOR_RETAINED")
        output = term.expect("[Esc] abort")
        self.assertIn(b"pt: missing TARGET, PASSWORD.", output)
        self.assertNotRegex(output, rb"\x1b\[[0-9;]*(?:31|33|36)m")
        redraw = term.expect(original)
        self.assertIn(original.encode(), term.plain(redraw))
        term.send("\x18\x02")
        deadline = time.monotonic() + 2
        while not (self.work / "returned-buffer").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual((self.work / "returned-buffer").read_text(), original)
        self.assertEqual((self.work / "returned-pending").read_text(), "1\n")
        term.send("\x1b")
        term.expect("PTREADY> ")
        term.command("touch cancelled-after-editor")
        self.assertTrue((self.work / "cancelled-after-editor").exists())
        self.assertFalse((self.work / "returned-edit-executed").exists())

    def test_escape_after_resolving_variables_in_editor_still_cancels(self):
        self.fake_editor('print -r -- "TARGET=server01" > "$1"\n')
        term = self.terminal()
        term.command("pt activate")
        term.command("pt guard block")
        term.send('print "$TARGET"; touch resolved-edit-executed\r')
        term.expect("[Esc] abort")
        term.send("\x18e")
        term.expect("pt: all required variables defined.")
        term.send("\x1b")
        term.expect("PTREADY> ")
        self.assertFalse((self.work / "resolved-edit-executed").exists())

    def test_edit_with_real_neovim(self):
        neovim = shutil.which("nvim")
        if not neovim:
            self.skipTest("Neovim is not installed")
        self.env["EDITOR"] = f"'{neovim}' --clean -n -i NONE"
        term = self.terminal()
        term.command("pt activate")
        term.command("pt set ACCOUNT original")
        term.send("pt edit\r")
        term.expect("Trusted Zsh assignments", timeout=10)
        term.send(":%delete _\r:call setline(1, [\"ACCOUNT='from-editor'\", \"PASSWORD=''\"])\r:wq\r")
        term.expect("pt: edited environment", timeout=10)
        term.expect("PTREADY> ")
        output = term.command("pt status")
        self.assertIn(b"ACCOUNT=$'from-editor'", output)
        self.assertIn(b"PASSWORD=''", output)

    def test_edit_shortcut_requires_active_environment(self):
        term = self.terminal()
        term.command("pt guard block")
        term.send('print "$TARGET"\r')
        term.expect("[Esc] abort")
        term.send("\x18e")
        term.expect("pt: no active environment; run pt activate before editing.")

    def test_edit_binding_preserves_existing_editor_shortcut(self):
        term = self.terminal(before="bindkey '^Xe' redisplay\nbindkey '^X^E' beep\n")
        self.assertIn(b"redisplay", term.command("bindkey '^Xe'"))
        self.assertIn(b"beep", term.command("bindkey '^X^E'"))
        self.assertIn(b"pt-edit", term.command("zle -l -L pt-edit"))

    def test_guard_editor_overrides_shortcuts_only_while_warning_is_active(self):
        self.fake_editor('print -r -- "TARGET=edited" > "$1"\n')
        term = self.terminal(after="""
bindkey '^Xe' _expand_word
autoload -Uz edit-command-line
zle -N edit-command-line
bindkey '^X^E' edit-command-line
""")
        term.command("pt activate")
        term.command("pt guard block")
        for shortcut in ("\x18e", "\x18\x05"):
            term.command("pt unset TARGET")
            term.send('print "$TARGET"; touch contextual-executed\r')
            term.expect("[Ctrl-X, E] edit;")
            term.send(shortcut)
            term.expect("pt: all required variables defined.")
            self.assertFalse((self.work / "contextual-executed").exists())
            term.send("\x15")
            self.assertIn(b"_expand_word", term.command("bindkey -M main '^Xe'"))
            self.assertIn(b"edit-command-line", term.command("bindkey -M main '^X^E'"))
        term.command("pt unset TARGET")
        term.send('print "$TARGET"\r')
        term.expect("[Esc] abort")
        term.send("\x15")
        self.assertIn(b"_expand_word", term.command("bindkey -M main '^Xe'"))

    def test_up_recalls_guarded_command_immediately_after_escape(self):
        term = self.terminal(after="""
test_immediate_recall() { print -rn -- "$BUFFER" > immediate-recall; }
zle -N test-immediate-recall test_immediate_recall
bindkey '^X^B' test-immediate-recall
""")
        term.command("pt guard block")
        original = 'print "$TARGET"; touch immediate-executed'
        term.send(original + "\r")
        term.expect("[Esc] abort")
        term.send("\x1b")
        time.sleep(0.6)
        term.send("\x1b[A\x18\x02")
        deadline = time.monotonic() + 2
        while not (self.work / "immediate-recall").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual((self.work / "immediate-recall").read_text(), original)
        self.assertFalse((self.work / "immediate-executed").exists())

    def test_guard_preserves_other_editor_display_and_highlights(self):
        term = self.terminal(after="""
test_other_display() { POSTDISPLAY='existing suffix'; region_highlight=('0 1 fg=blue memo=other'); }
test_capture_display() { print -r -- "$POSTDISPLAY" > display-copy; print -rl -- "${region_highlight[@]}" > highlights-copy; }
zle -N test-other-display test_other_display
zle -N test-capture-display test_capture_display
bindkey '^X^D' test-other-display
bindkey '^X^B' test-capture-display
""")
        term.command("pt guard block")
        term.send('print "$DOMAIN"\x18\x04\r')
        term.expect("[Esc] abort")
        term.send("\x15\x18\x02")
        deadline = time.monotonic() + 2
        while not (self.work / "display-copy").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual((self.work / "display-copy").read_text(), "existing suffix\n")
        highlights = (self.work / "highlights-copy").read_text()
        self.assertIn("memo=other", highlights)
        self.assertNotIn("memo=pt-guard", highlights)

    def test_editing_clears_stale_guard_message_and_keeps_custom_escape(self):
        term = self.terminal(before="bindkey -M emacs '^[' redisplay\n", after="""
test_guard_pending() { print -r -- "$_pt_guard_pending" > pending-state; }
zle -N test-guard-pending test_guard_pending
bindkey '^X^B' test-guard-pending
""")
        term.command("pt guard warn")
        self.assertIn(b'redisplay', term.command("bindkey -M emacs '^['"))
        term.send('print "$TARGET"\r')
        term.expect("[Ctrl-C] abort")
        term.send("\x15\x18\x02")
        deadline = time.monotonic() + 2
        while not (self.work / "pending-state").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual((self.work / "pending-state").read_text(), "0\n")
        term.command("touch edited-command")
        self.assertTrue((self.work / "edited-command").exists())

    def test_warn_requires_second_enter(self):
        term = self.terminal()
        term.command("pt scratch")
        term.command("pt unset TARGET")
        term.command("pt guard warn")
        term.send('print "$TARGET"; touch accepted\r')
        term.expect("[Enter] run anyway;")
        term.expect('print "$TARGET"; touch accepted')
        self.assertFalse((self.work / "accepted").exists())
        term.send("\r")
        term.expect("PTREADY> ")
        self.assertTrue((self.work / "accepted").exists())

    def test_warn_detects_unmanaged_variable_without_configuration(self):
        term = self.terminal(before="PT_GUARD_MODE=warn\n")
        term.send('print -r -- "$DOMAIN"; touch automatic-accepted\r')
        output = term.expect("[Enter] run anyway;")
        term.expect('print -r -- "$DOMAIN"; touch automatic-accepted')
        self.assertIn(b"pt: missing DOMAIN.", term.plain(output))
        self.assertFalse((self.work / "automatic-accepted").exists())
        term.send("\r")
        term.expect("PTREADY> ")
        self.assertTrue((self.work / "automatic-accepted").exists())

    def test_block_and_bypass_preserve_existing_widget(self):
        term = self.terminal(before="""
zle -A accept-line test-original-accept
test_accept() { print -r -- widget-called >> widget-calls; zle test-original-accept; }
zle -N accept-line test_accept
PT_GUARD_MODE=block
""", after="bindkey '^X^J' pt-accept-bypass\n")
        term.command("pt scratch")
        term.command("pt unset TARGET")
        count = len((self.work / "widget-calls").read_text().splitlines())
        term.send('print "$TARGET"; touch accepted\r')
        term.expect("Define variables to run;")
        term.expect('print "$TARGET"; touch accepted')
        term.send("\r")
        term.expect("Define variables to run;")
        term.expect('print "$TARGET"; touch accepted')
        self.assertFalse((self.work / "accepted").exists())
        self.assertEqual(len((self.work / "widget-calls").read_text().splitlines()), count)
        term.send("\x18\x0a")
        term.expect("PTREADY> ")
        self.assertTrue((self.work / "accepted").exists())
        self.assertEqual(len((self.work / "widget-calls").read_text().splitlines()), count + 1)
        term.command("pt guard off")
        term.command('print "$TARGET"; touch off-accepted')
        self.assertTrue((self.work / "off-accepted").exists())

    def test_occupied_preview_key_is_preserved(self):
        term = self.terminal(before="bindkey '^X^P' beginning-of-line\nbindkey -M vicmd '^X^P' beginning-of-line\n")
        output = term.command("bindkey '^X^P'")
        self.assertIn(b"beginning-of-line", output)
        output = term.command("bindkey -M vicmd '^X^P'")
        self.assertIn(b"beginning-of-line", output)

    def test_preview_key_and_guard_startup_defaults(self):
        term = self.terminal(before="bindkey -r '^X^V'\nPT_PREVIEW_KEY='^X^V'\nPT_GUARD_MODE=warn\n")
        output = term.command("bindkey '^X^V'")
        self.assertIn(b"pt-preview", output)
        output = term.command("bindkey -M vicmd '^X^V'")
        self.assertIn(b"pt-preview", output)
        output = term.command("pt guard")
        self.assertIn(b"pt: guard warn", output)

    def check_completion(self, *, init_first):
        (self.work / "localonly.env").write_text("touch sourced\nPASSWORD=never-display\n")
        (self.templates / "templonly.env").write_text("touch sourced\n")
        init = 'autoload -Uz compinit; compinit -D\n'
        capture = """
ZTEST_TARGET=never-display
test_completion_buffer() { print -rn -- "$BUFFER" > completion-copy; zle -M BUFFER_CAPTURED; }
zle -N test-completion-buffer test_completion_buffer
bindkey '^X^B' test-completion-buffer
"""
        term = self.terminal(before=init if init_first else "", after=("" if init_first else init) + capture)
        cases = [
            ("pt act", "pt activate "),
            ("pt edi", "pt edit "),
            ("pt loc", "pt localonly "),
            ("pt activate tem", "pt activate templonly "),
            ("pt activate --t", "pt activate --template "),
            ("pt activate --template tem", "pt activate --template templonly "),
            ("pt loa", "pt load "),
            ("pt load loc", "pt load localonly "),
            ("pt load --t", "pt load --template "),
            ("pt load --template tem", "pt load --template templonly "),
            ("pt load --f", "pt load --force "),
            ("pt load -f loc", "pt load -f localonly "),
            ("pt load -f --template tem", "pt load -f --template templonly "),
            ("pt load --template -f tem", "pt load --template -f templonly "),
            ("pt save --f", "pt save --force "),
            ("pt save --force loc", "pt save --force localonly "),
            ("pt set ZTEST_T", "pt set ZTEST_TARGET "),
            ("pt uns", "pt unset "),
            ("pt unset ZTEST_T", "pt unset ZTEST_TARGET "),
            ("pt ren", "pt rename "),
            ("pt rename loc", "pt rename localonly "),
            ("pt guard bl", "pt guard block "),
        ]
        for prefix, expected in cases:
            term.send(prefix + "\t\x18\x02")
            output = term.expect("BUFFER_CAPTURED")
            self.assertNotIn(b"never-display", output)
            self.assertEqual((self.work / "completion-copy").read_text(), expected)
            term.send("\x15")
        self.assertFalse((self.work / "sourced").exists())

    def test_completion_with_compinit_before_plugin(self):
        self.check_completion(init_first=True)

    def test_completion_with_compinit_after_plugin(self):
        self.check_completion(init_first=False)

    def test_prompt_tracks_name(self):
        term = self.terminal(after="""
setopt prompt_subst
PROMPT='${PT_ENV_NAME:+[$PT_ENV_NAME] }PTREADY> '
""")
        for command, name in [("pt first", "first"), ("pt rename renamed", "renamed"), ("pt second", "second")]:
            output = term.command(command)
            self.assertIn(f"[{name}]".encode(), output)
        output = term.command("pt deactivate")
        self.assertNotIn(b"[second]", output)

    def test_vi_guard_keeps_escape_mode_switch_and_cancellation_hint(self):
        term = self.terminal(before="bindkey -v\n", after='''
test_vi_state() { print -rl -- "$KEYMAP" "$BUFFER" > vi-state; }
zle -N test-vi-state test_vi_state
bindkey -M viins '^X^B' test-vi-state
bindkey -M vicmd '^X^B' test-vi-state
''')
        term.command("pt activate")
        term.command("pt guard block")
        self.assertIn(b"vi-cmd-mode", term.command("bindkey -M viins '^['"))
        original = 'print "$TARGET"; touch vi-executed'
        term.send(original + "\r")
        output = term.expect("[Ctrl-C] abort")
        self.assertNotIn(b"[Esc] abort", output)
        term.send("\x1b")
        time.sleep(0.6)
        term.send("\x18\x02")
        deadline = time.monotonic() + 2
        while not (self.work / "vi-state").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual((self.work / "vi-state").read_text(), "vicmd\n" + original + "\n")
        term.send("\r")
        term.expect("[Ctrl-C] abort")
        self.assertFalse((self.work / "vi-executed").exists())
        term.send("\x03")
        term.expect("PTREADY> ")
        term.command("touch vi-cancelled")
        self.assertTrue((self.work / "vi-cancelled").exists())
        self.assertFalse((self.work / "vi-executed").exists())

    def test_vi_guard_editor_and_preview_preserve_insert_mode(self):
        self.fake_editor('print -r -- "TARGET=vi-value" > "$1"\n')
        term = self.terminal(before="bindkey -v\n")
        term.command("pt activate")
        term.command("pt guard block")
        original = 'print "$TARGET" > vi-result'
        term.send(original + "\r")
        term.expect("[Ctrl-C] abort")
        term.send("\x18e")
        output = term.expect("[Ctrl-C] abort")
        self.assertIn(b"all required variables defined", output)
        self.assertNotIn(b"[Esc] abort", output)
        self.assertFalse((self.work / "vi-result").exists())
        term.send("\x18\x10")
        term.expect('pt preview: print "vi-value" > vi-result')
        term.send("\x18\x10\r")
        term.expect("PTREADY> ")
        self.assertEqual((self.work / "vi-result").read_text(), "vi-value\n")

    def test_vi_mode_selected_after_loading_warns_on_both_enter_bindings(self):
        term = self.terminal()
        term.command("bindkey -v")
        term.command("pt guard warn")
        for mode in ("insert", "command"):
            with self.subTest(mode=mode):
                original = f'print "$TARGET"; touch vi-warn-{mode}'
                term.send(original)
                if mode == "command":
                    term.send("\x1b")
                    time.sleep(0.6)
                term.send("\r")
                output = term.expect("[Ctrl-C] abort")
                self.assertIn(b"[Enter] run anyway", output)
                self.assertFalse((self.work / f"vi-warn-{mode}").exists())
                term.send("\r")
                term.expect("PTREADY> ")
                self.assertTrue((self.work / f"vi-warn-{mode}").exists())

    def test_quickstart_loads_completion_guard_and_short_prompt(self):
        term = Terminal(self, '''
bindkey -e
PROMPT='PTREADY> '
source "${PT_PLUGIN:h}/examples/quickstart.zsh"
''')
        output = term.command('source "${PT_PLUGIN:h}/examples/quickstart.zsh"')
        self.assertIn(b"[pt]", output)
        output = term.command('print -r -- "$_pt_active $PT_GUARD_MODE ${+functions[compdef]}"')
        self.assertIn(b"1 warn 1", output)
        term.command("pt rename demo")
        term.command("pt set TARGET synthetic")
        term.command('source "${PT_PLUGIN:h}/examples/quickstart.zsh"')
        output = term.command('print -r -- "$PROMPT"')
        self.assertEqual(output.count(b"${PT_ENV_NAME:+[pt] }"), 1)
        output = term.command('print -r -- "$PT_ENV_NAME $TARGET"')
        self.assertIn(b"demo synthetic", output)
        term.command("pt deactivate")
        output = term.command('print -r -- DEACTIVATED')
        self.assertNotIn(b"[pt]", output)


class IntegrationTests(IsolatedTest):
    terminal = TerminalTests.terminal

    def atuin_setup(self):
        if not shutil.which("atuin"):
            self.skipTest("Atuin is not installed")
        config = self.config / "atuin"
        config.mkdir()
        (config / "config.toml").write_text(
            "auto_sync = false\nupdate_check = false\n[daemon]\nenabled = false\n"
        )
        return 'source <(atuin init zsh)\n'

    def test_sheldon_local_plugin_loading(self):
        if not shutil.which("sheldon"):
            self.skipTest("Sheldon is not installed")
        config = self.config / "sheldon"
        config.mkdir()
        (config / "plugins.toml").write_text(
            f'shell = "zsh"\n[plugins.pt]\nlocal = "{ROOT}"\nuse = ["pt.plugin.zsh"]\n'
        )
        result = subprocess.run(
            ["sheldon", "--config-dir", str(config), "--data-dir", str(self.home / "sheldon-data"), "source"],
            cwd=self.work, env=self.env, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        script = self.work / "sheldon-source.zsh"
        script.write_text(result.stdout)
        self.run_zsh("""
source ./sheldon-source.zsh || fail sheldon
pt scratch || fail activate
pt set TARGET synthetic || fail set
pt deactivate || fail deactivate
(( ! ${+TARGET} )) || fail restoration
""", load=False)

    def test_sheldon_interactive_stack_with_late_atuin_and_guard(self):
        for executable in ("sheldon", "atuin"):
            if not shutil.which(executable):
                self.skipTest(f"{executable} is not installed")
        for variable in ("PT_TEST_P10K", "PT_TEST_AUTOSUGGEST", "PT_TEST_SYNTAX"):
            if not os.environ.get(variable):
                self.skipTest(f"set {variable} to the installed plugin entrypoint")
        theme = Path(os.environ["PT_TEST_P10K"])
        theme_copy = self.home / "theme"
        shutil.copytree(theme.resolve().parent, theme_copy,
                        ignore=shutil.ignore_patterns(".git", "*.zwc"))
        plugins = [("powerlevel10k", theme_copy / theme.name),
                   ("autosuggestions", Path(os.environ["PT_TEST_AUTOSUGGEST"])),
                   ("syntax-highlighting", Path(os.environ["PT_TEST_SYNTAX"])),
                   ("pt", ROOT / "pt.plugin.zsh")]
        config = self.config / "sheldon"
        config.mkdir()
        text = 'shell = "zsh"\n'
        for name, entrypoint in plugins:
            text += (f'\n[plugins.{name}]\nlocal = {json.dumps(str(entrypoint.parent))}\n'
                     f'use = [{json.dumps(entrypoint.name)}]\n')
        (config / "plugins.toml").write_text(text)
        result = subprocess.run(
            ["sheldon", "--config-dir", str(config), "--data-dir", str(self.home / "sheldon-data"), "source"],
            cwd=self.work, env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        script = self.home / "sheldon-source.zsh"
        script.write_text(result.stdout)
        self.fake_editor('print -r -- "TARGET=edited-sheldon" > "$1"\n')
        term = Terminal(self, '''
bindkey -e
PT_GUARD_MODE=off
POWERLEVEL9K_DISABLE_CONFIGURATION_WIZARD=true
POWERLEVEL9K_DISABLE_GITSTATUS=true
POWERLEVEL9K_INSTANT_PROMPT=off
POWERLEVEL9K_LEFT_PROMPT_ELEMENTS=(dir newline marker)
POWERLEVEL9K_RIGHT_PROMPT_ELEMENTS=()
prompt_marker() { p10k segment -t 'PTREADY> '; }
source "$HOME/sheldon-source.zsh"
''' + self.atuin_setup() + '''
autoload -Uz compinit
compinit -D
source "${PT_PLUGIN:h}/examples/powerlevel10k.zsh"
POWERLEVEL9K_LEFT_PROMPT_ELEMENTS+=(pt)
p10k reload
pt guard warn >/dev/null
test_sheldon_buffer() { print -rn -- "$BUFFER" > sheldon-completion; zle -M CAPTURED; }
zle -N test-sheldon-buffer test_sheldon_buffer
bindkey '^X^B' test-sheldon-buffer
''')
        output = term.command('print -r -- "$_pt_loaded $_pt_active $PT_GUARD_MODE"')
        self.assertIn(b"1 0 warn", output)
        term.command("pt activate")
        term.send('print "$TARGET" > sheldon-executed\r')
        term.expect("[Ctrl-X, E] edit;")
        self.assertFalse((self.work / "sheldon-executed").exists())
        term.send("\x18e")
        term.expect("all required variables defined.")
        self.assertFalse((self.work / "sheldon-executed").exists())
        term.send("\x18\x10")
        term.expect('pt preview: print "edited-sheldon" > sheldon-executed')
        term.send("\x18\x10\r")
        term.expect("PTREADY> ")
        deadline = time.monotonic() + 3
        while not (self.work / "sheldon-executed").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual((self.work / "sheldon-executed").read_text(), "edited-sheldon\n")
        (self.work / "overlay.env").write_text("TARGET=merged-sheldon\n")
        term.command("pt load -f overlay")
        output = term.command('print -r -- "$TARGET"')
        self.assertIn(b"merged-sheldon", output)
        term.send("pt loa\t\x18\x02")
        term.expect("CAPTURED")
        self.assertEqual((self.work / "sheldon-completion").read_text(), "pt load ")
        term.send("\x15")
        term.command("pt unset TARGET")
        term.send('print "$TARGET"; touch sheldon-cancelled\r')
        term.expect("[Esc] abort")
        term.send("\x1b")
        time.sleep(0.6)
        term.command("pt deactivate")
        output = term.command('print -r -- "$_pt_active ${+TARGET}"')
        self.assertIn(b"0 0", output)
        self.assertFalse((self.work / "sheldon-cancelled").exists())

    def test_atuin_guard_and_preview_history(self):
        term = self.terminal(before=self.atuin_setup())
        term.command("pt scratch")
        term.send("pt set PASSWORD\r")
        term.expect("Ctrl-C to cancel): ")
        term.send("synthetic-hidden-marker\r")
        term.expect("PTREADY> ")
        term.send('print -r -- "$PASSWORD" >/dev/null\x18\x10')
        term.expect("synthetic-hidden-marker")
        term.send("\r")
        term.expect("PTREADY> ")
        term.command("pt unset TARGET")
        term.command("pt guard block")
        term.send('print "$TARGET"; touch accepted\r')
        term.expect("Define variables to run;")
        self.assertFalse((self.work / "accepted").exists())
        term.send("\x03")
        term.expect("PTREADY> ")
        term.command("pt deactivate")
        self.env["ATUIN_SESSION"] = "0" * 32
        result = subprocess.run(
            ["atuin", "history", "list", "--format", "{command}"],
            env=self.env, cwd=self.work, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('$PASSWORD', result.stdout)
        self.assertNotIn("synthetic-hidden-marker", result.stdout)
        self.assertNotIn("touch accepted", result.stdout)

    def test_atuin_records_guard_cancellation_without_execution_or_expansion(self):
        term = self.terminal(before=self.atuin_setup(), after="""
test_atuin_native_recall() { print -rn -- "$BUFFER" > atuin-native-recall; }
zle -N test-atuin-native-recall test_atuin_native_recall
bindkey '^X^B' test-atuin-native-recall
bindkey '^[[A' up-line-or-history
""")
        term.command("pt activate")
        term.command("pt set PASSWORD synthetic-private-value")
        term.command("pt guard block")
        original = 'print "$TARGET" "$PASSWORD"; touch cancelled-atuin-executed'
        term.send(original + "\x18\x10")
        term.expect("synthetic-private-value")
        term.send("\r")
        term.expect("[Esc] abort")
        term.expect(original)
        term.send("\x1b")
        term.expect("PTREADY> ")
        term.send("\x1b[A\x18\x02")
        deadline = time.monotonic() + 2
        while not (self.work / "atuin-native-recall").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual((self.work / "atuin-native-recall").read_text(), original)
        term.send("\x15")
        term.command("pt set TARGET server01")
        self.assertFalse((self.work / "cancelled-atuin-executed").exists())
        self.env["ATUIN_SESSION"] = "0" * 32
        result = subprocess.run(
            ["atuin", "history", "list", "--format", "{exit}:{command}"],
            env=self.env, cwd=self.work, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count(original), 1)
        self.assertIn("130:" + original, result.stdout)
        self.assertNotIn('print "server01" "synthetic-private-value"', result.stdout)
        self.assertNotIn("pt: missing", result.stdout)

    def test_atuin_cancellation_respects_history_filters(self):
        setup = self.atuin_setup()
        (self.config / "atuin" / "config.toml").write_text(
            'auto_sync = false\nupdate_check = false\nhistory_filter = ["cancel-filter-marker"]\n[daemon]\nenabled = false\n'
        )
        term = self.terminal(before=setup)
        term.command("pt guard block")
        term.send('print "$TARGET"; touch cancel-filter-marker\r')
        term.expect("[Esc] abort")
        term.send("\x1b")
        time.sleep(0.6)
        term.command("touch filter-sync")
        self.assertFalse((self.work / "cancel-filter-marker").exists())
        self.env["ATUIN_SESSION"] = "0" * 32
        result = subprocess.run(
            ["atuin", "history", "list", "--format", "{command}"],
            env=self.env, cwd=self.work, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("cancel-filter-marker", result.stdout)

    def test_guard_editor_with_autosuggestions_and_syntax_highlighting(self):
        for variable in ("PT_TEST_AUTOSUGGEST", "PT_TEST_SYNTAX"):
            source = os.environ.get(variable)
            if not source:
                self.skipTest(f"set {variable} to the installed plugin entrypoint")
            self.env[variable] = source
        self.fake_editor('print -r -- "TARGET=edited" > "$1"\n')
        term = self.terminal(before='source "$PT_TEST_AUTOSUGGEST"\nsource "$PT_TEST_SYNTAX"\n', after="""
bindkey '^Xe' _expand_word
autoload -Uz edit-command-line
zle -N edit-command-line
bindkey '^X^E' edit-command-line
test_suggest_buffer() { print -rn -- "$BUFFER" > suggest-buffer; }
zle -N test-suggest-buffer test_suggest_buffer
bindkey '^X^B' test-suggest-buffer
""")
        term.command("pt activate")
        term.command("pt guard block")
        original = 'print "$TARGET"; touch suggest-executed'
        term.send(original + "\r")
        output = term.expect("[Esc] abort")
        self.assertIn(b"pt: missing TARGET.", output)
        self.assertNotIn(b"^[[33m", output)
        # Moving to end-of-line must never accept the warning as a suggestion.
        term.send("\x05\x18\x02")
        deadline = time.monotonic() + 2
        while not (self.work / "suggest-buffer").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual((self.work / "suggest-buffer").read_text(), original)
        term.send("\x18\x05")
        term.expect("pt: all required variables defined.")
        self.assertFalse((self.work / "suggest-executed").exists())
        term.send("\x15")
        self.assertIn(b"_expand_word", term.command("bindkey -M main '^Xe'"))
        self.assertIn(b"edit-command-line", term.command("bindkey -M main '^X^E'"))

    def test_powerlevel10k_warning_visible_on_screen(self):
        if os.environ.get("PT_TEST_TMUX") != "1":
            self.skipTest("set PT_TEST_TMUX=1 to run the private tmux screen test")
        if not shutil.which("tmux"):
            self.skipTest("tmux is not installed")
        theme = os.environ.get("PT_TEST_P10K")
        if not theme:
            self.skipTest("set PT_TEST_P10K to the installed theme")
        theme_copy = self.home / "theme"
        shutil.copytree(Path(theme).resolve().parent, theme_copy,
                        ignore=shutil.ignore_patterns(".git", "*.zwc"))
        (self.home / ".zshrc").write_text("""
bindkey -e
POWERLEVEL9K_DISABLE_CONFIGURATION_WIZARD=true
POWERLEVEL9K_DISABLE_GITSTATUS=true
POWERLEVEL9K_INSTANT_PROMPT=off
POWERLEVEL9K_LEFT_PROMPT_ELEMENTS=(dir newline marker)
POWERLEVEL9K_RIGHT_PROMPT_ELEMENTS=()
POWERLEVEL9K_COLOR_SCHEME=dark
prompt_marker() { p10k segment -t 'PTREADY> '; }
source "$HOME/theme/powerlevel10k.zsh-theme"
source "${PT_PLUGIN:h}/examples/quickstart.zsh"
HISTFILE=$HOME/test-history
""")
        prefix = ["tmux", "-S", str(self.home / "tmux.sock"), "-f", "/dev/null"]
        self.addCleanup(lambda: subprocess.run(prefix + ["kill-server"], env=self.env, capture_output=True))

        def tmux(*arguments):
            result = subprocess.run(prefix + list(arguments), env=self.env, cwd=self.work,
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout

        def screen():
            return tmux("capture-pane", "-p", "-J", "-t", "pt-screen")

        def wait_for(text):
            deadline = time.monotonic() + 10
            while text not in screen():
                if time.monotonic() > deadline:
                    self.fail(f"screen did not show {text!r}: {screen()!r}")
                time.sleep(0.05)

        def send(text):
            tmux("send-keys", "-t", "pt-screen", "-l", text)
            tmux("send-keys", "-t", "pt-screen", "Enter")

        tmux("new-session", "-d", "-s", "pt-screen", "-x", "120", "-y", "30", f"exec {ZSH} -i")
        wait_for("PTREADY>")
        send("pt activate; pt guard warn; print -r -- PT''SYNC")
        wait_for("\nPTSYNC\n")
        time.sleep(0.3)
        original = 'print "$TARGET" "$PASSWORD" "$DOMAIN"; touch screen-executed'
        send(original)
        time.sleep(0.8)  # Check the settled screen after all prompt repainting.
        visible = screen()
        self.assertIn("pt: missing TARGET, PASSWORD, DOMAIN.", visible)
        self.assertRegex(visible, r"PTREADY>[^\n]*" + re.escape(original))
        self.assertRegex(visible, r"PTREADY>[^\n]*\bpt\b[^\n]*" + re.escape(original))
        colored = tmux("capture-pane", "-p", "-J", "-e", "-t", "pt-screen")
        # Dark themes otherwise default to black text on this segment's black background.
        self.assertRegex(colored, r"\x1b\[(?:37|38;5;7)m(?:\x1b\[40m)?[^\x1b\n]*pt\b")
        self.assertEqual(visible.count(original), 1, visible)
        self.assertLess(visible.index(original), visible.index("pt: missing"))
        self.assertIn("\nPTSYNC\n", visible)
        self.assertFalse((self.work / "screen-executed").exists())
        # Wrapped commands keep their warning below, even with the cursor at the start.
        tmux("send-keys", "-t", "pt-screen", "Escape")
        time.sleep(0.6)
        send("print -r -- WRAPPEDSYNC")
        wait_for("\nWRAPPEDSYNC\n")
        time.sleep(0.3)
        wrapped = original + "; : " + "synthetic-padding-" * 12
        tmux("send-keys", "-t", "pt-screen", "-l", wrapped)
        tmux("send-keys", "-t", "pt-screen", "C-a", "Enter")
        time.sleep(0.8)
        visible = screen()
        self.assertEqual(visible.count(wrapped), 1, visible)
        self.assertIn("\nWRAPPEDSYNC\n", visible)
        self.assertIn("pt: missing TARGET, PASSWORD, DOMAIN.", visible)
        self.assertLess(visible.index(wrapped), visible.index("pt: missing"))
        self.assertFalse((self.work / "screen-executed").exists())

    def test_powerlevel10k_and_atuin_together(self):
        theme = os.environ.get("PT_TEST_P10K")
        if not theme:
            self.skipTest("set PT_TEST_P10K to an installed powerlevel10k.zsh-theme")
        self.assertTrue(Path(theme).is_file())
        # The theme compiles its own source files; keep those writes isolated too.
        theme_copy = self.home / "powerlevel10k"
        shutil.copytree(Path(theme).resolve().parent, theme_copy,
                        ignore=shutil.ignore_patterns(".git", "*.zwc"))
        self.env["PT_TEST_P10K"] = str(theme_copy / Path(theme).name)
        self.fake_editor('print -r -- "TARGET=edited-integration" > "$1"\n')
        before = self.atuin_setup() + """
POWERLEVEL9K_DISABLE_CONFIGURATION_WIZARD=true
POWERLEVEL9K_DISABLE_GITSTATUS=true
POWERLEVEL9K_INSTANT_PROMPT=off
POWERLEVEL9K_LEFT_PROMPT_ELEMENTS=(pt marker)
POWERLEVEL9K_RIGHT_PROMPT_ELEMENTS=()
prompt_pt() { [[ -n ${PT_ENV_NAME-} ]] && p10k segment -f 39 -t "[$PT_ENV_NAME]"; }
prompt_marker() { p10k segment -t 'PTREADY> '; }
source "$PT_TEST_P10K"
"""
        term = self.terminal(before=before)
        for command, name in [("pt first", "first"), ("pt rename renamed", "renamed"), ("pt second", "second")]:
            self.assertIn(f"[{name}]".encode(), term.command(command))
        term.command("pt set TARGET synthetic-preview")
        term.send('print -r -- "$TARGET"\x18\x10')
        term.expect("synthetic-preview")
        # Queue editing keys after the widget rather than signalling it mid-call.
        term.send("\x18\x10\x15")
        term.command("pt unset TARGET")
        term.command("pt guard block")
        term.send('print "$TARGET"; touch accepted\r')
        term.expect("Define variables to run;")
        self.assertFalse((self.work / "accepted").exists())
        term.send("\x18e")
        term.expect("pt: all required variables defined.")
        self.assertFalse((self.work / "accepted").exists())
        term.send("\x15")
        term.command("pt unset TARGET")
        term.send('print "$TARGET"; touch accepted\r')
        term.expect("Define variables to run;")
        term.send("\x1b")
        time.sleep(0.6)
        output = term.command("pt deactivate")
        # Cancellation may redraw the old prompt before this command executes.
        current_prompt = output.split(f"PTSYNC{term.sequence}\r\n".encode())[-1]
        self.assertNotIn(b"[second]", current_prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)

typeset -g PT_GUARD_MODE=${PT_GUARD_MODE:-off}
typeset -g PT_PREVIEW_KEY=${PT_PREVIEW_KEY-'^X^P'}
typeset -g _pt_warn_buffer=''
typeset -g _pt_guard_keymap=''
typeset -g _pt_guard_abort_hint=''
typeset -gi _pt_guard_installed=0 _pt_preview_open=0 _pt_guard_pending=0

_pt_guard_cancel_key() {
  local _pt_cancel_map=${_pt_guard_keymap:-$KEYMAP}
  if [[ $(bindkey -M "$_pt_cancel_map" '^[') == *' pt-guard-cancel' ]]; then
    _pt_guard_abort_hint='[Esc] abort'
  else
    _pt_guard_abort_hint='[Ctrl-C] abort'
  fi
}

_pt_clear_guard_context() {
  if [[ -n $_pt_guard_keymap ]]; then
    [[ $KEYMAP != _pt_guard ]] || zle -K "$_pt_guard_keymap"
    _pt_guard_keymap=''
  fi
}

_pt_show_guard_message() {
  _pt_clear_guard_context
  # Override editor shortcuts only while the guard is waiting for input.
  if (( _pt_active )); then
    _pt_guard_keymap=$KEYMAP
    bindkey -N _pt_guard "$KEYMAP"
    bindkey -M _pt_guard '^Xe' pt-edit
    bindkey -M _pt_guard '^X^E' pt-edit
    zle -K _pt_guard
  fi
  # Native messages stay below the command and cannot become autosuggestion text.
  zle -M "$1"
  return 0
}

_pt_guard_warning() {
  local _pt_warning_message="pt: missing ${(j:, :)_pt_guard_missing}."
  _pt_warn_buffer=$BUFFER
  _pt_guard_pending=1
  if [[ $PT_GUARD_MODE == warn ]]; then
    _pt_warning_message+=' [Enter] run anyway;'
  else
    _pt_warning_message+=' Define variables to run;'
  fi
  (( ${#_pt_scan_unchecked} == 0 )) || _pt_warning_message+=' Some syntax is unchecked.'
  (( ! _pt_active )) || _pt_warning_message+=' [Ctrl-X, E] edit;'
  _pt_guard_cancel_key
  _pt_warning_message+=" $_pt_guard_abort_hint"
  _pt_show_guard_message "$_pt_warning_message"
}

_pt_clear_stale_guard() {
  if (( _pt_guard_pending )) && [[ $BUFFER != $_pt_warn_buffer ]]; then
    _pt_guard_pending=0
    _pt_warn_buffer=''
    _pt_clear_guard_context
    zle -M ''
  fi
}

_pt_edit_widget() {
  # Keep caller prompt options and preserve the command for explicit acceptance.
  if (( ! _pt_active )); then
    zle -M 'pt: no active environment; run pt activate before editing.'
    return 1
  fi
  local _pt_widget_buffer=$BUFFER
  local -i _pt_widget_cursor=$CURSOR _pt_widget_rc=0 _pt_widget_guarded=$_pt_guard_pending
  local -a _pt_widget_missing
  if (( _pt_guard_pending )); then
    _pt_guard_check "$BUFFER"
    _pt_widget_missing=( "${_pt_guard_missing[@]}" )
  fi
  _pt_clear_guard_context
  _pt_guard_pending=0 _pt_warn_buffer=''
  zle -M ''
  zle -I
  _pt_edit "${_pt_widget_missing[@]}" </dev/tty || _pt_widget_rc=$?
  BUFFER=$_pt_widget_buffer
  CURSOR=$_pt_widget_cursor
  zle reset-prompt
  _pt_guard_check "$BUFFER"
  if (( _pt_widget_guarded )); then
    if (( ${#_pt_guard_missing} )); then
      _pt_guard_warning
    else
      _pt_guard_pending=1
      _pt_warn_buffer=$BUFFER
      _pt_guard_cancel_key
      _pt_show_guard_message "pt: all required variables defined. [Enter] run; $_pt_guard_abort_hint"
    fi
  elif (( _pt_widget_rc )); then
    zle -M 'pt: edit not applied.'
  else
    zle -M 'pt: edit complete. [Enter] run'
  fi
}

_pt_remember_guarded_command() {
  emulate -L zsh
  # Add literal buffer text to history without invoking execution hooks.
  builtin print -sr -- "$1" || return 1
  if [[ -n ${ATUIN_SESSION-} ]] && (( ${+commands[atuin]} && ${preexec_functions[(Ie)_atuin_preexec]} )); then
    local _pt_history_id
    # Match Atuin's hook recording so its history/privacy filters still apply.
    _pt_history_id=$(ATUIN_SHELL=zsh command atuin history start --hook -- "$1" 2>/dev/null) || return 0
    if [[ -n $_pt_history_id ]]; then
      command atuin history end --hook --exit 130 --duration 0 -- "$_pt_history_id" >/dev/null 2>&1 || true
    fi
  fi
  return 0
}

_pt_guard_cancel() {
  if (( _pt_preview_open )) && [[ $LASTWIDGET == pt-preview ]]; then
    _pt_preview_open=0
    zle -M ''
  elif (( _pt_guard_pending )); then
    _pt_remember_guarded_command "$BUFFER" || { zle -M 'pt: could not add the command to history; buffer kept.'; return 1; }
    BUFFER=''
    CURSOR=0
    _pt_guard_pending=0
    _pt_warn_buffer=''
    _pt_clear_guard_context
    zle -M ''
    # A new editing session sees the command just added to native history.
    zle .send-break
  else
    zle undefined-key
  fi
}

_pt_preview_widget() {
  # Preserve prompt options while ZLE renders messages and calls other widgets.
  if [[ $LASTWIDGET == pt-preview ]] && (( _pt_preview_open )); then
    _pt_preview_open=0
    zle -M ''
    return 0
  fi
  _pt_preview_open=1
  _pt_render_preview "$BUFFER"
  local _pt_preview_message="pt preview: $_pt_preview_command"
  (( ${#_pt_scan_unchecked} )) && _pt_preview_message+=$'\n'"Unchecked: ${(j:; :)_pt_scan_unchecked}"
  zle -M "$_pt_preview_message"
}

_pt_accept_line() {
  _pt_clear_guard_context
  case $PT_GUARD_MODE in
    off) _pt_guard_pending=0; zle _pt_original_accept_line; return ;;
    warn|block) ;;
    *) zle -M 'pt: invalid PT_GUARD_MODE; use off, warn, or block.'; return ;;
  esac
  _pt_guard_check "$BUFFER"
  if (( ${#_pt_guard_missing} )); then
    if [[ $PT_GUARD_MODE == warn && $BUFFER == $_pt_warn_buffer && $LASTWIDGET == accept-line ]]; then
      _pt_warn_buffer=''
      _pt_guard_pending=0
      zle _pt_original_accept_line
      return
    fi
    _pt_guard_warning
    return 0
  fi
  _pt_warn_buffer=''
  _pt_guard_pending=0
  if (( ${#_pt_scan_unchecked} )); then
    zle -M "pt: unchecked syntax: ${(j:; :)_pt_scan_unchecked}"
  fi
  zle _pt_original_accept_line
}

_pt_accept_bypass() {
  _pt_clear_guard_context
  _pt_warn_buffer=''
  _pt_guard_pending=0
  zle _pt_original_accept_line
}

_pt_install_guard() {
  [[ -o interactive ]] || return 0
  (( _pt_guard_installed )) && return 0
  zle -A accept-line _pt_original_accept_line || return
  zle -N accept-line _pt_accept_line
  zle -N pt-accept-bypass _pt_accept_bypass
  autoload -Uz add-zle-hook-widget
  add-zle-hook-widget line-pre-redraw _pt_clear_stale_guard
  _pt_guard_installed=1
}

_pt_guard_command() {
  emulate -L zsh
  if (( $# == 0 )); then
    _pt_output heading "pt: guard $PT_GUARD_MODE"
    return 0
  fi
  (( $# == 1 )) && [[ $1 == (off|warn|block) ]] || { _pt_error 'usage: pt guard [off|warn|block]'; return 2; }
  PT_GUARD_MODE=$1
  _pt_clear_guard_context
  _pt_warn_buffer=''
  _pt_guard_pending=0
  [[ $1 == off ]] || _pt_install_guard
}

_pt_editor_install() {
  emulate -L zsh
  [[ -o interactive ]] || return 0
  zle -N pt-preview _pt_preview_widget
  zle -N pt-edit _pt_edit_widget
  zle -N pt-guard-cancel _pt_guard_cancel
  # Dismiss previews with Escape even when the guard is off; preserve vi/custom keys.
  if [[ $(bindkey -M emacs '^[') == *' undefined-key' ]]; then
    bindkey -M emacs '^[' pt-guard-cancel
  fi
  local _pt_editor_map _pt_editor_binding _pt_editor_edit_key
  for _pt_editor_map in emacs viins; do
    for _pt_editor_edit_key in '^Xe' '^X^E'; do
      _pt_editor_binding=$(bindkey -M "$_pt_editor_map" "$_pt_editor_edit_key" 2>/dev/null)
      if [[ $_pt_editor_binding == *' undefined-key' ]]; then
        bindkey -M "$_pt_editor_map" "$_pt_editor_edit_key" pt-edit
      fi
    done
  done
  if [[ -n $PT_PREVIEW_KEY ]]; then
    for _pt_editor_map in emacs viins vicmd; do
      _pt_editor_binding=$(bindkey -M "$_pt_editor_map" "$PT_PREVIEW_KEY" 2>/dev/null)
      if [[ $_pt_editor_binding == *' undefined-key' ]]; then
        bindkey -M "$_pt_editor_map" "$PT_PREVIEW_KEY" pt-preview
      else
        _pt_error "preview binding in $_pt_editor_map is occupied; bind pt-preview manually."
      fi
    done
  fi
  case $PT_GUARD_MODE in
    off) ;;
    warn|block) _pt_install_guard ;;
    *) _pt_error 'invalid PT_GUARD_MODE; using off.'; PT_GUARD_MODE=off ;;
  esac
}

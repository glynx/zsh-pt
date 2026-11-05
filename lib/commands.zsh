_pt_help() {
  print -r -- 'Usage: pt NAME | pt COMMAND
  activate [NAME]            Activate by name; omit NAME for a fresh scratch environment
  activate --template NAME   Activate a home template
  load [-f] [--template] NAME  Merge values; confirm replacements (-f skips prompts)
  set NAME [VALUE]            Export a literal value; omit VALUE for visible input
  unset NAME                 Unset a variable until deactivation
  edit                       Edit defined environment variables in VISUAL or EDITOR
  status                     Show state and managed values in cleartext
  rename NAME                Rename the active environment in memory
  save [--force] [NAME]        Save ./NAME.env (0600); confirm overwrites
  list                       List local environments and home templates
  deactivate                 Restore managed scalars; discard unsaved changes
  guard [off|warn|block]      Show or change Enter validation
  help                       Show this help
Only trusted files are sourced. pentest.env is never written.'
}

_pt_require_active() {
  (( _pt_active )) || { _pt_error 'no active environment; use pt NAME first.'; return 1; }
}

_pt_set() {
  emulate -L zsh
  _pt_require_active || return
  (( $# == 1 || $# == 2 )) || { _pt_error 'usage: pt set NAME [VALUE]'; return 2; }
  local _pt_set_name=$1 _pt_set_value
  _pt_valid_parameter "$_pt_set_name" || { _pt_error 'invalid or reserved parameter name.'; return 2; }
  _pt_capture "$_pt_set_name" || { _pt_error "cannot manage $_pt_set_name: unsupported parameter attributes."; return 1; }
  if [[ ${_pt_base_kind[$_pt_set_name]-} == unsupported ]]; then
    _pt_error "cannot manage $_pt_set_name: its original attributes are unsupported."
    return 1
  fi
  if (( $# == 2 )); then
    _pt_set_value=$2
  else
    [[ -t 0 ]] || { _pt_error 'interactive input requires a terminal; pass VALUE explicitly.'; return 1; }
    if ! IFS= read -r "_pt_set_value?pt: $_pt_set_name (Ctrl-C to cancel): "; then
      print -u2
      _pt_error 'input cancelled.'
      return 1
    fi
  fi
  # Remove numeric/case attributes before assignment to keep input literal.
  builtin unset -- "$_pt_set_name" || return 1
  builtin typeset -gx -- "$_pt_set_name=$_pt_set_value" || return 1
  _pt_managed[$_pt_set_name]=1
  _pt_dirty=1
}

_pt_unset() {
  emulate -L zsh
  _pt_require_active || return
  (( $# == 1 )) || { _pt_error 'usage: pt unset NAME'; return 2; }
  local _pt_unset_name=$1
  _pt_valid_parameter "$_pt_unset_name" || { _pt_error 'invalid or reserved parameter name.'; return 2; }
  _pt_capture "$_pt_unset_name" || { _pt_error "cannot manage $_pt_unset_name: unsupported parameter attributes."; return 1; }
  if [[ ${_pt_base_kind[$_pt_unset_name]-} == unsupported ]]; then
    _pt_error "cannot manage $_pt_unset_name: its original attributes are unsupported."
    return 1
  fi
  builtin unset -- "$_pt_unset_name" || return 1
  _pt_managed[$_pt_unset_name]=1
  _pt_dirty=1
}

_pt_status() {
  emulate -L zsh
  if (( ! _pt_active )); then
    _pt_output muted 'pt: inactive'
    return 0
  fi
  local _pt_status_header="Environment: $PT_ENV_NAME"$'\n'"Source: $_pt_source"
  if [[ $_pt_source != '<empty>' ]]; then
    if (( _pt_dirty )); then
      _pt_status_header+=$'\nDirty: yes'
    else
      _pt_status_header+=$'\nDirty: no'
    fi
  fi
  _pt_output status "$_pt_status_header"
  (( ${#_pt_managed} )) && print
  local _pt_status_name _pt_status_value
  for _pt_status_name in ${(ok)_pt_managed}; do
    if (( ! ${+parameters[$_pt_status_name]} )); then
      print -r -- "$_pt_status_name=<unset>"
    else
      _pt_capture "$_pt_status_name" || { print -r -- "$_pt_status_name=<unsupported>"; continue; }
      _pt_status_value=${(P)_pt_status_name}
      if [[ -z $_pt_status_value ]]; then
        print -r -- "$_pt_status_name=''"
      else
        print -r -- "$_pt_status_name=${(qqqq)_pt_status_value}"
      fi
    fi
  done
}

_pt_rename() {
  emulate -L zsh
  _pt_require_active || return
  (( $# == 1 )) && _pt_valid_name "$1" || { _pt_error 'usage: pt rename NAME (pentest is reserved)'; return 2; }
  if [[ $PT_ENV_NAME != $1 ]]; then
    PT_ENV_NAME=$1
    _pt_dirty=1
  fi
  _pt_refresh
}

_pt_confirm_overwrite() {
  emulate -L zsh
  local _pt_confirm_reply
  [[ -t 0 ]] || { _pt_error 'destination exists; use --force to overwrite.'; return 1; }
  print -n -u2 -r -- 'pt: overwrite existing environment? [y/N] '
  IFS= read -r _pt_confirm_reply || return 1
  [[ $_pt_confirm_reply == y || $_pt_confirm_reply == Y ]] || { _pt_error 'save cancelled.'; return 1; }
}

_pt_save() {
  emulate -L zsh
  setopt localtraps
  _pt_require_active || return
  local -i _pt_save_force=0 _pt_save_exists=0 _pt_save_rc=0
  local _pt_save_name=$PT_ENV_NAME _pt_save_destination _pt_save_tmp='' _pt_save_var
  local _pt_save_template_dir=${PT_TEMPLATE_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/pt/templates}
  local _pt_save_default_dir=${XDG_CONFIG_HOME:-$HOME/.config}/pt/templates
  local -a _pt_save_flags
  if [[ ${1-} == --force ]]; then
    _pt_save_force=1
    shift
  fi
  (( $# <= 1 )) || { _pt_error 'usage: pt save [--force] [NAME]'; return 2; }
  (( $# )) && _pt_save_name=$1
  _pt_valid_name "$_pt_save_name" || { _pt_error 'invalid save name (pentest is reserved).'; return 2; }
  if [[ ${PWD:A} == "${_pt_save_template_dir:A}" || ${PWD:A} == "${_pt_save_template_dir:A}"/* ||
        ${PWD:A} == "${_pt_save_default_dir:A}" || ${PWD:A} == "${_pt_save_default_dir:A}"/* ]]; then
    _pt_error 'saving inside a template directory is not allowed; change to your project directory.'
    return 1
  fi
  _pt_save_destination=$PWD/$_pt_save_name.env
  [[ ! -L $_pt_save_destination ]] || { _pt_error 'refusing a symlink destination.'; return 1; }
  if [[ -e $_pt_save_destination ]]; then
    [[ -f $_pt_save_destination ]] || { _pt_error 'destination is not a regular file.'; return 1; }
    _pt_save_exists=1
    (( _pt_save_force )) || _pt_confirm_overwrite || return 1
  fi
  # Validate everything before creating a temporary file.
  for _pt_save_var in ${(k)_pt_managed}; do
    _pt_capture "$_pt_save_var" || { _pt_error "cannot save $_pt_save_var: unsupported parameter attributes."; return 1; }
  done
  _pt_save_tmp=$(command mktemp "$PWD/.pt-save.XXXXXXXXXX") || { _pt_error 'cannot create save file.'; return 1; }
  {
    command chmod 600 "$_pt_save_tmp" || _pt_save_rc=1
    if (( ! _pt_save_rc )); then
      {
        print -r -- '# Saved by pt. Trusted Zsh code; may contain cleartext credentials.'
        for _pt_save_var in ${(ok)_pt_managed}; do
          _pt_capture "$_pt_save_var" || { _pt_save_rc=1; break; }
          if [[ $_pt_result_kind == unset ]]; then
            print -r -- "unset -- $_pt_save_var"
          else
            _pt_save_flags=( ${=_pt_result_flags} )
            print -r -- "typeset -g ${_pt_save_flags:+${(j: :)_pt_save_flags} }-- $_pt_save_var=${(qqqq)_pt_result_value}"
          fi
        done
      } >| "$_pt_save_tmp" || _pt_save_rc=1
    fi
    if (( ! _pt_save_rc )); then
      if [[ -L $_pt_save_destination || ( -e $_pt_save_destination && ! -f $_pt_save_destination ) ]]; then
        _pt_save_rc=1
      elif (( _pt_save_exists )); then
        command mv -fT -- "$_pt_save_tmp" "$_pt_save_destination" || _pt_save_rc=1
      else
        # A hard link publishes atomically and refuses a concurrently created file.
        command ln -T -- "$_pt_save_tmp" "$_pt_save_destination" || _pt_save_rc=1
      fi
    fi
  } always {
    command rm -f -- "$_pt_save_tmp"
  }
  (( ! _pt_save_rc )) || { _pt_error 'save failed; environment name and dirty state are unchanged.'; return 1; }
  PT_ENV_NAME=$_pt_save_name
  _pt_dirty=0
  _pt_output success "pt: saved ./$_pt_save_name.env"
  _pt_refresh
}

_pt_list() {
  emulate -L zsh
  local _pt_list_file _pt_list_dir=${PT_TEMPLATE_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/pt/templates}
  for _pt_list_file in ./*.env(N-.); do
    _pt_valid_name "${_pt_list_file:t:r}" || continue
    print -r -- "local     ${_pt_list_file:t:r}"
  done
  for _pt_list_file in "$_pt_list_dir"/*.env(N-.); do
    _pt_valid_name "${_pt_list_file:t:r}" || continue
    print -r -- "template  ${_pt_list_file:t:r}"
  done
}

_pt_command() {
  emulate -L zsh
  (( ! _pt_loading )) || { _pt_error 'pt commands cannot run while loading an environment.'; return 1; }
  local _pt_cmd=${1:-help}
  (( $# )) && shift
  case $_pt_cmd in
    help|--help|-h) (( $# == 0 )) || return 2; _pt_help ;;
    activate) _pt_activate "$@" ;;
    load) _pt_load "$@" ;;
    set) _pt_set "$@" ;;
    unset) _pt_unset "$@" ;;
    rename) _pt_rename "$@" ;;
    edit) (( $# == 0 )) || { _pt_error 'usage: pt edit'; return 2; }; _pt_edit ;;
    save) _pt_save "$@" ;;
    status|list|deactivate)
      (( $# == 0 )) || { _pt_error "$_pt_cmd takes no arguments."; return 2; }
      "_pt_${_pt_cmd}" ;;
    guard) _pt_guard_command "$@" ;;
    *) _pt_activate "$_pt_cmd" "$@" ;;
  esac
}

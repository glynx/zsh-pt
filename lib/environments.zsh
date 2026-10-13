typeset -g _pt_resolved_file=''

_pt_resolve_environment() {
  emulate -L zsh
  local _pt_resolve_name=$1 _pt_resolve_dir=${PT_TEMPLATE_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/pt/templates}
  local -i _pt_resolve_template=$2 _pt_resolve_required=$3
  _pt_resolved_file=''
  if (( ! _pt_resolve_template )) && [[ -e ./$_pt_resolve_name.env || -L ./$_pt_resolve_name.env ]]; then
    _pt_resolved_file=$PWD/$_pt_resolve_name.env
  elif [[ -e $_pt_resolve_dir/$_pt_resolve_name.env || -L $_pt_resolve_dir/$_pt_resolve_name.env ]]; then
    _pt_resolved_file=$_pt_resolve_dir/$_pt_resolve_name.env
  elif (( _pt_resolve_template || _pt_resolve_required )); then
    _pt_error 'environment or template does not exist.'
    return 1
  fi
  if [[ -n $_pt_resolved_file && ( ! -f $_pt_resolved_file || ! -r $_pt_resolved_file ) ]]; then
    _pt_error 'environment source is not a readable regular file.'
    return 1
  fi
}

_pt_source_environment() {
  local -i _pt_source_rc=0
  # Files are trusted shell code; collect changes even when sourcing fails.
  _pt_loading=1
  {
    builtin source "$1" || _pt_source_rc=$?
  } always {
    _pt_loading=0
  }
  _pt_collect_changes || _pt_source_rc=1
  return $_pt_source_rc
}

_pt_load_transaction() {
  # Dynamic scope gives snapshot/restore a temporary baseline for this merge.
  # The active environment's original baseline remains intact in the caller.
  local -A _pt_base_kind _pt_base_value _pt_base_flags _pt_base_signature _pt_managed
  local _pt_load_var
  local _pt_load_reply
  local -a _pt_load_flags _pt_load_display
  local -i _pt_load_display_index
  local -A _pt_load_kinds _pt_load_values _pt_load_attributes
  local -i _pt_load_rc=0
  _pt_snapshot || { _pt_error 'cannot snapshot the current variable state.'; return 1; }
  _pt_source_environment "$1" || _pt_load_rc=1
  for _pt_load_var in ${(k)_pt_managed}; do
    if [[ ${_pt_load_original_kind[$_pt_load_var]-} == unsupported ]]; then
      _pt_error "cannot manage $_pt_load_var: its original attributes are unsupported."
      _pt_load_rc=1
    fi
  done
  _pt_load_changes=( ${(k)_pt_managed} )
  if (( _pt_load_rc )); then
    _pt_error 'load failed; attempting to restore pre-load scalars.'
    _pt_restore_managed || _pt_load_incomplete=1
    return 1
  fi
  (( ! _pt_load_force )) || return 0
  # Source once, capture proposed states, and restore before asking any questions.
  for _pt_load_var in ${(k)_pt_managed}; do
    _pt_capture "$_pt_load_var" || {
      _pt_restore_managed || _pt_load_incomplete=1
      _pt_error 'cannot capture proposed variables; attempted to restore pre-load scalars.'
      return 1
    }
    _pt_load_kinds[$_pt_load_var]=$_pt_result_kind
    _pt_load_values[$_pt_load_var]=$_pt_result_value
    _pt_load_attributes[$_pt_load_var]=$_pt_result_flags
  done
  _pt_restore_managed || { _pt_load_incomplete=1; return 1; }
  for _pt_load_var in ${(ok)_pt_managed}; do
    [[ ${_pt_base_kind[$_pt_load_var]-unset} == scalar ]] || continue
    [[ -t 0 ]] || { _pt_error 'load would replace existing variables; use -f without a terminal.'; return 1; }
    _pt_load_display=( "${_pt_base_value[$_pt_load_var]}" "${_pt_load_values[$_pt_load_var]}" )
    for _pt_load_display_index in 1 2; do
      if [[ $_pt_load_display[$_pt_load_display_index] == *[[:cntrl:]]* ]]; then
        _pt_load_display[$_pt_load_display_index]=${(qqqq)_pt_load_display[$_pt_load_display_index]}
      else
        _pt_load_display[$_pt_load_display_index]=${(qq)_pt_load_display[$_pt_load_display_index]}
      fi
    done
    if [[ $_pt_load_kinds[$_pt_load_var] == unset ]]; then
      _pt_load_display[2]='<unset>'
    elif [[ ${_pt_base_value[$_pt_load_var]} == ${_pt_load_values[$_pt_load_var]} ]]; then
      _pt_load_display[1]+=" (${_pt_base_flags[$_pt_load_var]:-plain})"
      _pt_load_display[2]+=" (${_pt_load_attributes[$_pt_load_var]:-plain})"
    fi
    print -n -u2 -r -- "pt: replace $_pt_load_var: $_pt_load_display[1] -> $_pt_load_display[2]? [y/N] "
    IFS= read -r _pt_load_reply || { print -u2; _pt_error 'load cancelled; variables unchanged.'; return 1; }
    if [[ $_pt_load_reply != (y|Y) ]]; then
      builtin unset "_pt_managed[$_pt_load_var]"
    fi
  done
  # Apply only after all questions have completed, so cancellation is atomic.
  for _pt_load_var in ${(ok)_pt_managed}; do
    builtin unset -- "$_pt_load_var" || _pt_load_rc=1
    if [[ $_pt_load_kinds[$_pt_load_var] == scalar ]]; then
      _pt_load_flags=( ${=_pt_load_attributes[$_pt_load_var]} )
      builtin typeset -g "${_pt_load_flags[@]}" -- "$_pt_load_var=${_pt_load_values[$_pt_load_var]}" || _pt_load_rc=1
    fi
    if (( _pt_load_rc )); then
      _pt_restore_managed || _pt_load_incomplete=1
      _pt_error 'load failed; attempted to restore pre-load scalars.'
      return 1
    fi
  done
  _pt_load_changes=( ${(k)_pt_managed} )
  return 0
}

_pt_load() {
  emulate -L zsh
  _pt_require_active || return
  local -i _pt_load_template=0 _pt_load_force=0 _pt_load_incomplete=0 _pt_load_rc=0
  local _pt_load_file _pt_load_name
  local -a _pt_load_changes
  local -A _pt_load_original_kind=( "${(@kv)_pt_base_kind}" )
  while (( $# )); do
    case $1 in
      -f|--force) _pt_load_force=1; shift ;;
      --template) _pt_load_template=1; shift ;;
      --) shift; break ;;
      *) break ;;
    esac
  done
  (( $# == 1 )) && _pt_valid_name "$1" || {
    _pt_error 'usage: pt load [-f|--force] [--template] NAME (pentest is reserved)'
    return 2
  }
  _pt_resolve_environment "$1" "$_pt_load_template" 1 || return
  _pt_load_file=$_pt_resolved_file
  _pt_load_transaction "$_pt_load_file" || _pt_load_rc=1
  if (( ! _pt_load_rc || _pt_load_incomplete )); then
    for _pt_load_name in "${_pt_load_changes[@]}"; do
      _pt_managed[$_pt_load_name]=1
    done
    (( ! ${#_pt_load_changes} )) || _pt_dirty=1
  fi
  if (( _pt_load_rc )); then
    (( ! _pt_load_incomplete )) || _pt_error 'restoration incomplete; the environment remains active.'
    return 1
  fi
  _pt_output success "pt: loaded $_pt_load_file"
  _pt_refresh
}

_pt_refresh() {
  [[ -o interactive ]] && zle >/dev/null 2>&1 && zle reset-prompt
  return 0
}

_pt_deactivate() {
  emulate -L zsh
  (( _pt_active )) || return 0
  _pt_restore_managed || return 1
  builtin unset PT_ENV_NAME || { _pt_error 'cannot clear PT_ENV_NAME; environment remains active.'; return 1; }
  _pt_active=0 _pt_dirty=0 _pt_source=''
  _pt_base_kind=() _pt_base_value=() _pt_base_flags=() _pt_base_signature=() _pt_managed=()
  _pt_refresh
}

_pt_activate() {
  emulate -L zsh
  local _pt_activate_name _pt_activate_file=''
  local -i _pt_activate_template=0 _pt_activate_rc=0 _pt_activate_fresh=0
  if [[ ${1-} == --template ]]; then
    _pt_activate_template=1
    shift
  fi
  if (( ! $# && ! _pt_activate_template )); then
    _pt_activate_fresh=1
    set -- scratch
  fi
  (( $# == 1 )) || { _pt_error 'usage: pt activate [NAME] | pt activate --template NAME'; return 2; }
  _pt_activate_name=$1
  _pt_valid_name "$_pt_activate_name" || { _pt_error 'invalid environment name (pentest is reserved).'; return 2; }
  if (( ! _pt_activate_fresh )); then
    _pt_resolve_environment "$_pt_activate_name" "$_pt_activate_template" 0 || return
    _pt_activate_file=$_pt_resolved_file
  fi
  if [[ ${parameters[PT_ENV_NAME]-} == *readonly* ]]; then
    _pt_error 'PT_ENV_NAME must be writable.'
    return 1
  fi
  _pt_deactivate || return
  _pt_snapshot || { _pt_error 'cannot snapshot the current variable state.'; return 1; }
  _pt_active=1 _pt_dirty=0 _pt_source=${_pt_activate_file:-'<empty>'}
  builtin typeset -gx PT_ENV_NAME="$_pt_activate_name"
  if [[ -n $_pt_activate_file ]]; then
    _pt_source_environment "$_pt_activate_file" || _pt_activate_rc=1
  fi
  if (( _pt_activate_rc )); then
    _pt_error 'loading failed; attempting to restore managed scalars.'
    _pt_deactivate || _pt_error 'restoration incomplete; the environment remains active.'
    return 1
  fi
  _pt_output success "pt: $PT_ENV_NAME (source: $_pt_source)"
  _pt_refresh
}

typeset -gi _pt_active=0 _pt_dirty=0 _pt_loading=0
typeset -g _pt_source='' _pt_result_value='' _pt_result_flags='' _pt_result_kind='' _pt_result_signature=''
typeset -gA _pt_base_kind _pt_base_value _pt_base_flags _pt_base_signature _pt_managed
typeset -gA _pt_capture_declarations

_pt_error() { _pt_output error "pt: $*" 2; }

_pt_valid_name() {
  emulate -L zsh
  [[ $1 == [a-zA-Z0-9_]* && $1 != *[^a-zA-Z0-9_-]* && $1 != pentest ]]
}

_pt_valid_parameter() {
  emulate -L zsh
  # Watch defaults are shell configuration even when Zsh marks them ordinary.
  [[ $1 == [a-zA-Z_]* && $1 != *[^a-zA-Z0-9_]* &&
     $1 != (_pt_*|PT_*|ZSH_*|ZLE_*|zle_*|PWD|OLDPWD|LOGCHECK|WATCHFMT) ]]
}

# Capture declarations as data. No declaration text is evaluated.
_pt_capture() {
  emulate -L zsh
  local _pt_cap_name=$1 _pt_cap_type=${parameters[$1]-} _pt_cap_decl _pt_cap_raw _pt_cap_display
  local -a _pt_cap_words _pt_cap_options
  _pt_result_value='' _pt_result_flags='' _pt_result_kind=unset _pt_result_signature=''
  [[ -n $_pt_cap_type ]] || return 0
  # Ordinary scalars need no declaration parsing or subshell.
  if [[ $_pt_cap_type == scalar || $_pt_cap_type == scalar-export ]]; then
    _pt_result_value=${(P)_pt_cap_name}
    [[ $_pt_cap_type == scalar-export ]] && _pt_result_flags=-x
    _pt_result_kind=scalar
    _pt_result_signature="$_pt_result_flags:${#_pt_result_value}:$_pt_result_value"
    return 0
  fi
  if [[ $_pt_cap_type == integer || $_pt_cap_type == integer-export ]]; then
    _pt_cap_display=${(P)_pt_cap_name}
    _pt_result_flags=-i
    if [[ $_pt_cap_display == *'#'* ]]; then
      _pt_cap_raw=${_pt_cap_display%%\#*}
      _pt_result_flags+=${_pt_cap_raw#-}
    else
      # Decimal display cannot distinguish an implicit base from explicit -i10.
      if (( ${+_pt_capture_declarations[$_pt_cap_name]} )); then
        _pt_cap_decl=$_pt_capture_declarations[$_pt_cap_name]
      else
        _pt_cap_decl=$(builtin typeset -p -- "$_pt_cap_name") || return 1
      fi
      _pt_cap_words=( ${(z)_pt_cap_decl} )
      for _pt_cap_raw in "${_pt_cap_words[@]}"; do
        [[ $_pt_cap_raw != -i* ]] || _pt_result_flags=$_pt_cap_raw
      done
    fi
    [[ $_pt_cap_type != integer-export ]] || _pt_result_flags+=' -x'
    builtin printf -v _pt_result_value '%d' "$_pt_cap_name" || return 1
    _pt_result_kind=scalar
    _pt_result_signature="$_pt_result_flags:${#_pt_result_value}:$_pt_result_value"
    return 0
  fi
  _pt_result_kind=unsupported
  if [[ $_pt_cap_type == *special* || $_pt_cap_type == *readonly* ||
        $_pt_cap_type == *array* || $_pt_cap_type == *association* ||
        $_pt_cap_type == *tied* || $_pt_cap_type == *local* ]]; then
    # Compare unsupported values as data without forking for every plugin array.
    local -a _pt_cap_items
    if [[ $_pt_cap_type == *association* ]]; then
      local -A _pt_cap_map
      local _pt_cap_key
      _pt_cap_map=( "${(@kvP)_pt_cap_name}" )
      for _pt_cap_key in ${(ok)_pt_cap_map}; do
        _pt_cap_items+=( "${(qqqq)_pt_cap_key}=${(qqqq)_pt_cap_map[$_pt_cap_key]}" )
      done
    elif [[ $_pt_cap_type == *array* ]]; then
      _pt_cap_items=( "${(@P)_pt_cap_name}" )
      _pt_cap_items=( "${(@qqqq)_pt_cap_items}" )
    else
      _pt_cap_items=( "${(qqqq)${(P)_pt_cap_name}}" )
    fi
    _pt_result_signature="$_pt_cap_type:${(j: :)_pt_cap_items}"
    return 1
  fi
  _pt_result_signature=$(builtin typeset -p -- "$_pt_cap_name")
  _pt_cap_display=${(P)_pt_cap_name}
  if [[ $_pt_cap_type == *hideval* ]]; then
    # Unhide only in a subshell, keeping both the value and attribute private.
    _pt_cap_decl=$(builtin typeset -g +H -- "$_pt_cap_name"; builtin typeset -p -- "$_pt_cap_name") || return 1
    _pt_cap_options+=( -H )
  else
    _pt_cap_decl=$_pt_result_signature
  fi
  _pt_cap_words=( ${(z)_pt_cap_decl} )
  [[ $_pt_cap_words[1] == export ]] && _pt_cap_options+=( -x )
  local _pt_cap_word
  for _pt_cap_word in "${_pt_cap_words[@]:1}"; do
    [[ $_pt_cap_word == -* ]] || break
    [[ $_pt_cap_word == -g || $_pt_cap_word == -- ]] || _pt_cap_options+=( "$_pt_cap_word" )
  done
  _pt_cap_raw=${_pt_cap_words[-1]#*=}
  _pt_result_value=${(Q)_pt_cap_raw}
  if [[ $_pt_cap_type == float* ]]; then
    # typeset -p omits display precision and rounds floats; retain both explicitly.
    local -i _pt_cap_index
    for (( _pt_cap_index=1; _pt_cap_index <= ${#_pt_cap_options}; ++_pt_cap_index )); do
      if [[ $_pt_cap_options[$_pt_cap_index] == -F ]]; then
        _pt_cap_raw=${_pt_cap_display#*.}
        _pt_cap_options[$_pt_cap_index]=-F${#_pt_cap_raw}
      elif [[ $_pt_cap_options[$_pt_cap_index] == -E ]]; then
        _pt_cap_raw=${_pt_cap_display%%e*}
        _pt_cap_raw=${_pt_cap_raw//[.\-+]/}
        _pt_cap_options[$_pt_cap_index]=-E${#_pt_cap_raw}
      fi
    done
    builtin printf -v _pt_result_value '%.17g' "$_pt_cap_name" || return 1
    [[ $_pt_result_value != *[a-df-zA-DF-Z]* ]] || return 1
  fi
  _pt_result_flags=${(j: :)_pt_cap_options}
  _pt_result_kind=scalar
  _pt_result_signature="$_pt_result_flags:${#_pt_result_value}:$_pt_result_value"
}

_pt_candidate() {
  _pt_valid_parameter "$1" && [[ ${parameters[$1]-} != *special* &&
     ${parameters[$1]-} != *local* ]]
}

_pt_capture_integer_declarations() {
  local _pt_decl_name _pt_decl_text _pt_decl_line
  local -a _pt_decl_names _pt_decl_words
  for _pt_decl_name in ${(k)parameters}; do
    [[ ${parameters[$_pt_decl_name]} == (integer|integer-export) ]] || continue
    _pt_candidate "$_pt_decl_name" && _pt_decl_names+=( "$_pt_decl_name" )
  done
  (( ${#_pt_decl_names} )) || return 0
  # One capture per scan preserves integer attributes without per-variable forks.
  _pt_decl_text=$(builtin typeset -p -- "${_pt_decl_names[@]}") || return 1
  for _pt_decl_line in "${(@f)_pt_decl_text}"; do
    _pt_decl_words=( ${(z)_pt_decl_line} )
    _pt_decl_name=${_pt_decl_words[-1]%%=*}
    _pt_capture_declarations[$_pt_decl_name]=$_pt_decl_line
  done
}

_pt_snapshot() {
  emulate -L zsh
  local _pt_snap_name
  local -A _pt_capture_declarations
  _pt_capture_integer_declarations || return 1
  _pt_base_kind=() _pt_base_value=() _pt_base_flags=() _pt_base_signature=() _pt_managed=()
  for _pt_snap_name in ${(k)parameters}; do
    _pt_candidate "$_pt_snap_name" || continue
    _pt_capture "$_pt_snap_name" || true
    _pt_base_kind[$_pt_snap_name]=$_pt_result_kind
    _pt_base_value[$_pt_snap_name]=$_pt_result_value
    _pt_base_flags[$_pt_snap_name]=$_pt_result_flags
    _pt_base_signature[$_pt_snap_name]=$_pt_result_signature
  done
}

_pt_collect_changes() {
  emulate -L zsh
  local -A _pt_capture_declarations
  _pt_capture_integer_declarations || return 1
  local _pt_collect_name _pt_collect_sig
  local -i _pt_collect_failed=0
  local -A _pt_collect_names
  for _pt_collect_name in ${(k)_pt_base_kind} ${(k)parameters}; do
    _pt_collect_names[$_pt_collect_name]=1
  done
  for _pt_collect_name in ${(k)_pt_collect_names}; do
    _pt_candidate "$_pt_collect_name" || continue
    _pt_capture "$_pt_collect_name" || true
    _pt_collect_sig=$_pt_result_signature
    [[ $_pt_collect_sig != ${_pt_base_signature[$_pt_collect_name]-} ]] || continue
    if [[ $_pt_result_kind == unsupported || ${_pt_base_kind[$_pt_collect_name]-} == unsupported ]]; then
      _pt_error "unsupported change to $_pt_collect_name (array, readonly, or tied parameter); restoration is not guaranteed."
      if [[ ${_pt_base_kind[$_pt_collect_name]-unset} != unsupported ]]; then
        _pt_managed[$_pt_collect_name]=1
      fi
      _pt_collect_failed=1
    else
      _pt_managed[$_pt_collect_name]=1
    fi
  done
  return $_pt_collect_failed
}

_pt_restore_one() {
  emulate -L zsh
  local _pt_restore_name=$1
  local -a _pt_restore_flags
  if [[ ${parameters[$_pt_restore_name]-} == *readonly* ||
        ${parameters[$_pt_restore_name]-} == *special* ||
        ${parameters[$_pt_restore_name]-} == *tied* ]]; then
    _pt_error "cannot restore $_pt_restore_name: it is now readonly, special, or tied."
    return 1
  fi
  builtin unset -- "$_pt_restore_name" || return 1
  if [[ ${_pt_base_kind[$_pt_restore_name]-unset} == scalar ]]; then
    _pt_restore_flags=( ${=_pt_base_flags[$_pt_restore_name]} )
    builtin typeset -g "${_pt_restore_flags[@]}" -- "$_pt_restore_name=${_pt_base_value[$_pt_restore_name]}"
  fi
}

_pt_restore_managed() {
  local _pt_restore_var
  local -i _pt_restore_failed=0
  for _pt_restore_var in ${(k)_pt_managed}; do
    _pt_restore_one "$_pt_restore_var" || _pt_restore_failed=1
  done
  return $_pt_restore_failed
}

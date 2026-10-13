typeset -ga _pt_scan_names _pt_scan_unchecked _pt_guard_missing
typeset -ga _pt_scan_refs _pt_scan_starts _pt_scan_ends _pt_scan_quotes _pt_scan_defaults _pt_scan_fallbacks
typeset -g _pt_preview_command=''
typeset -gA _pt_scan_required

# Inspect a deliberately small syntax subset. Never expand or evaluate the buffer.
_pt_scan() {
  emulate -L zsh
  local _pt_scan_text=$1 _pt_scan_char _pt_scan_next _pt_scan_quote=''
  local _pt_scan_name _pt_scan_expr _pt_scan_tail
  local MATCH MBEGIN MEND
  local -a match mbegin mend
  local -i _pt_scan_i=1 _pt_scan_j _pt_scan_optional _pt_scan_start
  local _pt_scan_default
  local -A _pt_scan_seen
  _pt_scan_names=() _pt_scan_unchecked=() _pt_scan_required=()
  _pt_scan_refs=() _pt_scan_starts=() _pt_scan_ends=() _pt_scan_quotes=()
  _pt_scan_defaults=() _pt_scan_fallbacks=()
  while (( _pt_scan_i <= ${#_pt_scan_text} )); do
    _pt_scan_char=$_pt_scan_text[$_pt_scan_i]
    _pt_scan_next=$_pt_scan_text[$(( _pt_scan_i + 1 ))]
    if [[ $_pt_scan_quote == single ]]; then
      [[ $_pt_scan_char == "'" ]] && _pt_scan_quote=''
      (( ++_pt_scan_i )); continue
    elif [[ $_pt_scan_quote == ansi ]]; then
      if [[ $_pt_scan_char == \\ ]]; then
        (( _pt_scan_i += 2 )); continue
      fi
      [[ $_pt_scan_char == "'" ]] && _pt_scan_quote=''
      (( ++_pt_scan_i )); continue
    fi
    if [[ $_pt_scan_char == \\ ]]; then
      if [[ $_pt_scan_quote != double || $_pt_scan_next == [\$\`\"\\] || $_pt_scan_next == $'\n' ]]; then
        (( _pt_scan_i += 2 )); continue
      fi
    fi
    if [[ $_pt_scan_char == '"' ]]; then
      if [[ $_pt_scan_quote == double ]]; then _pt_scan_quote=''; else _pt_scan_quote=double; fi
      (( ++_pt_scan_i )); continue
    fi
    if [[ -z $_pt_scan_quote && $_pt_scan_char == "'" ]]; then
      _pt_scan_quote=single
      (( ++_pt_scan_i )); continue
    fi
    if [[ $_pt_scan_char == '`' ||
          ( -z $_pt_scan_quote && $_pt_scan_text[$_pt_scan_i,$(( _pt_scan_i + 1 ))] == ('<<'|'<('|'>(') ) ]]; then
      _pt_scan_unchecked+=( 'substitution or heredoc; remaining buffer unchecked' )
      break
    fi
    if [[ -z $_pt_scan_quote && $_pt_scan_char == '#' &&
          ( $_pt_scan_i == 1 || $_pt_scan_text[$(( _pt_scan_i - 1 ))] == [[:space:]\;\|\&] ) ]]; then
      _pt_scan_unchecked+=( 'comment syntax; remaining buffer unchecked' )
      break
    fi
    [[ $_pt_scan_char == '$' ]] || { (( ++_pt_scan_i )); continue; }
    if [[ $_pt_scan_next == "'" && -z $_pt_scan_quote ]]; then
      _pt_scan_quote=ansi
      (( _pt_scan_i += 2 )); continue
    fi
    if [[ $_pt_scan_next == '(' ]]; then
      _pt_scan_unchecked+=( 'command or arithmetic substitution; remaining buffer unchecked' )
      break
    fi
    _pt_scan_name='' _pt_scan_optional=0 _pt_scan_default='' _pt_scan_tail=''
    _pt_scan_start=$_pt_scan_i
    if [[ $_pt_scan_next == '{' ]]; then
      _pt_scan_j=$(( _pt_scan_i + 2 ))
      while (( _pt_scan_j <= ${#_pt_scan_text} )) && [[ $_pt_scan_text[$_pt_scan_j] != '}' ]]; do
        (( ++_pt_scan_j ))
      done
      if (( _pt_scan_j > ${#_pt_scan_text} )); then
        _pt_scan_unchecked+=( 'unclosed parameter expression' ); break
      fi
      _pt_scan_expr=$_pt_scan_text[$(( _pt_scan_i + 2 )),$(( _pt_scan_j - 1 ))]
      _pt_scan_i=$_pt_scan_j
      if [[ $_pt_scan_expr =~ '^([a-zA-Z_][a-zA-Z0-9_]*)(:-|-)(.*)$' ]]; then
        _pt_scan_name=$match[1] _pt_scan_default=$match[2] _pt_scan_tail=$match[3]
        if [[ $_pt_scan_tail == *[\$\`\{\}\\\"\']* ]]; then
          _pt_scan_unchecked+=( 'complex parameter default' ); (( ++_pt_scan_i )); continue
        fi
        _pt_scan_optional=1
      elif [[ $_pt_scan_expr =~ '^[a-zA-Z_][a-zA-Z0-9_]*$' ]]; then
        _pt_scan_name=$_pt_scan_expr
      else
        _pt_scan_unchecked+=( 'unsupported parameter expression' ); (( ++_pt_scan_i )); continue
      fi
    elif [[ $_pt_scan_next == [a-zA-Z_] ]]; then
      _pt_scan_j=$(( _pt_scan_i + 1 ))
      while (( _pt_scan_j <= ${#_pt_scan_text} )) && [[ $_pt_scan_text[$_pt_scan_j] == [a-zA-Z0-9_] ]]; do
        _pt_scan_name+=$_pt_scan_text[$_pt_scan_j]
        (( ++_pt_scan_j ))
      done
      _pt_scan_i=$(( _pt_scan_j - 1 ))
    else
      _pt_scan_unchecked+=( 'unsupported dollar expression' )
    fi
    if [[ -n $_pt_scan_name ]]; then
      _pt_scan_refs+=( "$_pt_scan_name" )
      _pt_scan_starts+=( "$_pt_scan_start" )
      _pt_scan_ends+=( "$_pt_scan_i" )
      _pt_scan_quotes+=( "$_pt_scan_quote" )
      _pt_scan_defaults+=( "$_pt_scan_default" )
      _pt_scan_fallbacks+=( "$_pt_scan_tail" )
      if (( ! ${+_pt_scan_seen[$_pt_scan_name]} )); then
        _pt_scan_names+=( "$_pt_scan_name" )
        _pt_scan_seen[$_pt_scan_name]=1
      fi
      (( _pt_scan_optional )) || _pt_scan_required[$_pt_scan_name]=1
    fi
    (( ++_pt_scan_i ))
  done
  [[ -z $_pt_scan_quote ]] || _pt_scan_unchecked+=( 'unclosed quote' )
  return 0
}

_pt_render_preview() {
  emulate -L zsh
  local _pt_render_text=$1 _pt_render_name _pt_render_value _pt_render_quoted
  local -i _pt_render_i _pt_render_from=1
  _pt_scan "$_pt_render_text"
  _pt_preview_command=''
  for (( _pt_render_i=1; _pt_render_i <= ${#_pt_scan_refs}; ++_pt_render_i )); do
    _pt_render_name=$_pt_scan_refs[$_pt_render_i]
    if (( _pt_scan_starts[$_pt_render_i] > _pt_render_from )); then
      _pt_preview_command+=$_pt_render_text[$_pt_render_from,$(( _pt_scan_starts[$_pt_render_i] - 1 ))]
    fi
    if ! _pt_capture "$_pt_render_name"; then
      _pt_scan_unchecked+=( "$_pt_render_name has unsupported attributes" )
      _pt_preview_command+=$_pt_render_text[$_pt_scan_starts[$_pt_render_i],$_pt_scan_ends[$_pt_render_i]]
    else
      _pt_render_value=${(P)_pt_render_name}
      if [[ $_pt_result_kind == unset && -n $_pt_scan_defaults[$_pt_render_i] ||
            -z $_pt_render_value && $_pt_scan_defaults[$_pt_render_i] == ':-' ]]; then
        _pt_render_value=$_pt_scan_fallbacks[$_pt_render_i]
      fi
      if [[ $_pt_scan_quotes[$_pt_render_i] == double ]]; then
        if [[ $_pt_render_value == *[[:cntrl:]]* ]]; then
          # Close and reopen the surrounding quote to show control bytes safely.
          _pt_render_quoted="\"${(qqqq)_pt_render_value}\""
        else
          _pt_render_quoted=${_pt_render_value//\\/\\\\}
          _pt_render_quoted=${_pt_render_quoted//\"/\\\"}
          _pt_render_quoted=${_pt_render_quoted//\$/\\\$}
          _pt_render_quoted=${_pt_render_quoted//\`/\\\`}
        fi
      else
        _pt_render_quoted=${(q+)_pt_render_value}
      fi
      _pt_preview_command+=$_pt_render_quoted
    fi
    _pt_render_from=$(( _pt_scan_ends[$_pt_render_i] + 1 ))
  done
  if (( _pt_render_from <= ${#_pt_render_text} )); then
    _pt_preview_command+=$_pt_render_text[$_pt_render_from,-1]
  fi
}

_pt_guard_check() {
  emulate -L zsh
  _pt_scan "$1"
  local _pt_check_name
  local -a _pt_check_optional
  _pt_check_optional=( ${PT_OPTIONAL_VARS[@]} )
  _pt_guard_missing=()
  for _pt_check_name in "${_pt_scan_names[@]}"; do
    (( ${+_pt_scan_required[$_pt_check_name]} )) || continue
    (( ${_pt_check_optional[(Ie)$_pt_check_name]} )) && continue
    if ! _pt_capture "$_pt_check_name"; then
      _pt_scan_unchecked+=( "$_pt_check_name has unsupported attributes" )
    elif [[ $_pt_result_kind == unset ]]; then
      _pt_guard_missing+=( "$_pt_check_name" )
    fi
  done
}

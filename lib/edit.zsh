_pt_edit() {
  emulate -L zsh
  _pt_require_active || return
  local _pt_edit_name _pt_edit_file='' _pt_edit_data _pt_edit_before _pt_edit_value
  local -a _pt_edit_command _pt_edit_records
  local -A _pt_edit_names _pt_edit_values _pt_edit_kinds
  local -i _pt_edit_i _pt_edit_changed=0
  _pt_edit_command=( ${(z)${VISUAL:-${EDITOR:-vi}}} )
  _pt_edit_command=( "${(@Q)_pt_edit_command}" )
  (( ${#_pt_edit_command} )) || { _pt_error 'set VISUAL or EDITOR to an editor command.'; return 1; }
  for _pt_edit_name in ${(k)_pt_managed}; do
    (( ${+parameters[$_pt_edit_name]} )) && _pt_edit_names[$_pt_edit_name]=1
  done
  for _pt_edit_name in "$@"; do
    _pt_edit_names[$_pt_edit_name]=1
  done
  for _pt_edit_name in ${(k)_pt_edit_names}; do
    _pt_valid_parameter "$_pt_edit_name" && _pt_capture "$_pt_edit_name" &&
      [[ ${_pt_base_kind[$_pt_edit_name]-} != unsupported ]] || {
      _pt_error "cannot edit $_pt_edit_name: unsupported parameter attributes."
      return 1
    }
  done
  _pt_edit_file=$(command mktemp "${TMPDIR:-/tmp}/pt-edit.XXXXXXXXXX") || { _pt_error 'cannot create editing file.'; return 1; }
  {
    command chmod 600 "$_pt_edit_file" || return 1
    {
      print -r -- '# Trusted Zsh assignments. Save and quit to apply; exit nonzero to cancel.'
      print -r -- "# Empty: NAME=''. Unset: unset -- NAME. Deleting an assignment also unsets it."
      print -r -- '# Uncomment missing variables and enter values; commented variables remain unset.'
      print -r -- '# Changes stay in memory; use pt save to save an environment file.'
      for _pt_edit_name in ${(ok)_pt_edit_names}; do
        _pt_capture "$_pt_edit_name" || return 1
        if [[ $_pt_result_kind == unset ]]; then
          print -r -- "# $_pt_edit_name=''"
        elif [[ -z $_pt_result_value ]]; then
          print -r -- "$_pt_edit_name=''"
        else
          print -r -- "$_pt_edit_name=${(qqqq)_pt_result_value}"
        fi
      done
    } >| "$_pt_edit_file" || { _pt_error 'cannot write editing file.'; return 1; }
    _pt_edit_before=$(<"$_pt_edit_file")
    command "${_pt_edit_command[@]}" "$_pt_edit_file" || { _pt_error 'editing cancelled; environment unchanged.'; return 1; }
    [[ -f $_pt_edit_file && ! -L $_pt_edit_file ]] || { _pt_error 'editing file is missing or is a symlink.'; return 1; }
    [[ $(<"$_pt_edit_file") != $_pt_edit_before ]] || return 0
    command zsh -f -n "$_pt_edit_file" >/dev/null 2>&1 || { _pt_error 'invalid Zsh syntax; environment unchanged.'; return 1; }
    _pt_edit_data=$(command zsh -f "$_pt_plugin_dir/lib/edit-worker.zsh" "$_pt_edit_file" "${(@ok)_pt_edit_names}" 2>/dev/null) || {
      _pt_error 'edited file failed or changed unsupported variables; environment unchanged.'
      return 1
    }
    _pt_edit_records=( "${(@f)_pt_edit_data}" )
    [[ -n $_pt_edit_data ]] || _pt_edit_records=()
    (( ${#_pt_edit_records} % 3 == 0 )) || { _pt_error 'invalid editor result; environment unchanged.'; return 1; }
    # Decode generated records as data and validate all names before applying any.
    for (( _pt_edit_i=1; _pt_edit_i <= ${#_pt_edit_records}; _pt_edit_i+=3 )); do
      _pt_edit_name=$_pt_edit_records[$_pt_edit_i]
      _pt_valid_parameter "$_pt_edit_name" && _pt_capture "$_pt_edit_name" &&
        [[ ${_pt_base_kind[$_pt_edit_name]-} != unsupported && $_pt_edit_records[$(( _pt_edit_i + 1 ))] == (scalar|unset) ]] || {
        _pt_error 'edited file contains an unsupported variable; environment unchanged.'
        return 1
      }
      _pt_edit_kinds[$_pt_edit_name]=$_pt_edit_records[$(( _pt_edit_i + 1 ))]
      _pt_edit_value=$_pt_edit_records[$(( _pt_edit_i + 2 ))]
      _pt_edit_values[$_pt_edit_name]=${(Q)_pt_edit_value}
    done
    for _pt_edit_name in ${(ok)_pt_edit_kinds}; do
      _pt_capture "$_pt_edit_name" || return 1
      if [[ $_pt_edit_kinds[$_pt_edit_name] == unset ]]; then
        [[ $_pt_result_kind != unset ]] || continue
        _pt_unset "$_pt_edit_name" || return 1
      else
        [[ $_pt_result_kind == unset || $_pt_result_value != ${_pt_edit_values[$_pt_edit_name]} ]] || continue
        _pt_set "$_pt_edit_name" "${_pt_edit_values[$_pt_edit_name]}" || return 1
      fi
      _pt_edit_changed=1
    done
    (( ! _pt_edit_changed )) || _pt_output success 'pt: edited environment'
  } always {
    command rm -f -- "$_pt_edit_file"
  }
  return 0
}

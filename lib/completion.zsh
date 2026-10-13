# Collect names only. Completion never sources files or reads parameter values.
_pt_completion_names() {
  emulate -L zsh
  local _pt_complete_kind=$1 _pt_complete_file _pt_complete_name _pt_complete_type
  local _pt_complete_dir=${PT_TEMPLATE_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/pt/templates}
  _pt_completion_candidates=()
  if [[ $_pt_complete_kind == parameters ]]; then
    for _pt_complete_name in ${(k)parameters} ${(k)_pt_managed} "${PT_CHECK_VARS[@]}"; do
      _pt_valid_parameter "$_pt_complete_name" || continue
      _pt_complete_type=${parameters[$_pt_complete_name]-}
      [[ $_pt_complete_type != *special* && $_pt_complete_type != *readonly* &&
         $_pt_complete_type != *array* && $_pt_complete_type != *association* &&
         $_pt_complete_type != *tied* && $_pt_complete_type != *local* &&
         ${_pt_base_kind[$_pt_complete_name]-} != unsupported ]] || continue
      _pt_completion_candidates+=( "$_pt_complete_name" )
    done
  else
    if [[ $_pt_complete_kind != templates ]]; then
      for _pt_complete_file in ./*.env(N-.); do
        _pt_complete_name=${_pt_complete_file:t:r}
        _pt_valid_name "$_pt_complete_name" && _pt_completion_candidates+=( "$_pt_complete_name" )
      done
    fi
    if [[ $_pt_complete_kind == (all|templates) ]]; then
      for _pt_complete_file in "$_pt_complete_dir"/*.env(N-.); do
        _pt_complete_name=${_pt_complete_file:t:r}
        _pt_valid_name "$_pt_complete_name" && _pt_completion_candidates+=( "$_pt_complete_name" )
      done
    fi
    if [[ $_pt_complete_kind == save && -n ${PT_ENV_NAME-} ]]; then
      _pt_completion_candidates+=( "$PT_ENV_NAME" )
    fi
  fi
  _pt_completion_candidates=( ${(ou)_pt_completion_candidates} )
  return 0
}

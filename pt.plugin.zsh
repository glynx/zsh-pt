# pt: temporary, named pentest environments for Zsh.
if [[ -n ${_pt_loaded-} ]]; then
  return 0
fi
if (( ${+aliases[pt]} || ${+galiases[pt]} || ${+functions[pt]} || ${+commands[pt]} )); then
  print -u2 -r -- 'pt: warning: an existing pt command will be shadowed.'
fi
(( ${+aliases[pt]} || ${+galiases[pt]} )) && builtin unalias pt

typeset -g _pt_plugin_dir=${${(%):-%x}:A:h}
zmodload zsh/parameter || return
zmodload zsh/zle || return
source "$_pt_plugin_dir/lib/output.zsh" || return
source "$_pt_plugin_dir/lib/state.zsh" || return
source "$_pt_plugin_dir/lib/environments.zsh" || return
source "$_pt_plugin_dir/lib/commands.zsh" || return
source "$_pt_plugin_dir/lib/edit.zsh" || return
source "$_pt_plugin_dir/lib/inspect.zsh" || return
source "$_pt_plugin_dir/lib/editor.zsh" || return
source "$_pt_plugin_dir/lib/completion.zsh" || return
if (( ! ${fpath[(Ie)$_pt_plugin_dir/completions]} )); then
  fpath=("$_pt_plugin_dir/completions" "${fpath[@]}")
fi
autoload -Uz _pt
(( ${+functions[compdef]} )) && compdef _pt pt

# Define by name so an existing alias cannot expand the function definition.
function pt {
  _pt_command "$@"
}
typeset -g _pt_loaded=1
_pt_editor_install

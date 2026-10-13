# Source this file in an interactive Zsh for a temporary test setup.
if [[ ! -o interactive ]]; then
  print -u2 -r -- 'pt: source examples/quickstart.zsh in an interactive Zsh.'
  return 1
fi

function {
  local quickstart_dir=${${(%):-%x}:A:h}
  source "$quickstart_dir/../pt.plugin.zsh" || return

  if (( ! ${+functions[compdef]} )); then
    autoload -Uz compinit
    compinit -D || return
  fi

  if (( ${+functions[p10k]} )); then
    source "$quickstart_dir/powerlevel10k.zsh" || return
    if (( ! ${POWERLEVEL9K_LEFT_PROMPT_ELEMENTS[(Ie)pt]} &&
          ! ${POWERLEVEL9K_RIGHT_PROMPT_ELEMENTS[(Ie)pt]} )); then
      POWERLEVEL9K_LEFT_PROMPT_ELEMENTS+=(pt)
    fi
    p10k reload
  else
    source "$quickstart_dir/prompt.zsh" || return
  fi

  (( _pt_active )) || pt activate || return
  pt guard warn
}

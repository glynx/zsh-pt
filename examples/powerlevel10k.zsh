# Source with your p10k configuration; add pt to its existing prompt elements.
prompt_pt() {
  [[ -n ${PT_ENV_NAME-} ]] || return
  p10k segment -b 0 -f 7 -t 'pt'
}

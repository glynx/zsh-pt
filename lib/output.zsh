# Format literal text without prompt expansion or interpreting user values.
typeset -g PT_COLOR=${PT_COLOR:-auto}
typeset -g _pt_formatted=''

_pt_format() {
  emulate -L zsh
  local _pt_format_style=$1 _pt_format_text=$2 _pt_format_fd=${3:-1}
  local _pt_format_code=''
  _pt_formatted=$_pt_format_text
  [[ ${+NO_COLOR} == 0 && ${TERM-} != dumb ]] || return 0
  case $PT_COLOR in
    always) ;;
    auto) [[ -t $_pt_format_fd ]] || return 0 ;;
    *) return 0 ;;
  esac
  case $_pt_format_style in
    error) _pt_format_code=$'\e[31m' ;;
    warning) _pt_format_code=$'\e[33m' ;;
    success) _pt_format_code=$'\e[32m' ;;
    heading) _pt_format_code=$'\e[1;36m' ;;
    status) _pt_format_code=$'\e[1m' ;;
    muted) _pt_format_code=$'\e[2m' ;;
    *) return 0 ;;
  esac
  _pt_formatted="$_pt_format_code$_pt_format_text"$'\e[0m'
}

_pt_output() {
  emulate -L zsh
  local _pt_output_fd=${3:-1}
  _pt_format "$1" "$2" "$_pt_output_fd"
  print -r -u "$_pt_output_fd" -- "$_pt_formatted"
}

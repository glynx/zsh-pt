# Evaluate only the explicitly edited file, never the command buffer.
emulate -R zsh
zmodload zsh/parameter || exit 1
typeset _pt_worker_dir=${0:A:h} _pt_worker_file=$1 _pt_worker_name
shift
source "$_pt_worker_dir/output.zsh" || exit 1
source "$_pt_worker_dir/state.zsh" || exit 1
typeset -A _pt_worker_names
for _pt_worker_name in "$@"; do
  _pt_valid_parameter "$_pt_worker_name" || exit 1
  _pt_worker_names[$_pt_worker_name]=1
  builtin unset -- "$_pt_worker_name" || exit 1
done
_pt_snapshot || exit 1
{ builtin source "$_pt_worker_file" } >/dev/null 2>&1 || exit 1
_pt_collect_changes >/dev/null 2>&1 || exit 1
for _pt_worker_name in ${(k)_pt_managed}; do
  _pt_worker_names[$_pt_worker_name]=1
done
for _pt_worker_name in ${(ok)_pt_worker_names}; do
  _pt_valid_parameter "$_pt_worker_name" || exit 1
  _pt_capture "$_pt_worker_name" || exit 1
  # Three lines per record; ANSI-C quoting keeps values on a single data line.
  builtin print -rl -- "$_pt_worker_name" "$_pt_result_kind" "${(qqqq)_pt_result_value}"
done

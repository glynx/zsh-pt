# Source after setting your prompt. pt itself never changes PROMPT.
setopt prompt_subst
if [[ $PROMPT != *'${PT_ENV_NAME:+[pt] }'* ]]; then
  PROMPT='${PT_ENV_NAME:+[pt] }'"$PROMPT"
fi

.PHONY: test syntax

syntax:
	@for file in pt.plugin.zsh lib/*.zsh completions/_pt examples/*.zsh; do zsh -n "$$file" || exit; done

test: syntax
	python3 -m unittest discover -s tests -v
	git diff --check

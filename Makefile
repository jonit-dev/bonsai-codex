.PHONY: install test status stop clean

install:
	./install.sh

test:
	python3 -m py_compile src/ollama_codex_proxy.py src/ollama_codex_proxy/*.py
	for test_file in tests/test_*.py; do python3 "$$test_file" || exit 1; done
	bash -n bin/llama-codex install.sh

status:
	./bin/llama-codex --llama-status

stop:
	./bin/llama-codex --llama-stop

clean:
	rm -rf src/__pycache__ tests/__pycache__ .pytest_cache

.PHONY: check health syntax

check:
	python3 -m py_compile app.py maintenance.py

health:
	./healthcheck.sh

syntax:
	bash -n ../install.sh

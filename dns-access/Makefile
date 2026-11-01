.PHONY: check health syntax tests unbound nftables services version

check:
python3 -m py_compile app.py maintenance.py

health:
./healthcheck.sh

syntax:
bash -n ../install.sh
bash -n ../scripts/*.sh

tests:
../scripts/run-tests.sh

unbound:
../scripts/test-unbound.sh

nftables:
../scripts/test-nftables.sh

services:
../scripts/test-services.sh

version:
../scripts/version.sh

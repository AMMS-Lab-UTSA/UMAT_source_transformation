# Convenience targets over the canonical entry points. Each one is a thin
# wrapper: everything here can also be run directly with python, and the
# reproduction profiles are the supported interface.

PYTHON ?= python
PROFILE_ARGS ?=

.PHONY: help setup test test-fortran test-offline audit \
        reproduce-smoke reproduce-offline reproduce-paper reproduce-corpus \
        reproduce-abaqus clean-clone clean

help:
	@echo "setup              install the package and its test extras"
	@echo "test               the offline suite (no Abaqus, ARC or network)"
	@echo "test-fortran       only the tests that need a Fortran compiler"
	@echo "audit              repository-standards audit"
	@echo "reproduce-smoke    a few minutes: install plus one verified model"
	@echo "reproduce-offline  every redistributable test, no Abaqus or network"
	@echo "reproduce-paper    regenerate every currently reproducible artefact"
	@echo "reproduce-corpus   a new licensed network round (needs --allow-network)"
	@echo "reproduce-abaqus   optional paired Abaqus validation (needs ARC)"
	@echo "clean-clone        prove a fresh clone reproduces with nothing local"

setup:
	$(PYTHON) -m pip install -e ".[test]"

test:
	$(PYTHON) -m pytest -q -m "not abaqus and not arc and not network"

test-offline: test

test-fortran:
	$(PYTHON) -m pytest -q -m "fortran"

audit:
	$(PYTHON) tools/audit_repository_standards.py

reproduce-smoke:
	$(PYTHON) -m umat_oti.reproduce --profile smoke $(PROFILE_ARGS)

reproduce-offline:
	$(PYTHON) -m umat_oti.reproduce --profile offline $(PROFILE_ARGS)

reproduce-paper:
	$(PYTHON) -m umat_oti.reproduce --profile paper $(PROFILE_ARGS)

reproduce-corpus:
	$(PYTHON) -m umat_oti.reproduce --profile corpus --allow-network $(PROFILE_ARGS)

reproduce-abaqus:
	$(PYTHON) -m umat_oti.reproduce --profile abaqus $(PROFILE_ARGS)

clean-clone:
	./scripts/clean_clone_acceptance.sh

clean:
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	find . -name '*.o' -o -name '*.mod' -o -name '*.so' | xargs -r rm -f
	rm -rf build/ reproduce/

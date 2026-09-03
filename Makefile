# Convenience targets over the canonical entry points. Each one is a thin
# wrapper: everything here can also be run directly with python, and the
# reproduction profiles are the supported interface.

PYTHON ?= python
PROFILE_ARGS ?=

.PHONY: help setup test test-fortran test-offline audit \
        reproduce-smoke reproduce-offline reproduce-paper reproduce-corpus \
        reproduce-abaqus batch batch-transform batch-offline batch-abaqus \
        batch-status clean-clone clean

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
	@echo ""
	@echo "batch-status       what the transform store holds, and how much is stale"
	@echo "batch-transform    transform every discovered source into the store"
	@echo "batch-offline      fast parity gate over the store (minutes, no Abaqus)"
	@echo "batch-abaqus       paired Abaqus verification over the store (hours)"
	@echo "batch              all three in order -- the full chain after a change"

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

# The store keys every entry on a fingerprint of the transform code, so a
# change to the transform makes every cached entry stale and these targets
# rebuild and re-check rather than serving the previous run's output. That is
# the point of the chain: after a change, `make batch` re-establishes what
# still holds instead of leaving yesterday's numbers in place.
batch-status:
	$(PYTHON) tools/transform_all.py --status

batch-transform:
	$(PYTHON) tools/transform_all.py $(BATCH_ARGS)

batch-offline:
	$(PYTHON) tools/verify_store_offline.py $(BATCH_ARGS)

# Sequential by default: the licence server this runs against is shared, and
# two concurrent jobs double the tokens demanded of it.
batch-abaqus:
	$(PYTHON) tools/verify_store_in_abaqus.py $(BATCH_ARGS)

# The offline gate runs before Abaqus on purpose. It costs seconds per source
# and Abaqus costs minutes, so a source whose two builds already disagree at a
# material point should be fixed before it is given a licence token.
batch: batch-transform batch-offline batch-abaqus

clean-clone:
	./scripts/clean_clone_acceptance.sh

clean:
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	find . -name '*.o' -o -name '*.mod' -o -name '*.so' | xargs -r rm -f
	rm -rf build/ reproduce/

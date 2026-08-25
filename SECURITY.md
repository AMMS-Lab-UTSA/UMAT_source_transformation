# Security policy

## Scope

UMAT-OTI reads Fortran source, generates Fortran source, and invokes a Fortran
compiler. The security-relevant consequence is that **it runs a compiler over
input you supply**, and the code it generates is derived from that input.

Treat a UMAT source file the way you would treat any code you are about to
compile and execute. Transforming an untrusted source and running the result
executes that source's logic on your machine. The pipeline does not sandbox it.

## Supported versions

Fixes are applied to the `main` branch. There is no long-term support branch;
the version that receives fixes is the most recent release.

## Reporting a vulnerability

Report suspected vulnerabilities through GitHub's private advisory workflow:

- <https://github.com/AMMS-Lab-UTSA/UMAT_source_transformation/security/advisories/new>

Please do not open a public issue for a vulnerability until it has been
addressed. Include the input that triggers the problem and the command you ran;
a reproducible case is far more useful than a description.

Expect an acknowledgement within ten working days. This is academic research
software maintained alongside other duties, so please allow reasonable time for
a fix.

## Out of scope

- A UMAT that produces wrong numbers is a correctness bug, not a vulnerability.
  Open a normal issue, ideally with the contract and source that reproduce it.
- Crashes in `gfortran` itself belong upstream to GCC.
- Anything requiring an attacker to already be able to run code as you.

## Credentials

This repository contains no credentials, and `tools/audit_repository_standards.py`
runs a secret scan over every tracked file as part of CI. If you believe a
credential has been committed, report it privately using the link above rather
than opening an issue.

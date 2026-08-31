"""Advisory helpers that may propose, and may never decide.

Nothing in this package produces a number. A model here selects among things
that already exist -- which deck on disk belongs to which source, which of a
repository's files is the entry routine -- and a deterministic check then
either confirms the selection against the artefact or rejects it. The values
that reach the evidence are read by a parser from the file the selection
pointed at, never generated.

The distinction matters because everything else in this repository is built on
being able to say where a number came from. A model that proposed a material
constant would put an unreproducible step in the middle of that chain; one
that proposes a filename cannot, because the filename is checked and the
contents are read.

The whole package is optional. With no model reachable every caller falls back
to the deterministic path it already had, and the evidence is identical.
"""

from umat_oti.assist.local_model import (
    LocalModel, ModelUnavailable, model_from_environment,
)
from umat_oti.assist.proposals import Proposal, Verdict

__all__ = ["LocalModel", "ModelUnavailable", "model_from_environment",
           "Proposal", "Verdict"]

#: The proposers themselves are imported from their own modules rather than
#: re-exported here. ``umat_oti.assist.repair`` reaches into the transformer for
#: the predicates its invariance check is built on, and a package that pulled
#: that in on import would make the cost of ``import umat_oti.assist`` depend on
#: a proposer nobody asked for.

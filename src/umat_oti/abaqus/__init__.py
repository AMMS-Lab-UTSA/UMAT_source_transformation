"""Running a UMAT in Abaqus and checking what it computed.

The pieces are deliberately separate: a manifest says what a UMAT is made of,
a deck generator turns that into a single-element model, a runner executes it,
and a status classifier decides from Abaqus's own records whether the analysis
actually happened. Nothing here knows the name of any particular material.
"""

from umat_oti.abaqus.deck import generate_deck, total_increments
from umat_oti.abaqus.job_status import COMPLETED_MARKER, JobStatus, classify_job
from umat_oti.abaqus.manifest import (
    NEEDS_MATERIAL_DATA, LoadingSegment, VerificationManifest,
    reverse, simple_shear, uniaxial,
)
from umat_oti.abaqus.probe import (
    PROBE_SOURCE, instrument, parse_probe, probe_call,
)
from umat_oti.abaqus.runner import (
    JobResult, abaqus_command, extract_history, run_job,
)

__all__ = [
    "COMPLETED_MARKER", "JobResult", "JobStatus", "LoadingSegment",
    "NEEDS_MATERIAL_DATA", "VerificationManifest", "abaqus_command",
    "PROBE_SOURCE", "classify_job", "extract_history", "generate_deck",
    "instrument", "parse_probe", "probe_call", "reverse", "run_job",
    "simple_shear", "total_increments", "uniaxial",
]

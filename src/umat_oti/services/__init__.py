"""Pure services: the operations the pipeline performs, free of front ends.

The project owner's requirement, verbatim: *"The GUI must call reusable backend
services. It must not duplicate verification logic or execute large shell
commands assembled in UI callbacks."* This package is those services, and the
CLI and the GUI import the same names from here.

Each service returns a typed :class:`~umat_oti.services.results.ServiceResult`
rather than a dict of whatever fell out, because the moment a caller has to
decide what a missing key means, the decision has moved back into the caller
and the two front ends start disagreeing.

+---------------------------+------------------------------------------------+
| :class:`CorpusService`    | import, list, search, filter sources           |
| :class:`ManifestService`  | build and review a manifest for one source     |
| :class:`TransformationService` | transform, compile, report diagnostics    |
| :class:`ExperimentService`| formulation-aware decks, activation search     |
| :class:`AbaqusExecutionService` | submit/track/cancel through the job      |
|                           | manager -- it never runs Abaqus itself         |
| :class:`VerificationService` | the full ladder, six gates plus the seventh |
| :class:`RegressionService`| frozen fixtures against a baseline             |
| :class:`ResidualAssemblyService` | hand a verified fixture over          |
| :class:`ReportService`    | Markdown / HTML / JSON export                  |
+---------------------------+------------------------------------------------+

The three rules that hold across all of them: unknown is never verified; no
summary number hides a distinction; every claim carries the command or the file
it came from.
"""

from .corpus_service import CorpusListing, CorpusService, SourceSummary
from .execution_service import (
    DEFAULT_QUEUE, AbaqusExecutionService, RunTicket,
)
from .experiment_service import (
    ActivationSearch, ExperimentPlan, ExperimentService,
)
from .gates import (
    FALSE, GATES, GATE_MEANINGS, NOT_ESTABLISHED, RAW_ABSENT, RAW_FALSE,
    RAW_NO_BLOCK, RAW_NULL, RAW_TRUE, SEVENTH, TRUE, CensusDoesNotSum,
    GateReading, GateSet, census, read_gate, read_gates, read_seventh,
)
from .manifest_service import ManifestReview, ManifestService
from .regression_service import (
    AGREED, DID_NOT_RUN, DISAGREED, FixtureOutcome, RegressionReport,
    RegressionService,
)
from .report_service import FORMATS, RenderedReport, ReportService
from .residual_service import HandoffResult, ResidualAssemblyService
from .results import Problem, Provenance, ServiceResult, repo_commit
from .transformation import TransformationOptions, run_transformation
from .transformation_service import TransformationReport, TransformationService
from .verification_service import (
    CorpusSummary, LadderRung, VerificationService, VerificationVerdict,
)
from .workbench import (
    LoadingHistory, ProductOutcome, WorkbenchRequest, WorkbenchResult,
    analyse_source, run_workbench,
)

__all__ = [
    # envelope
    "ServiceResult", "Problem", "Provenance", "repo_commit",
    # gates
    "GATES", "SEVENTH", "GATE_MEANINGS", "TRUE", "FALSE", "NOT_ESTABLISHED",
    "RAW_TRUE", "RAW_FALSE", "RAW_NULL", "RAW_ABSENT", "RAW_NO_BLOCK",
    "GateReading", "GateSet", "read_gate", "read_gates", "read_seventh",
    "census", "CensusDoesNotSum",
    # services
    "CorpusService", "CorpusListing", "SourceSummary",
    "ManifestService", "ManifestReview",
    "TransformationService", "TransformationReport",
    "TransformationOptions", "run_transformation",
    "ExperimentService", "ExperimentPlan", "ActivationSearch",
    "AbaqusExecutionService", "RunTicket", "DEFAULT_QUEUE",
    "VerificationService", "VerificationVerdict", "LadderRung", "CorpusSummary",
    "RegressionService", "RegressionReport", "FixtureOutcome",
    "AGREED", "DISAGREED", "DID_NOT_RUN",
    "ResidualAssemblyService", "HandoffResult",
    "ReportService", "RenderedReport", "FORMATS",
    # workbench (pre-existing, re-exported so there is one import surface)
    "WorkbenchRequest", "WorkbenchResult", "ProductOutcome", "LoadingHistory",
    "analyse_source", "run_workbench",
]

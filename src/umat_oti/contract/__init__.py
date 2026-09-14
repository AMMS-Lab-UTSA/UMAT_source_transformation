"""The versioned data contract between this repository and Residual_Assembler.

One import, one version, one vocabulary. Everything two repositories need to
say to each other about a UMAT is defined here, so that neither has to read
the other's ad-hoc JSON keys and neither can rename one silently.

    >>> from umat_oti.contract import CONTRACT_VERSION, from_store_record
    >>> record = from_store_record(row)
    >>> record.evidence.derivatives_verified.is_true()

The five rules this contract exists to hold, each bought with debugging:

1. **Six gates, never one boolean.** Plus a seventh field that says why a
   false primal is still a verdict. See :mod:`.gates`.
2. **Three states, never two.** true / false / not-established. A missing key
   and a null key are both not-established, and neither is a pass. See
   :mod:`.tristate` -- the reader has no ``__bool__`` on purpose.
3. **Terminal states carry an owner.** EXTERNAL is somebody's published
   repository; INTERNAL is this project. A stage with no owner is refused,
   not defaulted. See :mod:`.terminal`.
4. **Identity is the cache path plus the source digest**, never a basename:
   23 basenames in the frozen corpus name more than one file. And a fixture
   carries the transform fingerprint it was cut at, so a consumer can refuse
   numbers produced by a transform that has since changed. See
   :mod:`.identity` and :mod:`.fixtures`.
5. **Provenance travels with every material property.** A value with no
   provenance is indistinguishable from an invented one. See :mod:`.record`.
"""
from __future__ import annotations

from .adapted import (adapt_v2_contract_versioned, kinematics_agree,
                      require_adapter_contract_compatible,
                      stamp_contract_version)
from .envelope import (CallEnvelope, EnvelopeError, FORBIDDEN_AS_A_VERDICT,
                       SUCCESS_FIELD, VERDICT_FIELD, verdict_of)
from .errors import CODES, CONTRACT_OWNER, ContractError, error_dict
from .frames import (COUNT_FIELDS, FrameError, FrameKey, HistoryCounts,
                     IDENTITY_FIELDS, IncrementKey, PointKey, check_counts,
                     count_history, frame_key, group_by_increment,
                     increment_key, point_key)
from .fixtures import (CURRENT_FIXTURES_ROOT, FIXTURE_SCHEMA,
                       IDENTITY_1X, IDENTITY_2X, fixture_generation,
                       require_five_field_identity,
                       FixtureFingerprintError, FixtureReference,
                       check_fingerprint, read_fixture_reference,
                       require_current)
from .gates import ALL_FIELDS, GATES, SEVENTH, EvidenceGates, read_gates
from .identity import IdentityError, UmatIdentity, refuse_basename_keying
from .record import (ContractRecord, DerivativeCapability, Formulation,
                     Interface, Kinematics, MaterialProperties, RecordError,
                     StoreAdaptation, TensorConvention, adapt_store_records,
                     from_store_record)
from .schema import (LockMismatch, SchemaViolation, compute_lock,
                     current_transform_generation, load_schema, validate,
                     verify_lock, write_lock)
from .terminal import (EXTERNAL_OWNER, INTERNAL_OWNER, PUBLISHED_OWNERS,
                       TerminalState, TerminalStateError, UntranslatedStage,
                       VERIFIED_OWNER, known_states, translate_stage,
                       vocabulary_gap)
from .tristate import (FALSE, NOT_ESTABLISHED, TRUE, Tri, TristateError,
                       all_true, read, read_path)
from .version import (CONTRACT_VERSION, SPEAKER, ContractVersionError,
                      contract_version_of, handshake, parse,
                      require_compatible)

__all__ = [
    "CONTRACT_VERSION", "SPEAKER", "ContractVersionError", "handshake",
    "parse", "require_compatible", "contract_version_of",
    "Tri", "TRUE", "FALSE", "NOT_ESTABLISHED", "TristateError", "read",
    "read_path", "all_true",
    "UmatIdentity", "IdentityError", "refuse_basename_keying",
    "TerminalState", "TerminalStateError", "translate_stage", "known_states",
    "EXTERNAL_OWNER", "INTERNAL_OWNER", "VERIFIED_OWNER",
    "GATES", "SEVENTH", "ALL_FIELDS", "EvidenceGates", "read_gates",
    "ContractRecord", "MaterialProperties", "Interface", "TensorConvention",
    "Kinematics", "Formulation", "DerivativeCapability", "RecordError",
    "from_store_record", "adapt_store_records", "StoreAdaptation",
    "FixtureReference", "FixtureFingerprintError", "check_fingerprint",
    "require_current", "read_fixture_reference", "FIXTURE_SCHEMA",
    "CURRENT_FIXTURES_ROOT",
    "ContractError", "CODES", "CONTRACT_OWNER", "error_dict",
    "CallEnvelope", "EnvelopeError", "verdict_of", "SUCCESS_FIELD",
    "VERDICT_FIELD", "FORBIDDEN_AS_A_VERDICT",
    "FrameKey", "PointKey", "IncrementKey", "frame_key", "point_key",
    "increment_key", "group_by_increment", "HistoryCounts", "count_history",
    "check_counts", "FrameError", "IDENTITY_FIELDS", "COUNT_FIELDS",
    "fixture_generation", "require_five_field_identity", "IDENTITY_1X",
    "IDENTITY_2X", "PUBLISHED_OWNERS", "vocabulary_gap", "UntranslatedStage",
    "adapt_v2_contract_versioned", "stamp_contract_version",
    "require_adapter_contract_compatible", "kinematics_agree",
    "load_schema", "validate", "SchemaViolation", "verify_lock",
    "current_transform_generation",
    "compute_lock", "write_lock", "LockMismatch",
]

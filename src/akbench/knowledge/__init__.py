"""Knowledge replay: the memory experiment of plan section 17.

Three arms measure one thing — what learned knowledge contributes:

- **learning**: the agent works the learning tasks with knowledge write and
  read active, producing the knowledge a later arm may use;
- **replay**: a new session, a clean workspace, access to the knowledge of
  that learning session, and no history of the session that wrote it;
- **fresh control**: a new session, a clean workspace, and no knowledge.

Replay and fresh must be identical in every other respect — the same
repository snapshot, task version, tests, evaluator, agent, parameters and
limits — so the plan compares the two fingerprints and refuses a difference
rather than measuring an uncontrolled change.

Two things are never assumed: that the end of a session means the knowledge
base is ready (writing and indexing are asynchronous), and that retrieval
means the knowledge was used. Both are separate measurements with separate
statuses here.
"""

from akbench.knowledge.fingerprint import (
    Fingerprint,
    fingerprint,
    invariant_differences,
)
from akbench.knowledge.modes import KnowledgeArm, KnowledgeMode, TransferScenario
from akbench.knowledge.readiness import (
    KbReadiness,
    ReadinessStatus,
    ReplayGate,
    build_readiness_gate,
)
from akbench.knowledge.sessions import LearningSession, SessionTask

__all__ = [
    "Fingerprint",
    "KbReadiness",
    "KnowledgeArm",
    "KnowledgeMode",
    "LearningSession",
    "ReadinessStatus",
    "ReplayGate",
    "SessionTask",
    "TransferScenario",
    "build_readiness_gate",
    "fingerprint",
    "invariant_differences",
]

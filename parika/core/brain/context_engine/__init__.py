"""
PARIKA Brain - Context Engine (private subpackage)

Implements Context Engineering as a private subpackage owned by
`Brain`, following the exact precedent already proven by
`planner/model_selection/`: a Core component grows substantial new
capability without becoming a new Core component and without changing
any other component's public API.

Imported only by `parika.core.brain.brain`. See
docs/architecture/Intelligence_Foundation_Design.md section 7 for the
full rationale, including why this lives here rather than inside
`ContextManager` (which must never "interpret context metadata").
"""

from .budget import TokenBudget, load_context_engine_config
from .compaction import CompactionResult, compact
from .message import ContextMessage
from .retrieval_ordering import ContextBundle, assemble_context
from .token_estimator import HeuristicTokenEstimator, TokenEstimator

__all__ = [
    "CompactionResult",
    "ContextBundle",
    "ContextMessage",
    "HeuristicTokenEstimator",
    "TokenBudget",
    "TokenEstimator",
    "assemble_context",
    "compact",
    "load_context_engine_config",
]

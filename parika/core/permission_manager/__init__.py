"""
PARIKA Permission Manager package.

Provides the PermissionManager component and its primary public
interfaces, plus the Workspace Permission Manager extension (see
`workspace_permission_manager.py` and
`docs/architecture/Core_Component_Responsibilities.md` section 25).
"""

from .decision import PermissionDecision
from .events import (
    PermissionDeniedEvent,
    PermissionGrantedEvent,
    PermissionRevokedEvent,
)
from .exceptions import (
    PermissionAlreadyGrantedError,
    PermissionManagerError,
    PermissionNotFoundError,
)
from .permission_grant import PermissionGrant
from .permission_manager import PermissionManager
from .workspace_events import (
    WorkspacePermissionEvaluatedEvent,
    WorkspaceTrustedEvent,
)
from .workspace_operation import WorkspaceOperation
from .workspace_permission_decision import WorkspacePermissionDecision
from .workspace_permission_manager import WorkspacePermissionManager
from .workspace_permission_prompt import WorkspacePermissionPrompt
from .workspace_permission_scope import WorkspacePermissionScope
from .workspace_trust_store import RuntimeTrustWriter

__all__ = [
    "PermissionAlreadyGrantedError",
    "PermissionDecision",
    "PermissionDeniedEvent",
    "PermissionGrant",
    "PermissionGrantedEvent",
    "PermissionManager",
    "PermissionManagerError",
    "PermissionNotFoundError",
    "PermissionRevokedEvent",
    "RuntimeTrustWriter",
    "WorkspaceOperation",
    "WorkspacePermissionDecision",
    "WorkspacePermissionEvaluatedEvent",
    "WorkspacePermissionManager",
    "WorkspacePermissionPrompt",
    "WorkspacePermissionScope",
    "WorkspaceTrustedEvent",
]

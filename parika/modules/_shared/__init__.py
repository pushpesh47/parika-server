"""
PARIKA Modules - Shared Utilities

Plain, stateless utility functions shared across multiple Modules.
Nothing here is a Module in the `ModuleManager` sense: no manifest, no
driver, no lifecycle, no registered Capability. Importing from this
package is the same "engine imports a pure library function" relationship
`FilesystemToolDriver` already has with `parika.tools.filesystem
.operations`, not Module-to-Module communication -- see
docs/development/Module_Guide.md section
5.6 for the full rationale.
"""

from __future__ import annotations

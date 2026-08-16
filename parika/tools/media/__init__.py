"""
PARIKA Media Tool

Provider-independent domain model, resolution, security, and
`ToolDriver` implementation backing the `media.*` Capabilities. See
`parika/modules/media/module_driver.py` for the registration
lifecycle, and `docs/architecture/adr/0004-media-capability.md` for
the architectural decision this package implements: PARIKA resolves
and controls media; a separate Web Client performs actual playback.
"""

from __future__ import annotations

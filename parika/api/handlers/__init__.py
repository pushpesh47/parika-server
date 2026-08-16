"""
PARIKA API - Handlers

Orchestration/translation-only functions registered as `Route`
handlers on the existing `Router` Core component (see
`docs/guides/Running.md` section 12, and the "Exposing a Capability
Through the API Layer" checklist in
`docs/development/Integration_Checklist.md`).

**Rule:** a handler in this package may only translate an
`ApiRequest`-shaped dataclass into a call an existing Core
manager/driver method already accepts, translate the result back into
a plain Python value, and orchestrate ordering of *already-existing*
read-only calls when one HTTP endpoint's contract genuinely needs more
than one Core call. A handler must never implement a new decision,
validation policy, or state transition that does not already exist in
some Core component. A useful review question for any line added
here: "does this line call an existing Core public method, or does it
decide something?" Only the former is permitted.
"""

from __future__ import annotations

"""
PARIKA Core - ProviderManager Component

Defines the normalized, provider-independent hardware/resource
requirements a ProviderModel may optionally declare.

ModelResourceRequirements exists so the Model Selection Framework's
resource-validation filtering step (see `parika/core/planner
/model_selection/filtering.py`) can reject a candidate whose declared
hardware needs are known to exceed what is currently available,
*without* Planner or ProviderManager ever needing to know about a
specific model, provider, or hardware vendor.

Every field defaults to `None`/`False`, meaning "this Provider did not
report a requirement for this dimension" - never "this model requires
nothing". Consumers only ever reject a candidate when a requirement is
both declared *and* known to be unmet against a supplied resource
snapshot; an unreported requirement, or the absence of a snapshot to
validate against, is always treated as "cannot be determined, so do
not reject" - exactly the same graceful-degradation contract every
other optional `ProviderModel` signal (e.g. `metadata`) already
follows in this framework.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelResourceRequirements:
    """
    Immutable, optional hardware/resource requirements for a
    ProviderModel.

    Attributes:
        min_ram_bytes:
            Minimum system RAM required to execute this model. `None`
            when unreported.

        min_vram_bytes:
            Minimum GPU VRAM required to execute this model. `None`
            when unreported.

        min_disk_bytes:
            Minimum free disk space required (e.g. to load model
            weights). `None` when unreported.

        requires_gpu:
            Whether a GPU is required at all. `False` (the safe
            default) never implies a GPU would be unhelpful - only
            that none was declared as strictly required.

        min_gpu_count:
            Minimum number of GPUs required. `None` when unreported.
    """

    min_ram_bytes: int | None = None
    min_vram_bytes: int | None = None
    min_disk_bytes: int | None = None
    requires_gpu: bool = False
    min_gpu_count: int | None = None

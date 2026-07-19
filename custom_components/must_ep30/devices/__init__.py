"""Device profile registry for the MUST EP30/EP3000 integration."""

from __future__ import annotations

from ..const import PROFILE_EP30_PRO, PROFILE_EP3000_PLUS
from .ep30_pro import EP30_PRO_PROFILE
from .ep3000_plus import EP3000_PLUS_PROFILE
from .models import DeviceProfile

PROFILE_REGISTRY: dict[str, DeviceProfile] = {
    PROFILE_EP30_PRO: EP30_PRO_PROFILE,
    PROFILE_EP3000_PLUS: EP3000_PLUS_PROFILE,
}


def get_profile(key: str) -> DeviceProfile:
    """Look up a device profile by its key, raising KeyError if unknown."""
    return PROFILE_REGISTRY[key]


__all__ = ["PROFILE_REGISTRY", "DeviceProfile", "get_profile"]

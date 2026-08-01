"""Back-compat shim.

The capability vocabulary is no longer a fixed enum here — it is registered by
each department into :data:`dojocore.capability.capabilities`, so a second
department can add its own without editing this package. See
``seoagents/department.py`` for SEO's declaration.
"""
from __future__ import annotations

from dojocore.capability import Capability, capabilities


def all_capabilities() -> list[Capability]:
    """Every capability registered in this process, across departments."""
    return capabilities.list()


def seo_capabilities() -> list[Capability]:
    import seoagents.department  # noqa: F401 - registers on import
    return capabilities.list(dept="seo")


__all__ = ["Capability", "all_capabilities", "capabilities", "seo_capabilities"]

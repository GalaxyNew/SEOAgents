"""Plugin layer — capabilities, tool catalog, and (later) pluggable providers."""
from seoagents.plugins.capabilities import Capability
from seoagents.plugins.catalog_loader import CatalogEntry, DeployMode, load_catalog

__all__ = ["Capability", "CatalogEntry", "DeployMode", "load_catalog"]

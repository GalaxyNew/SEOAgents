"""Back-compat shim — logging moved to :mod:`dojocore.logging` (framework layer)."""
from dojocore.logging import *
from dojocore.logging import LOGGER, configure_logging  # noqa: F401

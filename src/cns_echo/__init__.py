"""CNS Echo — receives signals, echoes back with analysis."""

__version__ = "0.1.0"

from .echo_space import EchoSpace, Ring  # noqa: F401

__all__ = ["EchoSpace", "Ring", "__version__"]

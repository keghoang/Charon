"""
Galt Script Manager

Pipeline usage:
    import galt
    galt.Go()
    
    # Or with custom paths:
    galt.Go(script_paths=[r"\path\to\scripts"])
"""

__version__ = "1.0.0"
__author__ = "Alex Dingfelder"


def Go(*args, **kwargs):
    """Launch helper that defers the heavy Qt import until required."""
    from .main import launch

    return launch(*args, **kwargs)

r"""
Charon workflow panel.

Pipeline usage:
    import charon
    charon.Go()
    
    # Or with custom paths:
    charon.Go(global_path=r"\path\to\workflows")
"""

__version__ = "1.3.0"
__author__ = "Kien"


def Go(*args, **kwargs):
    """Launch helper that defers the heavy Qt import until required."""
    from .main import launch

    return launch(*args, **kwargs)

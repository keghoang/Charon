"""Entry point for running `python -m charon`."""

from .main import launch


def _run() -> None:
    launch()


if __name__ == "__main__":
    _run()

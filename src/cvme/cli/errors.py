"""Turning expected failures into a message and an exit code.

Lives apart from ``app`` so sub-commands can use it without importing the
application they are registered on.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, cast

import typer
from rich.console import Console

from cvme.errors import CvmeError

err_console = Console(stderr=True)


def handled[F: Callable[..., Any]](command: F) -> F:
    """Report expected failures without a traceback.

    Applied per command rather than around ``app()`` so the behaviour holds
    however the CLI is entered, including from tests and sub-typers.
    """

    @functools.wraps(command)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return command(*args, **kwargs)
        except CvmeError as exc:
            err_console.print(f"[red]error:[/red] {exc}")
            raise typer.Exit(exc.exit_code) from exc

    # functools.wraps preserves the signature typer introspects, but the
    # wrapper's own type is not F.
    return cast(F, wrapper)

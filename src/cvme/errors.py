"""Error types that the CLI knows how to report without a traceback."""

from __future__ import annotations


class CvmeError(Exception):
    """Base class for expected failures.

    Anything raised as a ``CvmeError`` is a problem with the user's input or
    environment rather than a bug, so the CLI prints it plainly and exits
    non-zero instead of showing a traceback.
    """

    exit_code = 1


class ParseError(CvmeError):
    """A source document does not conform to the grammar."""

    def __init__(
        self, message: str, *, path: str | None = None, line: int | None = None
    ):
        self.path = path
        self.line = line
        location = ""
        if path is not None:
            location = path if line is None else f"{path}:{line}"
        super().__init__(f"{location}: {message}" if location else message)


class ConfigError(CvmeError):
    """Configuration is missing or invalid."""


class RenderError(CvmeError):
    """The document could not be typeset."""


class FitError(RenderError):
    """The document does not fit the configured page budget."""

    exit_code = 2


class ConvertError(CvmeError):
    """A PDF could not be converted to the markdown grammar."""

    exit_code = 6


class VerificationFailed(CvmeError):
    """A document made a claim it cannot support, or wrote like a machine."""

    exit_code = 3


class HuntError(CvmeError):
    """A hunt directory or its tracking record is missing or inconsistent."""

    exit_code = 7

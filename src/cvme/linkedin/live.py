"""Getting the live profile out of LinkedIn, by the routes that exist.

Ordered by how little work they cost you, not by how much they return:

=======================  ===========  ==============================
Source                   Effort       Reports
=======================  ===========  ==============================
Profile PDF              one click    headline, About, roles, degrees
Data export (CSV/ZIP)    a few mins   all of it, structured
=======================  ===========  ==============================

The PDF is *More > Save to PDF* on your own profile: it downloads immediately,
and cvme already knows how to read a PDF resume, so the whole path is the
existing ``convert`` pipeline pointed at a different document.

What is deliberately absent is fetching ``linkedin.com/in/...`` over HTTP. It
is not a technical gap. LinkedIn's user agreement forbids automated access,
and *hiQ Labs v. LinkedIn* ended in 2022 with a $500,000 judgment against hiQ
for breach of that agreement and a permanent injunction to stop and delete
what it had taken -- the widely-quoted ruling that scraping public pages is
not a *CFAA* crime left the contract claim untouched, and LinkedIn won it.
The same judgement is already recorded for job capture in ``jobs/sources.py``.

Every source says which parts of a profile it actually reports. A profile PDF
lists "Top Skills" rather than all of them, and a partial export may hold one
table; auditing an uncovered part would report the whole of it as missing,
which is a bug about the source dressed up as drift in your profile.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from cvme.errors import CvmeError
from cvme.linkedin.model import Profile


class SourceError(CvmeError):
    exit_code = 10


@dataclass
class Source:
    """A profile read from somewhere, and what that somewhere can vouch for."""

    profile: Profile
    #: Which of ``Profile.PARTS`` this source reports in full.
    covers: set[str] = field(default_factory=set)
    #: How to name the source in output.
    label: str = ""

    @property
    def unchecked(self) -> list[str]:
        return [part for part in Profile.PARTS if part not in self.covers]


def read(path: Path) -> Source:
    """Read a profile from whichever kind of file this is."""
    if not path.exists():
        raise SourceError(f"{path}: no such file or directory.\n{_HOW}")
    suffix = path.suffix.casefold()
    if suffix == ".pdf":
        from cvme.linkedin import pdfprofile

        return pdfprofile.read(path)
    if path.is_dir() or zipfile.is_zipfile(path):
        from cvme.linkedin import export

        return export.read(path)
    raise SourceError(
        f"{path}: cvme does not know how to read this as a profile.\n{_HOW}"
    )


_HOW = """\
  Two ways to get your profile, neither of which needs an API:

    1. Your profile > More > Save to PDF          (one click, immediate)
       cvme linkedin check ~/Downloads/Profile.pdf

    2. Settings & Privacy > Data Privacy > Get a copy of your data
       cvme linkedin check ~/Downloads/Basic_LinkedInDataExport.zip

  The PDF is quicker; the export is complete, and is the one that can vouch
  for your skills list."""

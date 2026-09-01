"""Proof-of-concept for the cvme rendering engine.

Validates the load-bearing assumptions of docs/implementation-plan.md §1.1:

* typst-py compiles from an in-memory ``dict[str, bytes]`` virtual filesystem,
  so no temp directory is needed;
* the template can read structured data injected as JSON;
* right-aligned text, bold/italic runs, a size hierarchy and section rules are
  all expressible — the things plain markdown cannot do;
* inline markdown can be handed through via ``eval(mode: "markup")``.

Run with::

    uv run --with typst python spikes/typst_spike.py

Writes spike_out.pdf and spike_out_1.png next to the CWD.
"""

from __future__ import annotations

import json
from typing import Any

import typst

DATA: dict[str, Any] = {
    "name": "Jeff Brennan",
    "contact": [
        "jeffbrennan10@gmail.com",
        "jeffbrennan.dev",
        "github.com/jeffbrennan",
        "Boston, MA",
    ],
    "sections": [
        {
            "title": "Experience",
            "entries": [
                {
                    "org": "Acme Data",
                    "role": "Senior Data Engineer",
                    "loc": "Boston, MA",
                    "dates": "Jan 2023 - Present",
                    "bullets": [
                        "Rebuilt the ingestion path in *PySpark*, cutting the "
                        "nightly window from 6h to 40m.",
                        "Consolidated 40 job clusters onto shared pools.",
                    ],
                }
            ],
        },
        {
            "title": "Skills",
            "entries": [
                {
                    "org": "",
                    "role": "",
                    "loc": "",
                    "dates": "",
                    "bullets": [
                        "*Languages:* Python, SQL, Scala",
                        "*Platforms:* Databricks, Snowflake, dbt",
                    ],
                }
            ],
        },
    ],
}

TEMPLATE = r"""
#let data = json("data.json")
#set page(paper: "us-letter", margin: (x: 0.6in, y: 0.5in))
#set text(font: ("Libertinus Serif", "DejaVu Serif"), size: 10.5pt)
#set par(justify: false, leading: 0.55em)

#align(center)[
  #text(size: 20pt, weight: "bold", tracking: 0.5pt)[#data.name] \
  #v(2pt)
  #text(size: 9.5pt)[#data.contact.join("  |  ")]
]
#v(4pt)

#let section(title, body) = {
  block(above: 10pt, below: 4pt)[
    #text(size: 11pt, weight: "bold", tracking: 1pt)[#upper(title)]
    #v(-4pt)
    #line(length: 100%, stroke: 0.6pt)
  ]
  body
}

#for s in data.sections {
  section(s.title, {
    for e in s.entries {
      if e.org != "" {
        // The load-bearing trick: a two-column grid puts the dates hard right
        // on the same baseline as the company.
        grid(columns: (1fr, auto), align: (left, right),
          text(weight: "bold", size: 11pt)[#e.org],
          text(weight: "bold", size: 10pt)[#e.dates],
        )
        grid(columns: (1fr, auto), align: (left, right),
          text(style: "italic")[#e.role],
          text(style: "italic", size: 9.5pt)[#e.loc],
        )
        v(1pt)
      }
      for b in e.bullets {
        block(inset: (left: 10pt), above: 2pt, below: 2pt)[- #eval(b, mode: "markup")]
      }
    }
  })
}
"""


def main() -> None:
    files: dict[str, bytes] = {
        "main.typ": TEMPLATE.encode(),
        "data.json": json.dumps(DATA).encode(),
    }
    typst.compile(files, output="spike_out.pdf", root=".")
    typst.compile(files, output="spike_out_{n}.png", root=".", format="png", ppi=110)
    print("wrote spike_out.pdf and spike_out_1.png")


if __name__ == "__main__":
    main()

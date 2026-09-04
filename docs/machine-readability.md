# Machine readability

A resume is parsed by software before a person reads it. These are the choices
cvme makes about that, and the ones left to you.

## What the renderer already does

**Bullets are a real `•` (U+2022).** This one is worth dwelling on, because the
obvious answers are both wrong. Your current resume uses a Wingdings glyph,
which extracts as a literal `§` — junk in the middle of every bullet. The first
fix was to *draw* the marker as a filled box, which looks right and extracts as
nothing at all; but then a wrapped line and a new bullet are indistinguishable
in extracted text, so a parser cannot tell where one point ends and the next
begins. A real bullet character is the only option that both prints correctly
and survives extraction. `--set marker_glyph=""` restores the drawn box if you
prefer the square.

**Sections are real headings.** They emit `/H2` tags into the PDF's structure
tree, with entries as `/H3` and bullet lists as `/L`. Bold text in a `/Div`
gives a parser nothing; a tagged heading gives it an outline. Typst tags PDFs by
default, but only for elements that are semantically headings — styling text
bold does not make it one.

**Reading order matches the document.** Right-aligned dates are set with a
two-column grid, which could easily scramble extraction; a test asserts that
each date still extracts on the same line as its role.

**Metadata is populated.** `/Title`, `/Author` and `/Lang` are set, and
`keywords` in frontmatter reaches the PDF. Many parsers read these first.

**The single-column layout is deliberate.** Multi-column resumes and sidebars
are the most common cause of scrambled extraction. cvme does not offer one.

## Checking it, rather than assuming it

```bash
cvme ats resume            # render, read the PDF back, report
cvme ats out/resume.pdf    # check a PDF from anywhere
```

Everything above is a claim about how the output extracts. `cvme ats` is how
that claim is tested: it renders the document, runs the converter over the
result, and compares the structure a machine recovers against the structure you
wrote. A section that goes missing, a bullet list that reads as one paragraph,
a date that no longer sits with its role -- each is an error rather than a
description.

| Rule | Severity | What it catches |
|---|---|---|
| `ats:structure` | error | The recovered sections, entries or bullet counts differ from the source. |
| `ats:symbol-font` | error | A glyph from Wingdings or similar, which extracts as junk. |
| `ats:name`, `ats:email` | error | No name or address recoverable from the letterhead. |
| `ats:dates` | warning | An entry's dates do not read as `Mon YYYY - Mon YYYY`. |
| `ats:section-name` | warning | A section name parsers do not map to a field. |
| `ats:bullets` | warning | No bullet list survives extraction. |
| `ats:skill-parenthetical` | warning | A proficiency in parentheses, per the trade-off below. |
| `ats:title`, `ats:author`, `ats:keywords` | warning | Metadata a parser reads first is empty. |
| `ats:pages` | warning | More pages than the budget. |

Warnings are judgement calls and errors are not: an error means the document
you wrote and the document a parser reads are different documents.

## Options you can turn on

```bash
cvme render resume.md --pdf-standard ua-1     # accessibility-tagged
cvme render resume.md --pdf-standard a-2b     # archival
```

`ua-1` enforces the tagging requirements of PDF/UA. Worth using if you want the
document to hold up in a screen reader, though the default output is already
tagged.

## Suggestions for the source document

These are about content, not rendering, and are yours to take or leave.

- **Spell out dates as `Mon YYYY – Mon YYYY`.** Already the case. Numeric
  formats (`07/23`) are ambiguous across locales, and bare years lose duration.
- **Put the role before the organisation.** Already the case, via ` @ `.
  Parsers key on the role.
- **Name the technology in the bullet that used it,** not only in Skills.
  Keyword matching is usually scoped to a role's date range, so a skill that
  appears only in a list has no dates attached to it.
- **Keep the Skills section as labelled lines** (`**Languages**: …`). The label
  gives a parser a category; a flat comma-separated blob does not.
- **Avoid parentheses for proficiency** (`Python (advanced)`) if you care about
  exact keyword matching — some parsers keep the parenthetical as part of the
  token. `Python — advanced` or a separate proficiency column is safer. This is
  a real trade-off against how it reads to a person, and worth deciding
  deliberately rather than by default.
- **One claim per bullet.** Bullets that run to three lines tend to get
  truncated in preview panes.

## What is deliberately not done

- **No em dashes**, anywhere, by policy — that carries into the generated-prose
  rules later.
- **No icons for contact details.** A glyph where an email address should be
  extracts as nothing, or as junk.
- **No tables for layout.** The one grid in the template spans a single line
  and is tested for extraction order.

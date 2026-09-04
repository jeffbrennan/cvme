// Shared by every template.
//
// All vertical spacing in these templates is explicit and non-weak. Weak
// spacing collapses against adjacent block spacing, which would make the
// rhythm depend on whatever happens to precede each element; being explicit is
// what lets the geometry tests hold a tolerance.

#let pt(x) = x * 1pt

/// Evaluate a markup string from the IR. Every string field in document.json
/// holds Typst markup, escaped during parsing.
#let markup(body) = eval(body, mode: "markup")

/// Page, text and paragraph rules common to all document types.
#let setup(s) = body => {
  set page(paper: s.paper, margin: (x: pt(s.margin_x), y: pt(s.margin_y)))
  set text(
    font: s.body_font, size: pt(s.body_size), fill: rgb(s.ink),
    lang: s.lang, hyphenate: false,
  )
  set par(justify: false, leading: pt(s.leading), spacing: pt(s.leading))
  show link: underline
  // The body is wrapped in a box, which is inline and so carries no block
  // spacing of its own. Returning `it.body` bare leaves the heading's own
  // block spacing in place, and forcing `block(above: 0pt, below: 0pt)`
  // overshoots by suppressing the surrounding paragraph spacing too.
  set heading(numbering: none)
  show heading: it => box(width: 100%, it.body)
  body
}

/// Name at the left margin, contact details hard against the right, on one
/// line. Shared so a resume and its cover letter carry the same letterhead.
///
/// The name is a level-1 heading: it is the document's title, a tagged PDF
/// wants exactly one, and PDF/UA-1 refuses a document whose first heading is
/// deeper than that. It is not outlined, so no bookmark appears for it.
#let letterhead(doc, s) = grid(
  columns: (1fr, auto), align: (left + bottom, right + bottom),
  heading(level: 1, outlined: false,
    text(font: s.name_font, weight: s.name_weight, size: pt(s.name_size),
      markup(doc.name))),
  text(size: pt(s.contact_size))[
    #doc.contact.map(c => if c.url == none { markup(c.text) } else {
      link(c.url)[#markup(c.text)]
    }).join(s.contact_sep)
  ],
)

/// A left/right line: content at the left margin, content hard against the
/// right. This is the one thing plain markdown cannot express, and the reason
/// the grammar has a pipe.
///
/// `lhs`/`rhs` rather than `left`/`right`: those names are Typst's alignment
/// builtins, and shadowing them breaks the `align` argument below.
#let split_line(lhs, rhs, right_size: none, weight: "regular") = grid(
  columns: (1fr, auto), align: (left + bottom, right + bottom),
  text(weight: weight)[#markup(lhs)],
  if rhs != "" { text(weight: "bold", size: pt(right_size))[#markup(rhs)] },
)

/// Render a run of IR blocks: paragraphs, bullet lists, page breaks.
#let blocks(items, paragraph_gap: none) = {
  for (i, b) in items.enumerate() {
    if i > 0 and paragraph_gap != none { v(pt(paragraph_gap), weak: false) }
    if b.kind == "paragraph" {
      markup(b.text)
    } else if b.kind == "bullets" {
      list(..b.items.map(it => {
        markup(it.text)
        if it.children.len() > 0 { list(..it.children.map(c => markup(c.text))) }
      }))
    } else if b.kind == "pagebreak" {
      pagebreak()
    }
  }
}

/// Split a multi-line frontmatter value into rendered lines.
#let lines(value) = value.split("\n").map(markup).join(linebreak())

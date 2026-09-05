// Shared by every template.
//
// All vertical spacing in these templates is explicit and non-weak. Weak
// spacing collapses against adjacent block spacing, which would make the
// rhythm depend on whatever happens to precede each element; being explicit is
// what lets the geometry tests hold a tolerance.

#let pt(x) = x * 1pt

/// Resolve a colour that may be unset. The style schema spells "unset" as an
/// empty string, and every colour in it falls back along a chain ending at
/// `ink`, so the caller passes the chain and gets the first value set.
#let ink(..chain) = {
  let set_values = chain.pos().filter(c => c != "")
  rgb(if set_values.len() > 0 { set_values.first() } else { "#000000" })
}

/// Evaluate a markup string from the IR. Every string field in document.json
/// holds Typst markup, escaped during parsing.
#let markup(body) = eval(body, mode: "markup")

/// A horizontal rule the width of the text block. Zero weight draws nothing,
/// which is how a preset turns the separator off without a second flag.
#let rule(weight, color, gap: 0.0) = if weight > 0 {
  v(pt(gap), weak: false)
  line(length: 100%, stroke: pt(weight) + color)
}

/// Page, text and paragraph rules common to all document types.
#let setup(s) = body => {
  set page(paper: s.paper, margin: (x: pt(s.margin_x), y: pt(s.margin_y)))
  set text(
    font: s.body_font, size: pt(s.body_size), fill: ink(s.ink),
    lang: s.lang, hyphenate: false,
  )
  set par(justify: false, leading: pt(s.leading), spacing: pt(s.leading))
  show strong: it => text(weight: s.strong_weight, fill: ink(s.strong_color, s.ink), it.body)
  show link: it => {
    let styled = text(fill: ink(s.link_color, s.ink), it)
    if s.link_underline { underline(styled) } else { styled }
  }
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
#let letterhead(doc, s) = {
  grid(
    columns: (1fr, auto), align: (left + bottom, right + bottom),
    heading(level: 1, outlined: false,
      text(font: s.name_font, weight: s.name_weight, size: pt(s.name_size),
        tracking: pt(s.name_tracking), fill: ink(s.name_color, s.ink),
        markup(doc.name))),
    text(size: pt(s.contact_size), fill: ink(s.contact_color, s.muted, s.ink))[
      #doc.contact.map(c => if c.url == none { markup(c.text) } else {
        link(c.url)[#markup(c.text)]
      }).join(s.contact_sep)
    ],
  )
  rule(s.header_rule, ink(s.header_rule_color, s.accent, s.ink), gap: s.header_rule_gap)
}

/// A left/right line: content at the left margin, content hard against the
/// right. This is the one thing plain markdown cannot express, and the reason
/// the grammar has a pipe.
///
/// Both sides are content, not markup strings: the caller composes them, which
/// is what lets a role and its organisation carry different weights and
/// colours rather than one hard-coded `#strong` around the first half.
///
/// `lhs`/`rhs` rather than `left`/`right`: those names are Typst's alignment
/// builtins, and shadowing them breaks the `align` argument below.
#let split_line(lhs, rhs) = grid(
  columns: (1fr, auto), align: (left + bottom, right + bottom), lhs, rhs,
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

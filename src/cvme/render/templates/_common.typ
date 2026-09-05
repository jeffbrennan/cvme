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
    let styled = text(fill: ink(s.link_color, s.accent, s.ink), it)
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
        tracking: pt(s.name_tracking), fill: ink(s.name_color, s.accent, s.ink),
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

/// Hold a paragraph to `width`, optionally evening out the lines it wraps to.
///
/// Blocks, not boxes. A box is inline, so a two-line-tall box becomes one tall
/// inline object on a line of its own and picks up that line's leading, which
/// makes the item taller than the text it holds. A block carries no such line,
/// and with its own spacing zeroed it occupies exactly the height the wrapped
/// text does.
///
/// With `balance` off -- the default -- the width is simply applied and Typst
/// fills greedily: the first line runs the full measure and the rest of the
/// sentence follows on the next. That is what a resume bullet wants when the
/// measure has been chosen to stop short of something, because the first line
/// then reaches exactly the edge it was cut to.
///
/// With `balance` on, the paragraph keeps the line count it already has and is
/// handed the narrowest width that still achieves it -- the trick CSS spells
/// `text-wrap: balance`. Height is unchanged by construction, so it is free
/// under the fit ladder, but it buys evenness at the cost of leaving the first
/// line short of the measure.
#let balanced(body, width, balance: false) = context {
  let fit(w, content) = block(width: w, above: 0pt, below: 0pt, content)
  if not balance { return fit(width, body) }
  let target = measure(fit(width, body)).height
  let single = measure(fit(width, [x])).height
  if target <= single * 1.5 { return fit(width, body) }
  // Seven halvings resolve a 500pt line to under a character's width, which is
  // finer than the breaker can act on.
  let lo = width / 4
  let hi = width
  for _ in range(7) {
    let mid = (lo + hi) / 2
    if measure(fit(mid, body)).height <= target { hi = mid } else { lo = mid }
  }
  fit(hi, body)
}

/// Render a run of IR blocks: paragraphs, bullet lists, page breaks.
///
/// `balance_width` is the width available to a list item's own text, with the
/// marker and its indents already taken off. Given one, wrapped bullets are
/// balanced; left unset, line breaking is whatever Typst does by default,
/// which is what a cover letter wants.
#let blocks(
  items, paragraph_gap: none,
  text_width: none, bullet_width: none, nested_indent: 0pt, balance: false,
) = {
  let wrap(body, depth) = if bullet_width == none {
    body
  } else {
    // A nested item sits one marker column further in than its parent, so it
    // has that much less room to work within.
    balanced(body, bullet_width - depth * nested_indent, balance: balance)
  }
  for (i, b) in items.enumerate() {
    if i > 0 and paragraph_gap != none { v(pt(paragraph_gap), weak: false) }
    if b.kind == "paragraph" {
      if text_width == none {
        markup(b.text)
      } else {
        balanced(markup(b.text), text_width, balance: balance)
      }
    } else if b.kind == "bullets" {
      list(..b.items.map(it => {
        wrap(markup(it.text), 0)
        if it.children.len() > 0 {
          list(..it.children.map(c => wrap(markup(c.text), 1)))
        }
      }))
    } else if b.kind == "pagebreak" {
      pagebreak()
    }
  }
}

/// Split a multi-line frontmatter value into rendered lines.
#let lines(value) = value.split("\n").map(markup).join(linebreak())

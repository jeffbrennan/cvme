// Resume template.
//
// Reads two JSON files from the virtual filesystem the engine builds:
//   document.json  the parsed document (strings hold Typst markup)
//   style.json     resolved style, all lengths as plain numbers in points

#import "_common.typ": blocks, ink, letterhead, markup, pt, rule, setup, split_line

#let doc = json("document.json")
#let s = json("style.json")

#set document(title: doc.title, author: doc.name_plain, keywords: doc.keywords)
#show: setup(s)

// A real U+2022 rather than a drawn box: the marker has to survive text
// extraction, or a parser cannot tell a new bullet from a wrapped line. Set
// marker_glyph to "" to draw a square instead, which looks closer to the
// reference but leaves no character behind.
// A tight list spaces its items by the paragraph leading. `bullet_gap` adds to
// that, which is the only way to loosen a run of bullets without also opening
// up the lines inside each one.
#set list(
  tight: s.bullet_gap <= 0,
  spacing: if s.bullet_gap > 0 { pt(s.leading + s.bullet_gap) } else { auto },
  marker: if s.marker_glyph == "" {
    box(width: pt(s.marker_size), height: pt(s.marker_size), fill: ink(s.ink),
        baseline: pt(s.marker_baseline))
  } else {
    text(size: pt(s.marker_size), fill: ink(s.ink), baseline: pt(s.marker_baseline))[
      #s.marker_glyph
    ]
  },
  indent: pt(s.marker_indent),
  body-indent: pt(s.body_indent),
)

/// The right-hand side of an entry line: dates, in their own size and weight.
#let dates(value) = if value != "" {
  text(weight: s.date_weight, size: pt(s.date_size),
    fill: ink(s.date_color, s.muted, s.ink))[#markup(value)]
}

/// Every date on the page, so the width of the column they occupy can be
/// measured rather than guessed.
/// Parenthesised because a `#let` in markup mode ends at the newline once its
/// expression is complete: without these, `doc.sections` is the whole binding
/// and the chained calls below it are read as markup.
#let date_values = (
  doc.sections
    .map(sec => sec.entries
      .map(e => (e.head.right, if e.sub != none { e.sub.right } else { "" }))
      .flatten())
    .flatten()
    .filter(v => v != "")
)

#letterhead(doc, s)
#v(pt(s.header_gap), weak: false)

// Dates are set hard against the right margin, and body text wraps at that
// same margin, so a bullet's first line runs the full width of the page and
// passes under the column the dates sit in. Holding the body clear of that
// column is what gives the page a right edge a reader can follow. The inset is
// measured from the widest date actually on the page, so it tracks the date
// size the fit ladder settles on rather than a number that goes stale.
#context {
  let date_width = calc.max(0pt, ..date_values.map(v => measure(dates(v)).width))
  let inset = if date_width > 0pt and s.date_gutter >= 0 {
    date_width + pt(s.date_gutter)
  } else {
    0pt
  }
  let text_width = page.width - 2 * pt(s.margin_x)
  let body_width = text_width - inset - pt(s.marker_indent) - pt(s.body_indent)
  // The inset is applied per block, by narrowing each one, rather than by
  // wrapping the run: a wrapper is block-level and would add spacing the run
  // does not have. With the inset off, widths are left unset and the blocks
  // reach the page exactly as they did before this existed.
  // Widths are always passed, whether or not there is an inset to apply.
  // Narrowing a block is how the inset is achieved, but it is also what
  // balances a wrapped bullet, and the second is worth having on a page whose
  // dates are not being cleared: with no width, a two-line bullet fills its
  // first line and drops a stub on the second.
  // A width is what applies the inset and also what balancing needs, so either
  // switches narrowing on. They are otherwise independent: the default is a
  // width with greedy filling, so a bullet's first line runs the whole measure
  // and stops at the edge the inset cut it to.
  let narrow = inset > 0pt or s.balance_bullets
  let body = (items, ..rest) => blocks(
    items, ..rest,
    text_width: if narrow { text_width - inset } else { none },
    bullet_width: if narrow { body_width } else { none },
    nested_indent: pt(s.marker_indent) + pt(s.body_indent),
    balance: s.balance_bullets,
  )

  for (i, sec) in doc.sections.enumerate() {
  if i > 0 { v(pt(s.section_gap_before), weak: false) }
  if sec.title != "" {
    // A real heading, so the PDF carries an H2 tag rather than anonymous bold
    // text. Body passed positionally, never as a markup block: the newline and
    // indentation inside `[...]` become a paragraph.
    heading(level: 2, text(
      font: if s.section_font == "" { s.body_font } else { s.section_font },
      weight: s.section_weight, size: pt(s.section_size),
      tracking: pt(s.section_tracking), fill: ink(s.accent, s.ink),
      if s.section_uppercase { upper(markup(sec.title)) } else { markup(sec.title) }))
    rule(s.section_rule, ink(s.section_rule_color, s.accent, s.ink), gap: s.section_rule_gap)
    v(pt(s.section_gap_after), weak: false)
  }

  body(sec.blocks)

  for (j, e) in sec.entries.enumerate() {
    if j > 0 or sec.blocks.len() > 0 { v(pt(s.entry_gap_before), weak: false) }
    heading(level: 3, outlined: false, split_line(
      if e.head.role != none {
        text(weight: s.role_weight)[#markup(e.head.role)]
        // On one line: a newline inside `[...]` renders as a space, which
        // would double the separator's own spacing.
        text(weight: s.org_weight, style: s.org_style,
          fill: ink(s.org_color, s.ink))[#s.role_sep#markup(e.head.org)]
      } else {
        text(weight: s.entry_weight)[#markup(e.head.left)]
      },
      dates(e.head.right),
    ))
    if e.sub != none {
      heading(level: 4, outlined: false, split_line(
        text(weight: s.sub_weight, fill: ink(s.sub_color, s.ink))[#markup(e.sub.left)],
        dates(e.sub.right),
      ))
    }
    body(e.blocks)
  }
  }
}

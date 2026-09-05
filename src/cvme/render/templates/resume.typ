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
#set list(
  tight: true,
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

#letterhead(doc, s)
#v(pt(s.header_gap), weak: false)

#for (i, sec) in doc.sections.enumerate() {
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

  blocks(sec.blocks)

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
    blocks(e.blocks)
  }
}

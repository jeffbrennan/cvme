// Resume template.
//
// Reads two JSON files from the virtual filesystem the engine builds:
//   document.json  the parsed document (strings hold Typst markup)
//   style.json     resolved style, all lengths as plain numbers in points

#import "_common.typ": blocks, letterhead, markup, pt, setup, split_line

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
    box(width: pt(s.marker_size), height: pt(s.marker_size), fill: rgb(s.ink),
        baseline: pt(s.marker_baseline))
  } else {
    text(size: pt(s.marker_size), fill: rgb(s.ink), baseline: pt(s.marker_baseline))[
      #s.marker_glyph
    ]
  },
  indent: pt(s.marker_indent),
  body-indent: pt(s.body_indent),
)

#letterhead(doc, s)
#v(pt(s.header_gap), weak: false)

#for (i, sec) in doc.sections.enumerate() {
  if i > 0 { v(pt(s.section_gap_before), weak: false) }
  if sec.title != "" {
    // A real heading, so the PDF carries an H2 tag rather than anonymous bold
    // text. Body passed positionally, never as a markup block: the newline and
    // indentation inside `[...]` become a paragraph.
    heading(level: 2, text(weight: "bold", size: pt(s.section_size),
      if s.section_uppercase { upper(markup(sec.title)) } else { markup(sec.title) }))
    v(pt(s.section_gap_after), weak: false)
  }

  blocks(sec.blocks)

  for (j, e) in sec.entries.enumerate() {
    if j > 0 or sec.blocks.len() > 0 { v(pt(s.entry_gap_before), weak: false) }
    heading(level: 3, outlined: false, if e.head.role != none {
      split_line(
        "#strong[" + e.head.role + "]" + s.role_sep + e.head.org,
        e.head.right, right_size: s.date_size,
      )
    } else {
      split_line(e.head.left, e.head.right, right_size: s.date_size, weight: "bold")
    })
    if e.sub != none {
      heading(level: 4, outlined: false,
        split_line(e.sub.left, e.sub.right, right_size: s.date_size, weight: "bold"))
    }
    blocks(e.blocks)
  }
}

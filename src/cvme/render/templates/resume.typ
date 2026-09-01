// Resume template.
//
// Reads two JSON files from the virtual filesystem the engine builds:
//   document.json  the parsed document (strings hold Typst markup)
//   style.json     resolved style, all lengths as plain numbers in points
//
// All vertical spacing is explicit and non-weak. Weak spacing collapses
// against adjacent block spacing, which makes the rhythm depend on what
// happens to precede each element; being explicit is what lets the geometry
// tests hold a tolerance.

#let doc = json("document.json")
#let s = json("style.json")

#let pt(x) = x * 1pt
#let ink = rgb(s.ink)

#set document(title: doc.title, author: doc.name_plain, keywords: doc.keywords)
#set page(paper: s.paper, margin: (x: pt(s.margin_x), y: pt(s.margin_y)))
#set text(font: s.body_font, size: pt(s.body_size), fill: ink, hyphenate: false)
#set par(justify: false, leading: pt(s.leading), spacing: pt(s.leading))
#set list(
  tight: true,
  marker: box(width: pt(s.marker_size), height: pt(s.marker_size), fill: ink,
              baseline: pt(s.marker_baseline)),
  indent: pt(s.marker_indent),
  body-indent: pt(s.body_indent),
)
#show link: underline

#let markup(body) = eval(body, mode: "markup")

// A left/right line: content at the left margin, content hard against the
// right. This is the one thing plain markdown cannot express, and the reason
// the grammar has a pipe.
// `lhs`/`rhs` rather than `left`/`right`: those names are Typst's alignment
// builtins, and shadowing them here breaks the `align` argument below.
#let split_line(lhs, rhs, right_size: none, weight: "regular") = {
  grid(
    columns: (1fr, auto), align: (left + bottom, right + bottom),
    text(weight: weight)[#markup(lhs)],
    if rhs != "" {
      text(weight: "bold", size: pt(right_size))[#markup(rhs)]
    },
  )
}

#let blocks(items) = {
  for b in items {
    if b.kind == "paragraph" {
      markup(b.text)
    } else if b.kind == "bullets" {
      list(..b.items.map(it => {
        markup(it.text)
        if it.children.len() > 0 {
          list(..it.children.map(c => markup(c.text)))
        }
      }))
    } else if b.kind == "pagebreak" {
      pagebreak()
    }
  }
}

// ── header ───────────────────────────────────────────────────────────────
#grid(
  columns: (1fr, auto), align: (left + bottom, right + bottom),
  text(font: s.name_font, weight: s.name_weight, size: pt(s.name_size))[#markup(doc.name)],
  text(size: pt(s.contact_size))[
    #doc.contact.map(c => if c.url == none { markup(c.text) } else {
      link(c.url)[#markup(c.text)]
    }).join(s.contact_sep)
  ],
)
#v(pt(s.header_gap), weak: false)

// ── sections ─────────────────────────────────────────────────────────────
#for (i, sec) in doc.sections.enumerate() {
  if i > 0 { v(pt(s.section_gap_before), weak: false) }
  text(weight: "bold", size: pt(s.section_size))[
    #if s.section_uppercase { upper(markup(sec.title)) } else { markup(sec.title) }
  ]
  v(pt(s.section_gap_after), weak: false)

  blocks(sec.blocks)

  for (j, e) in sec.entries.enumerate() {
    if j > 0 or sec.blocks.len() > 0 { v(pt(s.entry_gap_before), weak: false) }
    if e.head.role != none {
      split_line(
        "#strong[" + e.head.role + "]" + s.role_sep + e.head.org,
        e.head.right, right_size: s.date_size,
      )
    } else {
      split_line(e.head.left, e.head.right, right_size: s.date_size, weight: "bold")
    }
    if e.sub != none {
      split_line(e.sub.left, e.sub.right, right_size: s.date_size, weight: "bold")
    }
    blocks(e.blocks)
  }
}

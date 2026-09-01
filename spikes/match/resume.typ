#let d = json("data.json")

#let S = (
  body_size: 11pt, body_font: "Carlito",
  name_size: 19.5pt, name_font: "Fira Code", name_weight: 600,
  section_size: 12pt, date_size: 10pt,
  leading: 0.73em,
  before_section: 7pt, after_section: 11.4pt,
  before_entry: 6.7pt, marker_indent: 18pt, body_indent: 14.4pt,
)

#set page(paper: "us-letter", margin: (left: 0.8in, right: 0.8in, top: 0.5in, bottom: 0.5in))
#set text(font: S.body_font, size: S.body_size, hyphenate: false)
#set par(justify: false, leading: S.leading, spacing: S.leading)
#set list(tight: true, marker: box(width: 3.2pt, height: 3.2pt, fill: black, baseline: -0.5pt), indent: S.marker_indent, body-indent: S.body_indent)
#show link: underline

// ── header: name left, contact hard right, on one baseline ──────────────
#grid(
  columns: (1fr, auto), align: (left + bottom, right + bottom),
  text(font: S.name_font, weight: S.name_weight, size: S.name_size)[#d.name],
  text(size: S.body_size)[#d.contact.map(c => link(c.url)[#c.text]).join(" | ")],
)

#v(10pt)

#let section(title) = {
  v(S.before_section, weak: true)
  text(weight: "bold", size: S.section_size)[#upper(title)]
  v(S.after_section, weak: true)
}

#let entry(left_bold, left_rest, dates) = {
  v(S.before_entry, weak: true)
  grid(
    columns: (1fr, auto), align: (left + bottom, right + bottom),
    { text(weight: "bold")[#left_bold]; if left_rest != "" [ – #left_rest] },
    text(weight: "bold", size: S.date_size)[#dates],
  )
}

#section("Summary")
#d.summary

#section("Experience")
#for e in d.experience {
  entry(e.role, e.org, e.dates)
  list(..e.bullets)
}

#section("Education")
#for e in d.education {
  v(S.before_entry, weak: true)
  text(weight: "bold")[#e.school]
  parbreak()
  grid(
    columns: (1fr, auto), align: (left + bottom, right + bottom),
    text(weight: "bold")[#e.degree],
    text(weight: "bold", size: S.date_size)[#e.dates],
  )
  for x in e.extra { parbreak(); x }
}

#section("Skills")
#list(..d.skills.map(s => [#text(weight: "bold")[#s.label]: #s.body]))

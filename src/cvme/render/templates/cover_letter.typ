// Cover letter template.
//
// Shares its letterhead with the resume so the two read as one application.
// The body is ordinary markdown prose: no entry grammar, no bullets expected
// (though both render if present).
//
// Frontmatter keys, all optional: date, recipient (multi-line), subject,
// salutation, closing.

#import "_common.typ": blocks, letterhead, lines, markup, pt, setup

#let doc = json("document.json")
#let s = json("style.json")

#let meta(key) = if key in doc.meta and doc.meta.at(key) != "" {
  doc.meta.at(key)
} else { none }

#set document(title: doc.title, author: doc.name_plain, keywords: doc.keywords)
#show: setup(s)

#letterhead(doc, s)
#v(pt(s.letter_gap), weak: false)

#let date = meta("date")
#if date != none {
  markup(date)
  v(pt(s.letter_block_gap), weak: false)
}

#let recipient = meta("recipient")
#if recipient != none {
  lines(recipient)
  v(pt(s.letter_block_gap), weak: false)
}

#let subject = meta("subject")
#if subject != none {
  text(weight: "bold")[#markup(subject)]
  v(pt(s.letter_block_gap), weak: false)
}

#let salutation = meta("salutation")
#if salutation != none {
  markup(salutation)
  v(pt(s.paragraph_gap), weak: false)
}

#for (i, sec) in doc.sections.enumerate() {
  if i > 0 { v(pt(s.paragraph_gap), weak: false) }
  if sec.title != "" {
    heading(level: 2, text(weight: "bold", size: pt(s.section_size))[#markup(sec.title)])
    v(pt(s.paragraph_gap), weak: false)
  }
  blocks(sec.blocks, paragraph_gap: s.paragraph_gap)
}

#let closing = meta("closing")
#if closing != none {
  v(pt(s.letter_block_gap), weak: false)
  markup(closing)
  v(pt(s.signature_gap), weak: false)
  markup(doc.name)
}

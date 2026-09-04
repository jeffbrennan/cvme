# Task: tailor a resume

Produce a version of the BASE DOCUMENT below, targeted at the JOB POSTING.

Write the result to: `{output_path}`

## Constraints

- Every number carries `<!-- fact: id -->` on the same line as the number.
  This is checked mechanically and is the most common reason a draft is
  rejected; check each one before you finish.
- Conform exactly to the grammar in the GRAMMAR section. It is parsed
  mechanically; a document that does not conform will not render.
- Keep the frontmatter unchanged apart from `keywords`, which you may set from
  the posting's own vocabulary where the corpus supports the claim.
- Section order may change. Sections may not be invented.
- Between {min_bullets} and {max_bullets} bullets per role, and no bullet
  longer than {max_bullet_words} words.
- The document must fit {max_pages} page(s). Cutting the least relevant true
  material is the intended way to achieve that.
- Preserve every role and every date range. Tailoring changes emphasis, never
  employment history.

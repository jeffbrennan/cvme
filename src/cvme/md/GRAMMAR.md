# cvme markdown grammar

This file is the authoring contract. It is also the file handed to a generator
verbatim, so that whatever writes these documents and whatever parses them
cannot drift apart.

The grammar is deliberately small. Beyond YAML frontmatter there is one
invention — **a pipe splits left-aligned from right-aligned content** — plus
`@` as a convenience inside it. Everything else is ordinary markdown.

## Frontmatter

```yaml
---
name: Morgan Avery
contact:
  - text: morgan.avery@example.com
    url: mailto:morgan.avery@example.com
  - morganavery.example          # a bare string works too, with no link
---
```

`name` and `contact` are rendered in the header. Any other key is carried
through as document metadata; `title` and `keywords` reach the PDF's metadata,
which is what most automated readers look at first.

## Blocks

| Construct | Meaning |
|---|---|
| `## Heading` | Section. Rendered uppercase and bold, with no rule beneath. |
| `### Left \| Right` | Entry header. Text after `\|` is set hard against the right margin, on the same line. |
| `### Role @ Org \| Dates` | Inside an experience section, ` @ ` splits the left side so the role sets bold and the organisation regular, as `**Role** – Org`. |
| `#### Left \| Right` | A second entry line with the same split. Education uses it for `degree \| date`. |
| Paragraph | Prose. Under an entry it is an unstyled follow-on line. |
| `- item` | Bullet, tight, hanging indent. One level of nesting is supported. |
| `---` | Explicit page break. |

Inline `**bold**`, `*italic*`, `` `code` `` and `[text](url)` all work.

## Fact provenance

```markdown
- Cut the nightly window from 6h to 40m <!-- fact: m-ingest-window -->
```

`<!-- fact: id -->` marks where a claim came from. It is stripped from the
rendered document and collected into the IR, where `cvme verify` checks it
against the fact corpus. Writing one is optional today and required for any
quantitative claim once verification lands.

## Escaping

A literal pipe is `\|` and a literal at-sign in an entry header is `\@`. Both
are only special in the positions described above: `@` in body text, and in a
contact address, needs no escape.

## Worked example

```markdown
---
name: Morgan Avery
contact:
  - text: morgan.avery@example.com
    url: mailto:morgan.avery@example.com
---

## Summary

Six years across the data lifecycle. <!-- fact: s-experience-years -->

## Experience

### Staff Data Engineer @ Northwind Analytics | Jul 2023 – Present

- Own ingestion for several hundred tenants <!-- fact: m-tenant-count -->
- Built a CLI that generates orchestration workflows

## Education

### Ridgeway University
#### Master of Science - Major in Epidemiology | May 2020

Certificate: Data Science

## Skills

- **Languages**: Python (advanced), SQL (advanced)
```

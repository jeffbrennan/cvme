"""One-way sync from the markdown source of truth to a LinkedIn profile.

``base.md`` is the document that has to fit a page. A LinkedIn profile does
not, so the projection reads an optional ``linkedin.md`` overlay for the
longer copy and falls back to the resume everywhere the overlay is silent.
"""

# Docs README Link Integrity

Section status: implementation accepted for the seventeenth development loop section.

## Requirement Document

`docs/README.md` is the documentation entry point, but it currently references
several docs files that are not present in this checkout. Broken entry-point
links make the accepted section documentation harder to discover and reduce the
value of the progress loop.

This section cleans the README to link only to existing documentation and adds a
small test guard so missing local docs links are caught early.

Scope:

- Remove or replace stale `docs/README.md` links to missing local files.
- Keep links to existing docs, design docs, implementation docs, and examples.
- Add a focused docs link integrity test for `docs/README.md` and the section
  design index.

Out of scope:

- Recreating old missing docs.
- Full Markdown link validation across the repository.
- External link validation.

## Acceptance Criteria

- Every local link in `docs/README.md` resolves to an existing file or
  directory.
- Every local link in `docs/design/section-design-index.md` resolves.
- A test fails when those entry-point docs contain missing local links.
- `progress.md` records the section result.

## Structure Design

Files changed in this section:

```text
docs/
  README.md
  design/docs-readme-link-integrity.md

tests/
  test_docs_links.py

progress.md
```

## Implementation Design

1. Update `docs/README.md` to point only at existing docs.
2. Add a small regex-based local Markdown link test.
3. Ignore external URLs and anchors.
4. Run the docs link test.

## Review Checklist

- The README remains useful as a short entry point.
- The test is intentionally narrow and does not require a Markdown parser.
- No stale docs are recreated just to satisfy links.

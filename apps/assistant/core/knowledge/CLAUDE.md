# apps/assistant/core/knowledge/

The full-text index behind `knowledge_search`: the bible and ADRs from the image, every markdown page in this directory, soul, the glossary, the issues and the assistant's own notes. Rebuilt off the request path.

- **This directory ships with one example page.** Drop how-to pages for your own setup here, one heading per topic; they are indexed on the next rebuild. Do not put secrets or personal data in them: the assistant quotes what it finds.
- A source that cannot be read is skipped and logged; the last good index stays.

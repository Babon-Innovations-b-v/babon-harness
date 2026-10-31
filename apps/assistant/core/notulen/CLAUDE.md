# apps/assistant/core/notulen/

Files a meeting's action items and decisions on the board. `parse_minutes` reads the template's action items table in plain Python, `candidate_issues` lists the open issues, `decide_placements` lets the model choose a parent per item from that list only, `file_minutes` writes through `github_act`.

- **How many issues a meeting opens is read, never judged.** The template owns the count; the model only places.
- Area and assignee choices come from `.claude/project.json` (`areas`, `people`); an unknown one is refused, not guessed.
- Heading spellings live in `parse_minutes.py`; a translated template adds its heading there.

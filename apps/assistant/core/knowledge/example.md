# Example knowledge page

Replace this page with how-to pages for your own setup. Every markdown file in
this directory is indexed by `knowledge_search`, split on its second-level
headings, so one heading per topic keeps an answer short.

## How to restart the assistant

On the server, from the repository root:

    docker compose restart assistant

The assistant's state lives on a named volume and survives the restart.

"""The recorder SPA (``inputs/`` layer).

    dashboard.html  the page shell and its styles
    dashboard.js    the recorder: chunked upload, IndexedDB queue, recovery,
                    job list, the minutes editor and the send-to-assistant button

Served by ``entrypoints/spa_routes.py`` with no-store, so a phone never runs a
cached script against routes that have moved.
"""

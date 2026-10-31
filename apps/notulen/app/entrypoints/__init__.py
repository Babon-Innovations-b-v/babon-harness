"""Notulen dashboard FastAPI surface (``entrypoints/`` layer).

The only layer that imports FastAPI routing. uvicorn target:
``apps.notulen.app.entrypoints.main:app``.

Module map:
    main.py            app assembly: DashkitConfig, factory, routers, startup hooks
    spa_routes.py      GET / and /dashboard.js (the SPA shell, no-store)
    people_routes.py   GET /api/people (attendee suggestions)
    upload_routes.py   POST /api/upload/* chunked-upload lifecycle
    jobs_routes.py     GET/POST/DELETE /api/jobs* projections, retry, download
    minutes_routes.py  read, correct and hand on committed minutes
    health_routes.py   /healthz and /api/health/notulen/full

No re-exports: route modules register everything on their ``router``; the
seam is HTTP, not Python.
"""

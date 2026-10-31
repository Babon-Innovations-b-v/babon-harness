"""GitHub write-path helpers (``core/publish/github/``).

Module map:
    api_session.py      the token and headers, once
    github_writer.py    commit minutes via the GitHub Contents API, never overwriting
    read_notulen.py     read committed minutes back with their blob sha
    rewrite_notulen.py  the one door that replaces a file, for a person's correction
    remove_notulen.py   take the file out when a recording is deleted
    attendee_name.py    the who half of the path: ``alice_bob``
    target_path.py      ``<NOTULEN_TARGET_PATH>/<YYYY-MM>/<who>/<YYYY-MM-DD>.md``
"""

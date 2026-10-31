"""Repo-relative target path for a committed minutes file.

Owns the path grammar ``<NOTULEN_TARGET_PATH>/<YYYY-MM>/<who>/<YYYY-MM-DD>.md``:
a folder per month, a folder per set of people inside it, and the day as the
filename. The people are a folder rather than part of the name because a
standing meeting is one thing that happened many times, and reads best as a
dated list. The day stays the whole date: a file lifted out of its folder
still has to say when it happened.

The slug grammar lives in ``shared/slug.py`` and the who-was-there grammar in
``attendee_name.py`` beside this file.
"""
from __future__ import annotations

from apps.notulen.app.core.publish.github.attendee_name import attendee_name
from apps.notulen.app.shared.config import target_folder
from apps.notulen.app.shared.slug import slugify


def target_path(meeting_date: str, title: str, attendees: list[str]) -> str:
    """Repo-relative path for a notulen markdown file.

    The date comes from the first 10 chars of ``meeting_date`` (works for both
    ``YYYY-MM-DD`` and full ISO timestamps). The folder says who was there, and
    falls back to the meeting title when the attendee list is empty, because a
    set of minutes must always land somewhere.
    """
    day = meeting_date[:10]
    who = attendee_name(attendees) or slugify(title) or "notulen"
    return f"{target_folder()}/{day[:7]}/{who}/{day}.md"

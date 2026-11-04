"""Test defaults for the assistant package.

The tests pin a zone with a daylight-saving change, so the clock conversions
they assert are exercised across both offsets, and a project file with four
placeholder people and two areas, so the board rules have something to hold.
Production reads ASSISTANT_TIMEZONE from the owner's settings and
`.claude/project.json` from the repository; nothing here leaks into either.
"""
import json
import os
import tempfile

os.environ.setdefault("ASSISTANT_TIMEZONE", "Europe/Amsterdam")
os.environ.setdefault("ASSISTANT_NAME", "Assistant")

_PROJECT = {
    "repo": "owner/repo",
    "owner": "alex-example",
    "area_label_prefix": "area:",
    "areas": ["dev", "finance"],
    "backlog_prd": 151,
    "people": {
        "Alex": "alex-example",
        "Sam": "sam-example",
        "Robin": "robin-example",
        "Kim": "kim-example",
    },
}
if "HARNESS_PROJECT_JSON" not in os.environ:
    _handle, _path = tempfile.mkstemp(prefix="assistant-project-", suffix=".json")
    with os.fdopen(_handle, "w", encoding="utf-8") as _file:
        json.dump(_PROJECT, _file)
    os.environ["HARNESS_PROJECT_JSON"] = _path


# The frozen clock. A test that needs "now" asks for `frozen_clock` and builds
# its ground truth from `FROZEN_AT`; every assistant module already imported
# then reads that instant (a microsecond later at each read, so the order of
# two writes survives), so the verdict depends on the commit and never
# on the day or the hour the test happens to run.

import datetime as _real_datetime
import sys as _sys
import time as _real_time
import types as _types

import pytest

#: A Tuesday, 10:30 in the pinned zone (winter time), well clear of any quiet window,
#: and later than every fixed date a test writes into its ground truth.
FROZEN_AT = _real_datetime.datetime(2026, 11, 10, 9, 30, tzinfo=_real_datetime.timezone.utc)


class _SameClass(type):
    """A stand-in class that still answers isinstance for the real one."""

    def __instancecheck__(cls, instance):
        return isinstance(instance, cls.__mro__[1])


_TICKS = [0]


def _tick():
    """The frozen instant, one microsecond later at every read, so order survives."""
    _TICKS[0] += 1
    return FROZEN_AT + _real_datetime.timedelta(microseconds=_TICKS[0])


class _FrozenDateTime(_real_datetime.datetime, metaclass=_SameClass):
    @classmethod
    def now(cls, tz=None):
        moment = _tick()
        return moment.astimezone(tz) if tz is not None else moment.astimezone().replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return _tick().replace(tzinfo=None)

    @classmethod
    def today(cls):
        return cls.now()


class _FrozenDate(_real_datetime.date, metaclass=_SameClass):
    @classmethod
    def today(cls):
        return FROZEN_AT.astimezone().date()


def _frozen_module(real, **overrides):
    """A copy of a stdlib module's namespace with the clock readers replaced."""
    copy = _types.SimpleNamespace(**vars(real))
    for name, value in overrides.items():
        setattr(copy, name, value)
    return copy


@pytest.fixture
def frozen_clock(monkeypatch):
    """Every loaded assistant module reads the clock from FROZEN_AT on; returns that instant."""
    _TICKS[0] = 0
    datetime_module = _frozen_module(_real_datetime, datetime=_FrozenDateTime, date=_FrozenDate)
    time_module = _frozen_module(_real_time, time=lambda: _tick().timestamp(),
                                 time_ns=lambda: int(_tick().timestamp() * 10**6) * 1000)
    swaps = {id(_real_datetime.datetime): _FrozenDateTime, id(_real_datetime.date): _FrozenDate,
             id(_real_datetime): datetime_module, id(_real_time): time_module}
    for name, module in list(_sys.modules.items()):
        if not name.startswith("apps.assistant") or module is None or ".tests" in name or name.endswith("conftest"):
            continue
        for attribute, value in list(vars(module).items()):
            if id(value) in swaps:
                monkeypatch.setattr(module, attribute, swaps[id(value)])
    return FROZEN_AT

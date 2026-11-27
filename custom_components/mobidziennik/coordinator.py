"""Data update coordinator for mobiDziennik."""
from __future__ import annotations

import logging
import random
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import AccountData, MobiDziennikAuthError, MobiDziennikClient, MobiDziennikError
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_NEW_ABSENCE,
    EVENT_NEW_GRADE,
    EVENT_NEW_REMARK,
)

_LOGGER = logging.getLogger(__name__)


class MobiDziennikCoordinator(DataUpdateCoordinator[AccountData]):
    """Fetches grades, timetable, tests, homework and messages on a schedule."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: MobiDziennikClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.entry = entry
        self.client = client

    def _next_interval(self) -> timedelta:
        """Irregular polling: ~hourly on school-day daytime, ~3 h otherwise.

        mobiDziennik has no public API, so keep the load low and avoid a
        machine-regular pattern (random interval every cycle).
        """
        now = dt_util.now()
        if now.weekday() < 5 and 6 <= now.hour < 21:
            minutes = random.uniform(45, 75)
        else:
            minutes = random.uniform(150, 210)
        return timedelta(minutes=minutes)

    async def _async_update_data(self) -> AccountData:
        # The coordinator schedules the next refresh from update_interval
        # after this call returns, so a new random value applies each cycle.
        self.update_interval = self._next_interval()
        _LOGGER.debug("Next mobiDziennik refresh in %s", self.update_interval)
        try:
            data = await self.client.async_get_all(dt_util.now().date())
        except MobiDziennikAuthError as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except MobiDziennikError as err:
            raise UpdateFailed(f"Error communicating with mobiDziennik: {err}") from err
        if self.data is not None:
            self._fire_new_item_events(self.data, data)
        return data

    def _fire_new_item_events(self, old: AccountData, new: AccountData) -> None:
        """Fire bus events for grades, remarks and absences not seen before.

        Only compares sections that were present in the previous snapshot,
        so the first load (or a page that failed before) never floods the bus.
        """
        for name, student in new.students.items():
            prev = old.students.get(name)
            if prev is None:
                continue
            seen_grades = {_grade_key(g) for g in prev.grades}
            for g in student.grades:
                if _grade_key(g) not in seen_grades:
                    self.hass.bus.async_fire(EVENT_NEW_GRADE, {
                        "student": name,
                        "subject": g.subject,
                        "grade": g.symbol,
                        "category": g.category,
                        "topic": g.topic,
                        "weight": g.weight,
                        "teacher": g.teacher,
                        "entered": g.entered_at.isoformat() if g.entered_at else None,
                    })
            if prev.behaviour is not None and student.behaviour is not None:
                seen = {(r.entered_at, r.text) for r in prev.behaviour.remarks}
                for r in student.behaviour.remarks:
                    if (r.entered_at, r.text) not in seen:
                        self.hass.bus.async_fire(EVENT_NEW_REMARK, {
                            "student": name,
                            "kind": r.kind,
                            "points": r.points,
                            "text": r.text,
                            "category": r.category,
                            "teacher": r.teacher,
                            "entered": r.entered_at.isoformat() if r.entered_at else None,
                        })
            if prev.attendance is not None and student.attendance is not None:
                seen_abs = {(d.day, l.time, l.subject) for d in prev.absences for l in d.lessons}
                for d in student.absences:
                    for l in d.lessons:
                        if (d.day, l.time, l.subject) not in seen_abs:
                            self.hass.bus.async_fire(EVENT_NEW_ABSENCE, {
                                "student": name,
                                "date": d.day.isoformat(),
                                "time": l.time,
                                "subject": l.subject,
                                "teacher": l.teacher,
                                "excused": l.excused,
                            })


def _grade_key(grade) -> tuple:
    return (grade.grade_id,) if grade.grade_id else (grade.subject, grade.symbol, grade.entered_at)


def build_client(hass: HomeAssistant, school_id: str, email: str, password: str) -> MobiDziennikClient:
    """Create a client with its own cookie jar (one session per account)."""
    session = async_create_clientsession(hass)
    return MobiDziennikClient(session, school_id, email, password)

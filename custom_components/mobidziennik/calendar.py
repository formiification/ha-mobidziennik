"""Calendar platform for mobiDziennik: the class calendar of each student.

Entries come from the "Kalendarz klasowy" page: announced tests and
quizzes, class events, trips, things to bring and school days off.
All entries are all-day events.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import CalendarItem, StudentData, slugify_name
from .const import DOMAIN
from .coordinator import MobiDziennikCoordinator

KIND_LABELS = {
    "test": "Test",
    "quiz": "Quiz",
    "trip": "Trip",
    "event": "Event",
    "info": "Info",
    "duty": "Duty",
    "own": "Note",
    "school": "School",
    "day_off": "Day off",
}


def _to_event(item: CalendarItem) -> CalendarEvent:
    label = KIND_LABELS.get(item.kind, item.kind)
    return CalendarEvent(
        start=item.start,
        end=item.end + timedelta(days=1),  # HA all-day end is exclusive
        summary=f"{label}: {item.title}",
        description=item.description,
        uid=item.uid,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one class calendar per student."""
    coordinator: MobiDziennikCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ClassCalendar(coordinator, entry, name) for name in coordinator.data.students
    )


class ClassCalendar(CoordinatorEntity[MobiDziennikCoordinator], CalendarEntity):
    """Class calendar of one student."""

    _attr_has_entity_name = True
    _attr_translation_key = "class_calendar"

    def __init__(self, coordinator: MobiDziennikCoordinator, entry: ConfigEntry, student_name: str) -> None:
        super().__init__(coordinator)
        self._student_name = student_name
        school_id = entry.data.get("school_id", "mobidziennik")
        self._attr_unique_id = f"{entry.entry_id}_{slugify_name(student_name)}_class_calendar"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{school_id}_{slugify_name(student_name)}")},
            name=student_name,
            manufacturer="mobiDziennik (unofficial)",
            model="Student",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=coordinator.client.base_url + "/dziennik",
        )

    @property
    def _student(self) -> StudentData | None:
        return self.coordinator.data.students.get(self._student_name)

    @property
    def available(self) -> bool:
        return super().available and self._student is not None

    @property
    def event(self) -> CalendarEvent | None:
        """The current or next entry."""
        student = self._student
        if student is None:
            return None
        today = dt_util.now().date()
        for item in student.calendar:
            if item.end >= today:
                return _to_event(item)
        return None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        student = self._student
        if student is None:
            return []
        first: date = dt_util.as_local(start_date).date()
        last: date = dt_util.as_local(end_date).date()
        return [
            _to_event(item)
            for item in student.calendar
            if item.end >= first and item.start <= last
        ]

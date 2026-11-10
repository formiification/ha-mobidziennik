"""Sensor platform for mobiDziennik.

Design goals (v0.2): every entity has a proper name, the state is
readable at a glance on a dashboard, and attributes hold short,
human-readable lines rather than raw scraped fragments.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import Grade, Lesson, StudentData, slugify_name
from .const import DOMAIN, RECENT_GRADES_DAYS
from .coordinator import MobiDziennikCoordinator

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MAX_STATE = 255


# ----------------------------------------------------------------------
# Formatting helpers
# ----------------------------------------------------------------------

def _d(day: date) -> str:
    """12.11"""
    return day.strftime("%d.%m")


def _wd(day: date) -> str:
    """Thu 12.11"""
    return f"{WEEKDAYS[day.weekday()]} {_d(day)}"


def _t(value) -> str:
    return value.strftime("%H:%M") if value else "?"


def _cut(text: str, limit: int = MAX_STATE) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _lesson_line(lesson: Lesson) -> str:
    line = f"{_t(lesson.start)}–{_t(lesson.end)} {lesson.subject}"
    if lesson.room:
        line += f" (s. {lesson.room})" if lesson.room[:1].isdigit() else f" ({lesson.room})"
    if lesson.is_substitution:
        line += f" – zastępstwo: {lesson.teacher or '?'}"
    return line


def _lessons_on(student: StudentData, day: date) -> list[Lesson]:
    return [l for l in student.lessons if l.day == day and l.start is not None]


def _day_summary(student: StudentData, day: date) -> str:
    if day in student.days_off:
        return f"Day off – {student.days_off[day]}"
    lessons = _lessons_on(student, day)
    if not lessons:
        return "No lessons"
    return f"{_t(lessons[0].start)}–{_t(lessons[-1].end)} ({len(lessons)})"


def _day_attrs(student: StudentData, day: date) -> dict[str, Any]:
    lessons = _lessons_on(student, day)
    return {
        "date": day.isoformat(),
        "day_off": student.days_off.get(day),
        "lesson_count": len(lessons),
        "start": _t(lessons[0].start) if lessons else None,
        "end": _t(lessons[-1].end) if lessons else None,
        "substitutions": sum(1 for l in lessons if l.is_substitution),
        "lessons": [_lesson_line(l) for l in lessons],
    }


def _next_school_day(student: StudentData, today: date) -> date | None:
    days = sorted({l.day for l in student.lessons if l.day > today})
    return days[0] if days else None


def _sorted_grades(student: StudentData) -> list[Grade]:
    dated = [g for g in student.grades if g.entered_at is not None]
    return sorted(dated, key=lambda g: g.entered_at, reverse=True)


def _grade_line(grade: Grade) -> str:
    when = grade.entered_at.strftime("%d.%m") if grade.entered_at else "?"
    details = [x for x in (grade.category, f"waga {grade.weight}" if grade.weight else None) if x]
    line = f"{when} {grade.subject}: {grade.symbol}"
    if details:
        line += f" ({', '.join(details)})"
    if grade.topic:
        line += f" – {grade.topic}"
    return line


def _now() -> datetime:
    return dt_util.now().replace(tzinfo=None)


# ----------------------------------------------------------------------
# Student sensors
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class StudentSensorSpec:
    key: str  # unique_id suffix and translation key
    icon: str
    value: Callable[[StudentData], Any]
    attrs: Callable[[StudentData], dict[str, Any]] | None = None
    unit: str | None = None
    state_class: SensorStateClass | None = None
    available_if: Callable[[StudentData], bool] | None = None  # create only if true


def _next_lesson(student: StudentData) -> Lesson | None:
    now = _now()
    for lesson in student.lessons:
        if lesson.end is None:
            continue
        if datetime.combine(lesson.day, lesson.end) >= now:
            return lesson
    return None


def _next_lesson_value(student: StudentData) -> str | None:
    lesson = _next_lesson(student)
    if lesson is None:
        return None
    today = _now().date()
    when = _t(lesson.start) if lesson.day == today else f"{_wd(lesson.day)} {_t(lesson.start)}"
    return _cut(f"{lesson.subject} ({when})")


def _next_lesson_attrs(student: StudentData) -> dict[str, Any]:
    lesson = _next_lesson(student)
    if lesson is None:
        return {}
    return {
        "subject": lesson.subject,
        "date": lesson.day.isoformat(),
        "time": f"{_t(lesson.start)}–{_t(lesson.end)}",
        "room": lesson.room,
        "teacher": lesson.teacher,
        "class": lesson.class_group,
        "substitution": lesson.is_substitution,
    }


def _today_value(student: StudentData) -> str:
    return _cut(_day_summary(student, _now().date()))


def _today_attrs(student: StudentData) -> dict[str, Any]:
    return _day_attrs(student, _now().date())


def _next_day_value(student: StudentData) -> str | None:
    today = _now().date()
    day = _next_school_day(student, today)
    if day is None:
        return None
    return _cut(f"{_wd(day)}: {_day_summary(student, day)}")


def _next_day_attrs(student: StudentData) -> dict[str, Any]:
    day = _next_school_day(student, _now().date())
    return _day_attrs(student, day) if day else {}


def _latest_grade_value(student: StudentData) -> str | None:
    grades = _sorted_grades(student)
    if not grades:
        return None
    g = grades[0]
    return _cut(f"{g.symbol} – {g.subject}")


def _latest_grade_attrs(student: StudentData) -> dict[str, Any]:
    grades = _sorted_grades(student)
    if not grades:
        return {}
    g = grades[0]
    return {
        "grade": g.symbol,
        "subject": g.subject,
        "category": g.category,
        "topic": g.topic,
        "weight": g.weight,
        "counts_to_average": g.counts_to_average,
        "teacher": g.teacher,
        "comment": g.comment,
        "entered": g.entered_at.isoformat() if g.entered_at else None,
    }


def _recent(student: StudentData) -> list[Grade]:
    since = _now() - timedelta(days=RECENT_GRADES_DAYS)
    return [g for g in _sorted_grades(student) if g.entered_at >= since]


def _recent_attrs(student: StudentData) -> dict[str, Any]:
    return {
        "days": RECENT_GRADES_DAYS,
        "grades": [_grade_line(g) for g in _recent(student)],
    }


def _average_value(student: StudentData) -> float | None:
    if not student.averages:
        return None
    return round(sum(student.averages.values()) / len(student.averages), 2)


def _average_attrs(student: StudentData) -> dict[str, Any]:
    return {
        "subjects": {k: v for k, v in sorted(student.averages.items(), key=lambda kv: -kv[1])},
        "lowest": min(student.averages, key=student.averages.get) if student.averages else None,
    }


def _upcoming_tests(student: StudentData):
    today = _now().date()
    return [t for t in student.tests if t.day >= today]


def _next_test_value(student: StudentData) -> str:
    tests = _upcoming_tests(student)
    if not tests:
        return "None"
    t = tests[0]
    kind = f" ({t.kind})" if t.kind else ""
    return _cut(f"{_wd(t.day)} {t.subject}{kind}")


def _next_test_attrs(student: StudentData) -> dict[str, Any]:
    tests = _upcoming_tests(student)
    attrs: dict[str, Any] = {"count": len(tests)}
    if tests:
        t = tests[0]
        attrs.update(
            {
                "date": t.day.isoformat(),
                "days_until": (t.day - _now().date()).days,
                "subject": t.subject,
                "kind": t.kind,
                "topic": t.topic,
            }
        )
    attrs["upcoming"] = [
        _cut(f"{_wd(t.day)} {t.subject} ({t.kind or '?'}): {t.topic or ''}".rstrip(": "), 200)
        for t in tests
    ]
    return attrs


def _open_homework(student: StudentData):
    today = _now().date()
    return [h for h in student.homework if not h.done and (h.due is None or h.due >= today)]


def _homework_attrs(student: StudentData) -> dict[str, Any]:
    today = _now().date()
    upcoming = [h for h in student.homework if h.due is None or h.due >= today]
    return {
        "items": [
            _cut(
                f"{'✔ ' if h.done else ''}{_wd(h.due) if h.due else '?'} {h.subject}: {h.content or ''}".rstrip(": "),
                250,
            )
            for h in upcoming
        ],
    }


STUDENT_SENSORS: tuple[StudentSensorSpec, ...] = (
    StudentSensorSpec("next_lesson", "mdi:clock-outline", _next_lesson_value, _next_lesson_attrs),
    StudentSensorSpec("today_lessons", "mdi:timetable", _today_value, _today_attrs),
    StudentSensorSpec("next_school_day", "mdi:calendar-arrow-right", _next_day_value, _next_day_attrs),
    StudentSensorSpec("last_grade", "mdi:school", _latest_grade_value, _latest_grade_attrs),
    StudentSensorSpec(
        "recent_grades", "mdi:format-list-numbered", lambda s: len(_recent(s)), _recent_attrs,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    StudentSensorSpec(
        "average", "mdi:chart-line", _average_value, _average_attrs,
        state_class=SensorStateClass.MEASUREMENT,
        available_if=lambda s: bool(s.averages),
    ),
    StudentSensorSpec("next_test", "mdi:file-document-edit-outline", _next_test_value, _next_test_attrs),
    StudentSensorSpec(
        "homework", "mdi:notebook-edit-outline", lambda s: len(_open_homework(s)), _homework_attrs,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up mobiDziennik sensors from a config entry."""
    coordinator: MobiDziennikCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = [UnreadMessagesSensor(coordinator, entry)]
    for name, student in coordinator.data.students.items():
        for spec in STUDENT_SENSORS:
            if spec.available_if is None or spec.available_if(student):
                entities.append(StudentSensor(coordinator, entry, name, spec))
    async_add_entities(entities)


class _Base(CoordinatorEntity[MobiDziennikCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: MobiDziennikCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    def _device(self, student_name: str | None) -> DeviceInfo:
        school_id = self._entry.data.get("school_id", "mobidziennik")
        return DeviceInfo(
            identifiers={(DOMAIN, f"{school_id}_{slugify_name(student_name)}" if student_name else school_id)},
            name=student_name or "mobiDziennik",
            manufacturer="mobiDziennik (unofficial)",
            model="Student" if student_name else "Parent account",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=self.coordinator.client.base_url + "/dziennik",
        )


class StudentSensor(_Base):
    """One sensor per (student, spec)."""

    def __init__(
        self,
        coordinator: MobiDziennikCoordinator,
        entry: ConfigEntry,
        student_name: str,
        spec: StudentSensorSpec,
    ) -> None:
        super().__init__(coordinator, entry)
        self._student_name = student_name
        self._spec = spec
        self._attr_translation_key = spec.key
        self._attr_icon = spec.icon
        self._attr_native_unit_of_measurement = spec.unit
        self._attr_state_class = spec.state_class
        self._attr_unique_id = f"{entry.entry_id}_{slugify_name(student_name)}_{spec.key}"
        self._attr_device_info = self._device(student_name)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # States like "next lesson" depend on the clock, not only on new
        # data: re-render once a minute (no extra requests to the site).
        self.async_on_remove(
            async_track_time_change(self.hass, self._minute_tick, second=5)
        )

    @callback
    def _minute_tick(self, _now) -> None:
        if self.coordinator.data is not None:
            self.async_write_ha_state()

    @property
    def _student(self) -> StudentData | None:
        return self.coordinator.data.students.get(self._student_name)

    @property
    def available(self) -> bool:
        return super().available and self._student is not None

    @property
    def native_value(self):
        return self._spec.value(self._student)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self._spec.attrs is None:
            return None
        return self._spec.attrs(self._student)


class UnreadMessagesSensor(_Base):
    """Number of unread messages, with the unread subjects listed."""

    _attr_translation_key = "unread_messages"
    _attr_icon = "mdi:email-alert-outline"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: MobiDziennikCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_unread_messages"
        self._attr_device_info = self._device(None)

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.unread_messages)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "unread": [
                f"{m.received or '?'} – {m.sender or '?'}: {m.subject}"
                for m in self.coordinator.data.unread_messages
            ],
            "latest": (
                f"{self.coordinator.data.messages[0].received} – {self.coordinator.data.messages[0].subject}"
                if self.coordinator.data.messages
                else None
            ),
        }

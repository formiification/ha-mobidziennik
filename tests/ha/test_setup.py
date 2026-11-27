"""End-to-end: entry setup creates sensors + calendars; new items fire events."""
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.mobidziennik import api
from custom_components.mobidziennik.const import DOMAIN, EVENT_NEW_REMARK

TODAY = date(2026, 11, 27)


def _snapshot(extra_remark: bool = False) -> api.AccountData:
    remarks = [
        api.Remark("Konkurs", "positive", 10, "Konkursy", datetime(2026, 11, 23, 12, 0), "Nowak Ewa"),
    ]
    if extra_remark:
        remarks.insert(0, api.Remark("Rozmowy", "negative", -2, None, datetime(2026, 11, 27, 9, 0), "Nowak Ewa"))
    student = api.StudentData(
        name="Kowalski Jan",
        absences=[api.AbsenceDay(TODAY - timedelta(days=8), 2, 2, 0, [
            api.AbsenceLesson("07:05 - 07:50", "historia", "Nowak Ewa", False),
            api.AbsenceLesson("08:00 - 08:45", "biologia", "Nowak Ewa", False),
        ])],
        attendance=api.AttendanceStats(present=98, unexcused=2, excused=0),
        behaviour=api.Behaviour(points=68, grade="poprawne", term="I", remarks=remarks),
        calendar=[
            api.CalendarItem("sprawdzian;1;1", "test", TODAY + timedelta(days=3), TODAY + timedelta(days=3), "Ułamki", None),
            api.CalendarItem("dzien_wolny;1;", "day_off", TODAY + timedelta(days=24), TODAY + timedelta(days=32), "Przerwa świąteczna", None),
        ],
    )
    return api.AccountData(students={"Kowalski Jan": student}, messages=[])


async def test_setup_and_events(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"school_id": "s", "email": "u", "password": "p"},
        unique_id="s_u",
    )
    entry.add_to_hass(hass)
    with patch.object(api.MobiDziennikClient, "async_get_all", return_value=_snapshot()):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get("sensor.kowalski_jan_attendance").state == "98.0"
    assert hass.states.get("sensor.kowalski_jan_unexcused_absences").state == "2"
    assert hass.states.get("sensor.kowalski_jan_behaviour_points").state == "68"
    remark = hass.states.get("sensor.kowalski_jan_latest_remark")
    assert remark.state == "+10 Konkurs"
    assert remark.attributes["positive"] == 1
    cal = hass.states.get("calendar.kowalski_jan_class_calendar")
    assert cal is not None and cal.attributes["message"] == "Test: Ułamki"

    events = async_capture_events(hass, EVENT_NEW_REMARK)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    with patch.object(api.MobiDziennikClient, "async_get_all", return_value=_snapshot(extra_remark=True)):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["text"] == "Rozmowy" and events[0].data["points"] == -2
    assert hass.states.get("sensor.kowalski_jan_latest_remark").state == "-2 Rozmowy"

    # calendar service returns the day-off range with an exclusive end
    start = dt_util.start_of_local_day(datetime.combine(TODAY, datetime.min.time()))
    resp = await hass.services.async_call(
        "calendar", "get_events",
        {"entity_id": "calendar.kowalski_jan_class_calendar", "start_date_time": start, "duration": {"days": 60}},
        blocking=True, return_response=True,
    )
    items = resp["calendar.kowalski_jan_class_calendar"]["events"]
    assert [e["summary"] for e in items] == ["Test: Ułamki", "Day off: Przerwa świąteczna"]
    assert items[1]["end"] == (TODAY + timedelta(days=33)).isoformat()


async def test_polish_system_keeps_english_ids_and_polish_texts(hass: HomeAssistant) -> None:
    await hass.config.async_update(language="pl")
    snap = _snapshot()
    student = snap.students["Kowalski Jan"]
    student.lessons = [api.Lesson(TODAY + timedelta(days=3), None, None, "matematyka", None, "Nowak Ewa", "10")]
    student.days_off = {TODAY: "Dzień Edukacji"}
    entry = MockConfigEntry(domain=DOMAIN, data={"school_id": "s", "email": "u", "password": "p"}, unique_id="s_u")
    entry.add_to_hass(hass)
    with patch.object(api.MobiDziennikClient, "async_get_all", return_value=snap):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # ids do not follow the Polish entity names
    assert hass.states.get("sensor.kowalski_jan_next_test").state == "Brak"
    assert hass.states.get("sensor.kowalski_jan_today_lessons").state.startswith("Dzień wolny – ")
    assert hass.states.get("sensor.kowalski_jan_unread_messages") is None
    assert hass.states.get("sensor.mobidziennik_unread_messages") is not None
    unexcused = hass.states.get("sensor.kowalski_jan_unexcused_absences")
    assert unexcused.attributes["days"][0].startswith(("pon.", "wt.", "śr.", "czw.", "pt.", "sob.", "niedz."))
    assert "2 nieuspr." in unexcused.attributes["days"][0]
    cal = hass.states.get("calendar.kowalski_jan_class_calendar")
    assert cal.attributes["message"] == "Sprawdzian: Ułamki"

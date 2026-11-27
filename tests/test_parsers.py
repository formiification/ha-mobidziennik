"""Parser tests on anonymised copies of the real page structure."""
from datetime import date, datetime

import pytest

from mdz_loader import api

C = api.MobiDziennikClient


def test_attendance_main_and_extra_sections(fixture_html):
    result = C.parse_attendance(fixture_html("obecnosci.html"))
    ala_days, ala_stats = result["Kowalska Ala"]
    assert [d.day for d in ala_days] == [date(2026, 11, 19), date(2026, 11, 12)]
    assert (ala_days[0].total, ala_days[0].unexcused, ala_days[0].excused) == (2, 2, 0)
    assert [l.subject for l in ala_days[0].lessons] == ["edukacja wczesnoszkolna", "język angielski"]
    assert ala_days[0].lessons[0].excused is False
    assert ala_days[1].lessons[0].excused is True
    assert (ala_stats.present, ala_stats.unexcused, ala_stats.excused, ala_stats.late) == (100, 2, 1, 1)
    assert ala_stats.percent == pytest.approx(97.1)
    jan_days, jan_stats = result["Kowalski Jan"]
    # the club section adds a day but must not replace the main stats
    assert [d.day for d in jan_days] == [date(2026, 11, 3), date(2026, 10, 21)]
    assert jan_stats.present == 50 and jan_stats.excused == 1


def test_behaviour(fixture_html):
    result = C.parse_behaviour(fixture_html("zachowanie.html"))
    jan = result["Kowalski Jan"]
    assert (jan.term, jan.points, jan.grade) == ("I", 68, "poprawne")
    assert jan.final_grades == {"Ocena przewidywana śródroczna": "dobre"}
    assert [r.kind for r in jan.remarks] == ["positive", "negative", "neutral"]  # newest first
    top = jan.remarks[0]
    assert top.text == "Konkurs plastyczny" and top.points == 10
    assert top.category == "Udział w konkursach (1-10k)"
    assert top.teacher == "Kowalczyk - Zielińska Anna"
    assert top.entered_at == datetime(2026, 11, 23, 12, 23, 36)
    assert jan.remarks[2].category is None
    ala = result["Kowalska Ala"]
    assert ala.points is None and ala.final_grades == {} and len(ala.remarks) == 1


def test_calendar(fixture_html):
    result = C.parse_calendar(fixture_html("kalendarz.html"))
    ala = result["Kowalska Ala"]
    assert [(i.start, i.kind) for i in ala] == [
        (date(2026, 11, 30), "event"),
        (date(2026, 12, 3), "quiz"),
        (date(2027, 1, 18), "day_off"),
    ]
    assert ala[0].title == "Wróżby andrzejkowe"
    assert ala[0].description == "Wróżby andrzejkowe\nChętni uczniowie [przebrani]."
    assert ala[2].end == date(2027, 1, 31)
    jan = result["Kowalski Jan"]
    assert [(i.kind, i.title) for i in jan] == [
        ("test", 'Sprawdzian wiadomości "Rzeczpospolita"'),
        ("trip", "Wyjazd do kina"),
    ]


@pytest.mark.parametrize("parser", ["parse_attendance", "parse_behaviour", "parse_calendar"])
def test_parsers_raise_on_foreign_page(fixture_html, parser):
    with pytest.raises(api.MobiDziennikPageError):
        getattr(C, parser)(fixture_html("autowylogowanie.html"))


def test_auto_logout_detection(fixture_html):
    assert C._is_auto_logout(fixture_html("autowylogowanie.html"))
    assert C._is_auto_logout("", "https://x.mobidziennik.pl/helper/autowylogowanie")
    assert not C._is_auto_logout("<div id='content'>Oceny</div>", "https://x.mobidziennik.pl/dziennik/oceny")

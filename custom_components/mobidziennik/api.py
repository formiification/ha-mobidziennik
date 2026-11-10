"""Unofficial mobiDziennik client.

mobiDziennik does not expose a public JSON API - the parent portal is a
plain server-rendered HTML site. This client logs in the same way a
browser would (a form POST that sets a session cookie) and then scrapes
the pages it needs with BeautifulSoup.

The client is strictly READ-ONLY. In particular it never requests URLs
with ``zmien_status_zrobienia`` (marks homework as done) and never opens
individual messages (that would mark them as read).

Because this relies on the current HTML markup of mobidziennik.pl rather
than a documented API, it can break if the site's markup changes.
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time, timedelta

import aiohttp
from bs4 import BeautifulSoup, Tag

from .const import (
    BASE_URL_TEMPLATE,
    GRADES_PATH,
    HOMEWORK_DETAIL_PATH,
    HOMEWORK_PATH,
    LOGIN_FAILURE_MARKERS,
    LOGIN_PATH,
    MESSAGES_PATH,
    TESTS_PATH,
    TIMETABLE_PATH,
)

_LOGGER = logging.getLogger(__name__)

_MONTHS_PL = {
    "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4,
    "maja": 5, "czerwca": 6, "lipca": 7, "sierpnia": 8,
    "września": 9, "października": 10, "listopada": 11, "grudnia": 12,
}
_MONTHS_PL_SHORT = {
    "sty": 1, "lut": 2, "mar": 3, "kwi": 4, "maj": 5, "cze": 6,
    "lip": 7, "sie": 8, "wrz": 9, "paź": 10, "lis": 11, "gru": 12,
}

_DATETIME_RE = re.compile(
    r"(\d{1,2})\s+(\w+)\s+(\d{4}),\s*godzina\s*(\d{1,2}):(\d{2}):(\d{2})"
)
_LONG_DATE_RE = re.compile(r"(\d{1,2})\s+([^\W\d_]+)\s+(\d{4})")
_SHORT_DATE_RE = re.compile(r"(\d{1,2})\s+([^\W\d_]{3})\w*\s+(\d{4})")
_TIME_RANGE_RE = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")


def _clean(text: str | None) -> str | None:
    """Collapse whitespace; return None for empty strings."""
    if text is None:
        return None
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def parse_entered(text: str | None) -> datetime | None:
    """Parse "piątek, 4 września 2026, godzina 12:29:52" (local wall clock)."""
    if not text:
        return None
    match = _DATETIME_RE.search(text)
    if not match:
        return None
    day, month_name, year, hour, minute, second = match.groups()
    month = _MONTHS_PL.get(month_name.lower())
    if month is None:
        return None
    try:
        return datetime(int(year), month, int(day), int(hour), int(minute), int(second))
    except ValueError:
        return None


def parse_long_date(text: str | None) -> date | None:
    """Parse "czwartek, 12 listopada 2026" or "12 listopada 2026"."""
    if not text:
        return None
    match = _LONG_DATE_RE.search(text)
    if not match:
        return None
    month = _MONTHS_PL.get(match.group(2).lower())
    if month is None:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(1)))
    except ValueError:
        return None


def parse_short_date(text: str | None) -> date | None:
    """Parse "12 lis 2026"."""
    if not text:
        return None
    match = _SHORT_DATE_RE.search(text)
    if not match:
        return None
    month = _MONTHS_PL_SHORT.get(match.group(2).lower())
    if month is None:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(1)))
    except ValueError:
        return None


def _parse_time_range(text: str | None) -> tuple[dt_time | None, dt_time | None]:
    if not text:
        return None, None
    match = _TIME_RANGE_RE.search(text)
    if not match:
        return None, None
    h1, m1, h2, m2 = (int(g) for g in match.groups())
    return dt_time(h1, m1), dt_time(h2, m2)


def _to_float(text: str | None) -> float | None:
    if not text:
        return None
    match = re.search(r"-?\d+(?:[.,]\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


class MobiDziennikError(Exception):
    """Base error for the mobiDziennik client."""


class MobiDziennikAuthError(MobiDziennikError):
    """Raised when login fails or the session has expired."""


@dataclass
class Grade:
    """A single grade entry."""

    subject: str
    symbol: str  # e.g. "5", "4+", "6p", "np"
    category: str | None  # e.g. "sprawdzian", "kartkówka"
    topic: str | None  # short description shown next to the grade
    value: float | None  # "Wartość oceny" (0 for descriptive grades)
    counts_to_average: bool | None
    weight: int | None
    weight_label: str | None  # e.g. "Bardzo ważna"
    entered_at: datetime | None
    teacher: str | None
    comment: str | None
    grade_id: str | None


@dataclass
class Lesson:
    """A single timetable entry with a concrete date."""

    day: date
    start: dt_time | None
    end: dt_time | None
    subject: str
    class_group: str | None
    teacher: str | None
    room: str | None
    is_substitution: bool = False


@dataclass
class Test:
    """An announced test/quiz."""

    day: date
    time: str | None
    subject: str
    kind: str | None  # "sprawdzian", "kartkówka", "inne"
    topic: str | None
    class_group: str | None
    teacher: str | None


@dataclass
class Homework:
    """A homework assignment."""

    homework_id: str
    due: date | None
    lesson_time: str | None
    subject: str
    teacher: str | None
    content: str | None
    done: bool


@dataclass
class Message:
    """Header of an inbox message (never opened by this client)."""

    subject: str
    sender: str | None
    received: str | None
    unread: bool


@dataclass
class StudentData:
    """Everything scraped for a single student on the account."""

    name: str
    grades: list[Grade] = field(default_factory=list)
    averages: dict[str, float] = field(default_factory=dict)
    lessons: list[Lesson] = field(default_factory=list)
    days_off: dict[date, str] = field(default_factory=dict)
    tests: list[Test] = field(default_factory=list)
    homework: list[Homework] = field(default_factory=list)


@dataclass
class AccountData:
    """Snapshot returned by MobiDziennikClient.async_get_all()."""

    students: dict[str, StudentData]
    messages: list[Message]

    @property
    def unread_messages(self) -> list[Message]:
        return [m for m in self.messages if m.unread]


def slugify_name(name: str) -> str:
    """Turn a student's display name into a stable id fragment."""
    normalized = (
        name.lower()
        .replace("ą", "a").replace("ć", "c").replace("ę", "e")
        .replace("ł", "l").replace("ń", "n").replace("ó", "o")
        .replace("ś", "s").replace("ź", "z").replace("ż", "z")
    )
    return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")


def _student_from_heading(text: str, suffix: str) -> str | None:
    """Extract "Kowalski Jan" from "Kowalski Jan - <suffix>..."."""
    idx = text.find(f" - {suffix}")
    if idx <= 0:
        return None
    return text[:idx].strip()


class MobiDziennikClient:
    """Thin async scraping client for a single mobiDziennik account."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        school_id: str,
        email: str,
        password: str,
    ) -> None:
        self._session = session
        self._school_id = school_id
        self._email = email
        self._password = password
        self._base_url = BASE_URL_TEMPLATE.format(school_id=school_id)
        self._logged_in = False
        # Homework content is only available on a per-item page; cache it
        # so each assignment is fetched once.
        self._homework_content: dict[str, str | None] = {}

    @property
    def base_url(self) -> str:
        return self._base_url

    # ------------------------------------------------------------------
    # HTTP / session handling
    # ------------------------------------------------------------------

    @staticmethod
    def _is_login_page(html: str) -> bool:
        return any(marker in html for marker in LOGIN_FAILURE_MARKERS)

    async def _fetch(self, path: str) -> str:
        if "zmien_status" in path:
            raise MobiDziennikError("Refusing to call a state-changing URL")
        url = f"{self._base_url}{path}"
        try:
            async with self._session.get(url) as resp:
                resp.raise_for_status()
                return await resp.text()
        except aiohttp.ClientError as err:
            raise MobiDziennikError(f"GET {path} failed: {err}") from err

    async def _get(self, path: str) -> str:
        """GET a page, logging in (again) if the session has expired."""
        await self._ensure_logged_in()
        html = await self._fetch(path)
        if self._is_login_page(html):
            _LOGGER.debug("Session expired, logging in again")
            self._logged_in = False
            await self.async_login()
            html = await self._fetch(path)
            if self._is_login_page(html):
                raise MobiDziennikAuthError("Still not logged in after re-login")
        return html

    async def async_login(self) -> None:
        """Log in with a plain form POST and keep the session cookie."""
        url = f"{self._base_url}{LOGIN_PATH}"
        data = {"login": self._email, "haslo": self._password}
        try:
            async with self._session.post(url, data=data) as resp:
                resp.raise_for_status()
                html = await resp.text()
        except aiohttp.ClientError as err:
            raise MobiDziennikError(f"Login request failed: {err}") from err
        if self._is_login_page(html):
            self._logged_in = False
            raise MobiDziennikAuthError(
                "mobiDziennik rejected the login - check the credentials."
            )
        self._logged_in = True

    async def _ensure_logged_in(self) -> None:
        if not self._logged_in:
            await self.async_login()

    # ------------------------------------------------------------------
    # Grades
    # ------------------------------------------------------------------

    _GRADE_HEADING_RE = re.compile(
        r"^(?P<student>.+?) - (oceny cząstkowe|oceny klasyfikacyjne|oceny z dziennika)"
    )
    _TOOLTIP_LABELS = (
        "Wartość oceny",
        "Liczona do średniej",
        "Średnia ocen",
        "Wpisano",
        "Wpisał(a)",
        "Waga",
        "Opis oceny",
        "Komentarz",
    )

    async def async_get_grades(self) -> dict[str, tuple[list[Grade], dict[str, float]]]:
        """Return (grades, subject averages) per student."""
        soup = BeautifulSoup(await self._get(GRADES_PATH), "lxml")
        content = soup.find(id="content")
        result: dict[str, tuple[list[Grade], dict[str, float]]] = {}
        if content is None:
            return result

        for heading in content.find_all("h1"):
            match = self._GRADE_HEADING_RE.match(heading.get_text(" ", strip=True))
            if not match:
                continue
            student = match.group("student").strip()
            table = heading.find_next_sibling("table")
            if table is None:
                continue
            grades, averages = result.setdefault(student, ([], {}))
            for row in table.find_all("tr", class_="naglowek3"):
                tds = row.find_all("td")
                if len(tds) < 2:
                    continue
                subject, average = self._parse_subject_cell(tds[0])
                if average is not None:
                    averages[subject] = average
                grades.extend(self._parse_grade_cell(subject, tds[1]))
        return result

    @staticmethod
    def _parse_subject_cell(td: Tag) -> tuple[str, float | None]:
        small = td.find("small")
        average = None
        if small is not None:
            average = _to_float(small.get_text(" ", strip=True).split(":")[-1])
            small.extract()
        return _clean(td.get_text(" ", strip=True)) or "?", average

    def _parse_grade_cell(self, subject: str, td: Tag) -> list[Grade]:
        grades: list[Grade] = []
        category: str | None = None
        for node in td.children:
            if not isinstance(node, Tag):
                continue
            if node.name == "span":
                # Coloured category label, e.g. " kartkówka:"
                category = _clean(node.get_text(" ", strip=True).rstrip(":"))
            elif node.name == "a" and "info" in (node.get("class") or []):
                grades.append(self._parse_grade_anchor(subject, category, node))
        return grades

    def _parse_grade_anchor(self, subject: str, category: str | None, anchor: Tag) -> Grade:
        strong = anchor.find("strong")
        symbol = strong.get_text(strip=True) if strong else anchor.get_text(strip=True)
        topic_tag = anchor.find("small", recursive=False)
        topic = _clean(topic_tag.get_text(" ", strip=True).strip("()")) if topic_tag else None

        fields: dict[str, str] = {}
        tooltip = anchor.find("span")
        if tooltip is not None:
            text = tooltip.get_text("\n", strip=True)
            pattern = "|".join(re.escape(lbl) for lbl in self._TOOLTIP_LABELS)
            labels = re.findall(f"({pattern}):", text)
            parts = re.split(f"(?:{pattern}):", text)
            for label, value in zip(labels, parts[1:]):
                fields[label] = _clean(value) or ""

        weight_raw = fields.get("Waga")
        weight = None
        weight_label = None
        if weight_raw:
            num = re.search(r"\((\d+)\)", weight_raw)
            weight = int(num.group(1)) if num else None
            weight_label = _clean(re.sub(r"\(\d+\)", "", weight_raw))

        counts = fields.get("Liczona do średniej")
        rel = anchor.get("rel")
        return Grade(
            subject=subject,
            symbol=symbol,
            category=category,
            topic=topic,
            value=_to_float(fields.get("Wartość oceny")),
            counts_to_average=counts.lower().startswith("tak") if counts else None,
            weight=weight,
            weight_label=weight_label,
            entered_at=parse_entered(fields.get("Wpisano")),
            teacher=fields.get("Wpisał(a)") or None,
            comment=fields.get("Komentarz") or fields.get("Opis oceny") or None,
            grade_id=" ".join(rel) if isinstance(rel, list) else rel,
        )

    # ------------------------------------------------------------------
    # Timetable
    # ------------------------------------------------------------------

    async def async_get_timetable(
        self, week: date | None = None
    ) -> dict[str, tuple[list[Lesson], dict[date, str]]]:
        """Return (lessons, days off) per student for the week containing `week`."""
        path = f"{TIMETABLE_PATH}?typ=podstawowy"
        if week is not None:
            path += f"&tydzien={week.isoformat()}"
        soup = BeautifulSoup(await self._get(path), "lxml")
        content = soup.find(id="content")
        result: dict[str, tuple[list[Lesson], dict[date, str]]] = {}
        if content is None:
            return result

        for block in content.find_all("div", class_="plany-cnt"):
            heading = block.find(["h1", "h2"])
            if heading is None:
                continue
            student = heading.get_text(" ", strip=True).split("Drukuj")[0].strip()

            # Column headers carry the date in their title, e.g.
            # "11 listopada 2026 (Narodowe Święto Niepodległości)".
            day_dates: list[date | None] = []
            days_off: dict[date, str] = {}
            top = block.find("div", class_="plansc_top")
            if top is not None:
                for col in top.find_all("div", recursive=False):
                    title = col.get("title", "")
                    col_date = parse_long_date(title)
                    day_dates.append(col_date)
                    if col_date and col.find(class_="plansc_dw"):
                        reason = re.search(r"\(([^)]+)\)", title)
                        days_off[col_date] = reason.group(1) if reason else "Dzień wolny"

            lessons: list[Lesson] = []
            for box in block.find_all("div", class_="bx"):
                lesson = self._parse_lesson_box(box, day_dates)
                if lesson is not None:
                    lessons.append(lesson)
            lessons.sort(key=lambda l: (l.day, l.start or dt_time(0)))
            result[student] = (lessons, days_off)
        return result

    @staticmethod
    def _parse_lesson_box(box: Tag, day_dates: list[date | None]) -> Lesson | None:
        left = re.search(r"left:\s*([\d.]+)%", box.get("style", ""))
        if not left:
            return None
        # Columns sit at ~0.5, 20.5, 40.5, 60.5, 80.5 % for Mon..Fri.
        col = round((float(left.group(1)) - 0.5) / 20)
        if col < 0 or col >= len(day_dates) or day_dates[col] is None:
            return None

        # The title attribute holds the full description, lines separated
        # by <br />: [zastępstwo,] "07:05 - 07:50", subject, then either
        # "6 a - Nowak Anna (sala 11)" or "2 a", "Wiśniewska Maria".
        title_html = box.get("title", "")
        lines = [
            _clean(BeautifulSoup(part, "lxml").get_text(" ", strip=True))
            for part in re.split(r"<br\s*/?>", title_html)
        ]
        lines = [l for l in lines if l]
        is_substitution = "lz" in (box.get("class") or [])
        if lines and lines[0].lower() == "zastępstwo":
            is_substitution = True
            lines = lines[1:]
        if not lines:
            return None
        start, end = _parse_time_range(lines[0])
        if start is not None:
            lines = lines[1:]
        subject = lines[0] if lines else "?"
        extra = lines[1:]

        class_group = teacher = room = None
        combined = next((l for l in extra if " - " in l), None)
        if combined is not None:
            room_match = re.search(r"\(([^)]+)\)\s*$", combined)
            if room_match:
                room = room_match.group(1)
                combined = combined[: room_match.start()].strip()
            class_group, _, teacher = combined.partition(" - ")
        elif extra:
            class_group = extra[0]
            teacher = " ".join(extra[1:]) or None

        if room is None:
            # Younger grades: room only in the visible box text.
            room_match = re.search(r"\(([^)]+)\)\s*$", box.get_text(" ", strip=True))
            room = room_match.group(1) if room_match else None
        if room and re.match(r"sala \d", room, re.I):
            room = room[5:]

        return Lesson(
            day=day_dates[col],
            start=start,
            end=end,
            subject=subject,
            class_group=_clean(class_group),
            teacher=_clean(teacher),
            room=_clean(room),
            is_substitution=is_substitution,
        )

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    async def async_get_tests(self) -> dict[str, list[Test]]:
        """Return upcoming announced tests per student."""
        soup = BeautifulSoup(await self._get(TESTS_PATH), "lxml")
        content = soup.find(id="content")
        result: dict[str, list[Test]] = {}
        if content is None:
            return result
        student: str | None = None
        for row in content.find_all("tr"):
            h1 = row.find("h1")
            if h1 is not None:
                student = _student_from_heading(h1.get_text(" ", strip=True), "najbliższe sprawdziany")
                if student:
                    result.setdefault(student, [])
                continue
            if student is None:
                continue
            tds = row.find_all("td", recursive=False)
            if len(tds) < 6:
                continue
            day = parse_short_date(tds[0].get_text(" ", strip=True))
            if day is None:
                continue
            small = tds[0].find("small")
            time_match = _TIME_RE.search(small.get_text() if small else "")

            def full(td: Tag) -> str | None:
                tip = td.find(class_="autoTooltip")
                if tip is not None and tip.get("title"):
                    return _clean(tip["title"])
                return _clean(td.get_text(" ", strip=True))

            teacher_tip = tds[5].find("strong")
            result[student].append(
                Test(
                    day=day,
                    time=time_match.group(0) if time_match else None,
                    class_group=full(tds[1]),
                    subject=full(tds[2]) or "?",
                    kind=full(tds[3]),
                    topic=_clean(tds[4].get_text(" ", strip=True)),
                    teacher=_clean(teacher_tip.get_text()) if teacher_tip else None,
                )
            )
        return result

    # ------------------------------------------------------------------
    # Homework
    # ------------------------------------------------------------------

    async def async_get_homework(self) -> dict[str, list[Homework]]:
        """Return upcoming homework per student (with full content)."""
        soup = BeautifulSoup(await self._get(HOMEWORK_PATH), "lxml")
        content = soup.find(id="content")
        result: dict[str, list[Homework]] = {}
        if content is None:
            return result
        for h1 in content.find_all("h1"):
            student = _student_from_heading(h1.get_text(" ", strip=True), "najbliższe zadania domowe")
            if not student:
                continue
            items = result.setdefault(student, [])
            table = h1.find_next("table")
            # "Brak zadań domowych." has no table - make sure we did not
            # grab the next student's table instead.
            if table is None or table.find_previous("h1") is not h1:
                continue
            for row in table.find_all("tr", class_="podswietl"):
                hw_id = row.get("id_zadania")
                pupil = row.get("uczen")
                tds = row.find_all("td", recursive=False)
                if not hw_id or len(tds) < 6:
                    continue
                small = tds[0].find("small")
                lesson_time = _clean(small.get_text()) if small else None
                teacher_tip = tds[2].find("strong")
                done_img = tds[5].find("img")
                items.append(
                    Homework(
                        homework_id=hw_id,
                        due=parse_long_date(tds[0].get_text(" ", strip=True)),
                        lesson_time=lesson_time,
                        subject=_clean(tds[1].get_text(" ", strip=True)) or "?",
                        teacher=_clean(teacher_tip.get_text()) if teacher_tip else None,
                        content=await self._homework_text(hw_id, pupil, tds[3]),
                        done=bool(done_img and done_img.get("alt") == "tak"),
                    )
                )
        return result

    async def _homework_text(self, hw_id: str, pupil: str | None, cell: Tag) -> str | None:
        """Full homework text from the (read-only) detail page, cached."""
        if hw_id in self._homework_content:
            return self._homework_content[hw_id]
        text = _clean(cell.get_text(" ", strip=True))  # truncated fallback
        if pupil:
            try:
                await self._pause()
                html = await self._get(
                    f"{HOMEWORK_DETAIL_PATH}?id_zadania={hw_id}&uczen={pupil}&o=zadaniadomowe"
                )
                detail = BeautifulSoup(html, "lxml")
                for tr in detail.find_all("tr"):
                    cells = tr.find_all(["td", "th"], recursive=False)
                    if len(cells) >= 2 and cells[0].get_text(strip=True).startswith("Treść zadania"):
                        text = _clean(cells[1].get_text(" ", strip=True)) or text
                        break
                self._homework_content[hw_id] = text
            except MobiDziennikError as err:
                _LOGGER.debug("Could not fetch homework %s details: %s", hw_id, err)
        return text

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def async_get_messages(self) -> list[Message]:
        """Return inbox headers (first page, newest first). Never opens messages."""
        soup = BeautifulSoup(
            await self._get(f"{MESSAGES_PATH}?sortuj_wg=otrzymano&sortuj_typ=desc&odebrane=1"),
            "lxml",
        )
        messages: list[Message] = []
        for row in soup.find_all("tr", class_="podswietl"):
            tds = row.find_all("td")
            if len(tds) < 6:
                continue
            sender_td = tds[3]
            role = sender_td.find("small")
            if role is not None:
                role.extract()
            messages.append(
                Message(
                    subject=_clean(tds[0].get_text(" ", strip=True)) or "?",
                    sender=_clean(sender_td.get_text(" ", strip=True)),
                    received=_clean(tds[4].get_text(" ", strip=True)),
                    unread="Tak" not in tds[5].get_text(strip=True),
                )
            )
        return messages

    # ------------------------------------------------------------------
    # Everything
    # ------------------------------------------------------------------

    async def _pause(self) -> None:
        """Small random gap between page loads so a refresh is not a burst."""
        await asyncio.sleep(random.uniform(1.0, 4.0))

    async def async_get_all(self, today: date | None = None) -> AccountData:
        """Fetch everything needed by the sensors (5-6 page loads)."""
        today = today or date.today()
        grades = await self.async_get_grades()
        await self._pause()
        this_week = await self.async_get_timetable(today)
        # Next week's plan is only needed once this week has no lessons
        # left (Friday afternoon / weekend) - saves a request most of the time.
        next_week: dict[str, tuple[list[Lesson], dict[date, str]]] = {}
        if not any(l.day > today for lessons, _ in this_week.values() for l in lessons):
            await self._pause()
            next_week = await self.async_get_timetable(today + timedelta(days=7 - today.weekday()))
        await self._pause()
        tests = await self.async_get_tests()
        await self._pause()
        homework = await self.async_get_homework()
        await self._pause()
        messages = await self.async_get_messages()

        names = set(grades) | set(this_week) | set(next_week)
        students: dict[str, StudentData] = {}
        for name in sorted(names):
            g, avg = grades.get(name, ([], {}))
            l1, off1 = this_week.get(name, ([], {}))
            l2, off2 = next_week.get(name, ([], {}))
            students[name] = StudentData(
                name=name,
                grades=g,
                averages=avg,
                lessons=l1 + l2,
                days_off={**off1, **off2},
                tests=sorted(tests.get(name, []), key=lambda t: (t.day, t.time or "")),
                homework=sorted(homework.get(name, []), key=lambda h: (h.due or date.max)),
            )
        return AccountData(students=students, messages=messages)

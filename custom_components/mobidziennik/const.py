"""Constants for the mobiDziennik integration."""
from datetime import timedelta

DOMAIN = "mobidziennik"

CONF_SCHOOL_ID = "school_id"

# Initial value only - the coordinator re-randomises it every cycle.
DEFAULT_SCAN_INTERVAL = timedelta(minutes=60)

BASE_URL_TEMPLATE = "https://{school_id}.mobidziennik.pl"

LOGIN_PATH = "/dziennik"
GRADES_PATH = "/dziennik/oceny/"
TIMETABLE_PATH = "/dziennik/planlekcji"
MESSAGES_PATH = "/dziennik/wiadomosci/"
TESTS_PATH = "/dziennik/sprawdziany"
HOMEWORK_PATH = "/dziennik/zadaniadomowe"
HOMEWORK_DETAIL_PATH = "/dziennik/wyslijzadanie/"
ATTENDANCE_PATH = "/dziennik/obecnosci"
BEHAVIOUR_PATH = "/dziennik/zachowanie"
CALENDAR_PATH = "/dziennik/kalendarzklasowy"

# Attendance, behaviour and the class calendar change rarely: fetch them
# at most this often (on top of the normal randomised polling).
SLOW_REFRESH = timedelta(hours=4)

# HA bus events fired when the coordinator sees new items.
EVENT_NEW_GRADE = "mobidziennik_new_grade"
EVENT_NEW_REMARK = "mobidziennik_new_remark"
EVENT_NEW_ABSENCE = "mobidziennik_new_absence"

# Text fragments mobiDziennik returns when the session is not authenticated
# or credentials were rejected. Reverse engineered from the live HTML -
# if mobiDziennik changes its login page wording, update these.
LOGIN_FAILURE_MARKERS = (
    "Nie jestes zalogowany",
    "przypomnij_haslo_email",
    "Podano niepoprawny login i/lub hasło",
)

# mobiDziennik allows ONE session per account: a login from another
# browser/device (or another HA instance) ends ours and redirects every
# request to this page, which has none of the markers above.
AUTO_LOGOUT_PATH = "/helper/autowylogowanie"
AUTO_LOGOUT_MARKERS = (
    "auto wylogowanie",
    "autowylogowanie",
)

# How many days back the "recent grades" sensor looks.
RECENT_GRADES_DAYS = 7

# Language-independent object ids. Home Assistant would otherwise build
# entity ids from the translated name (e.g. "..._nastepna_lekcja" on a
# Polish system), which breaks copy-paste examples. Keys are translation
# keys; values keep the ids used since v0.2.
OBJECT_IDS = {
    "next_lesson": "next_lesson",
    "today_lessons": "today_lessons",
    "next_school_day": "next_school_day",
    "last_grade": "latest_grade",
    "recent_grades": "grades_last_7_days",
    "average": "average_grade",
    "next_test": "next_test",
    "homework": "homework",
    "attendance": "attendance",
    "unexcused_absences": "unexcused_absences",
    "behaviour_points": "behaviour_points",
    "last_remark": "latest_remark",
    "class_calendar": "class_calendar",
}

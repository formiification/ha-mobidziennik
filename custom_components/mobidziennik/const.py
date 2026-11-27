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

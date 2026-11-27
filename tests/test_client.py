"""Session handling: the auto-logout page must trigger a fresh login."""
import asyncio

import pytest

from mdz_loader import api


class _Resp:
    def __init__(self, url, text):
        self.url, self._text = url, text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    async def text(self):
        return self._text


class FakeSession:
    """GET returns queued pages; POST (login) always succeeds."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.logins = 0

    def get(self, url):
        final, text = self.pages.pop(0)
        return _Resp(final, text)

    def post(self, url, data):
        self.logins += 1
        return _Resp(url.replace("/dziennik", "/dziennik/historia"), "<div id='content'>wyloguj</div>")


def test_relogin_after_auto_logout(fixture_html):
    good = "<div id='content'>ok</div>"
    session = FakeSession([
        ("https://s.mobidziennik.pl/helper/autowylogowanie", fixture_html("autowylogowanie.html")),
        ("https://s.mobidziennik.pl/dziennik/oceny/", good),
    ])
    client = api.MobiDziennikClient(session, "s", "u", "p")
    html = asyncio.run(client._get("/dziennik/oceny/"))
    assert html == good
    assert session.logins == 2  # initial login + re-login after takeover


def test_still_logged_out_raises(fixture_html):
    page = ("https://s.mobidziennik.pl/helper/autowylogowanie", fixture_html("autowylogowanie.html"))
    client = api.MobiDziennikClient(FakeSession([page, page]), "s", "u", "p")
    with pytest.raises(api.MobiDziennikAuthError):
        asyncio.run(client._get("/dziennik/oceny/"))


def test_refuses_state_changing_url():
    client = api.MobiDziennikClient(FakeSession([]), "s", "u", "p")
    client._logged_in = True
    with pytest.raises(api.MobiDziennikError):
        asyncio.run(client._get("/dziennik/zmien_status_zrobienia?id=1"))

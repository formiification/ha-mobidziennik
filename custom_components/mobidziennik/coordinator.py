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
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

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
            return await self.client.async_get_all(dt_util.now().date())
        except MobiDziennikAuthError as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except MobiDziennikError as err:
            raise UpdateFailed(f"Error communicating with mobiDziennik: {err}") from err


def build_client(hass: HomeAssistant, school_id: str, email: str, password: str) -> MobiDziennikClient:
    """Create a client with its own cookie jar (one session per account)."""
    session = async_create_clientsession(hass)
    return MobiDziennikClient(session, school_id, email, password)

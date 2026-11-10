"""Config flow for mobiDziennik."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MobiDziennikAuthError, MobiDziennikClient, MobiDziennikError
from .const import CONF_SCHOOL_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SCHOOL_ID): str,
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class MobiDziennikConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for mobiDziennik."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            school_id = user_input[CONF_SCHOOL_ID].strip()
            email = user_input[CONF_EMAIL].strip()
            password = user_input[CONF_PASSWORD]

            await self.async_set_unique_id(f"{school_id}:{email}".lower())
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            client = MobiDziennikClient(session, school_id, email, password)

            try:
                await client.async_login()
            except MobiDziennikAuthError:
                errors["base"] = "invalid_auth"
            except MobiDziennikError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating mobiDziennik credentials")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"mobiDziennik ({school_id})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "school_id_hint": "e.g. 'myschool' from myschool.mobidziennik.pl"
            },
        )

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
import logging
from typing import TypeVar

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import MgIndiaApiError, MgIndiaClient, Snapshot
from .const import DEFAULT_SCAN_INTERVAL_SECONDS, DOMAIN

_LOGGER = logging.getLogger(__name__)
_T = TypeVar("_T")


class MgIndiaCoordinator(DataUpdateCoordinator):
    def __init__(
        self,
        hass: HomeAssistant,
        client: MgIndiaClient,
        scan_interval_seconds: int = DEFAULT_SCAN_INTERVAL_SECONDS,
        fetch_charging: bool = True,
    ):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval_seconds),
        )
        self.client = client
        self.fetch_charging = fetch_charging
        self._command_lock = asyncio.Lock()
        self.command_in_progress = False
        self.command_name: str | None = None
        self.last_command_status: str | None = None
        self.last_command_error: str | None = None

    async def _async_update_data(self):
        if not self.fetch_charging:
            return await self.client.snapshot()
        # Same steps as client.snapshot(), but the status poll also waits for
        # the EV charging frame so battery and charging entities stay current.
        client = self.client
        if not client.vehicle or client.vehicle.vin != client.vin:
            await client.vehicles()
        vehicle = client.vehicle
        if vehicle is None:
            raise MgIndiaApiError("No vehicle is available for a snapshot")
        caps = await client.refresh_capabilities()
        status = await client.status(include_charge=True)
        if client.vin != vehicle.vin:
            raise MgIndiaApiError("VIN changed during snapshot")
        return Snapshot(vehicle, caps, status)

    async def async_run_command(
        self, name: str, operation: Callable[[], Awaitable[_T]]
    ) -> _T:
        if self._command_lock.locked():
            raise HomeAssistantError(
                f"Another MG remote command is already running: {self.command_name}"
            )
        async with self._command_lock:
            self.command_in_progress = True
            self.command_name = name
            self.last_command_status = "processing"
            self.last_command_error = None
            self.async_update_listeners()
            try:
                result = await operation()
                self.last_command_status = "refreshing"
                self.async_update_listeners()
                await self.async_request_refresh()
                self.last_command_status = "success"
                return result
            except Exception as err:
                self.last_command_status = "failed"
                self.last_command_error = str(err)
                raise
            finally:
                self.command_in_progress = False
                self.async_update_listeners()

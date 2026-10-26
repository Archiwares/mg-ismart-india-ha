from __future__ import annotations

import datetime

from homeassistant.components.device_tracker import SourceType, TrackerEntity

from .const import DOMAIN
from .entity import MgIndiaEntity


async def async_setup_entry(hass, entry, async_add_entities):
    c = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([MgLocation(c)])


class MgLocation(MgIndiaEntity, TrackerEntity):
    _attr_icon = "mdi:car-electric"

    def __init__(self, c):
        super().__init__(c, "location", "Location")
        self._fix = None
        self._remember_fix()

    def _remember_fix(self):
        # A car parked indoors often reports no GPS fix, so keep the last
        # position it did report rather than dropping to unknown.
        gps = self.status.gps if self.status else None
        if gps is not None and gps.has_fix:
            self._fix = gps

    def _handle_coordinator_update(self):
        self._remember_fix()
        super()._handle_coordinator_update()

    @property
    def source_type(self):
        return SourceType.GPS

    @property
    def latitude(self):
        return self._fix.latitude if self._fix else None

    @property
    def longitude(self):
        return self._fix.longitude if self._fix else None

    @property
    def location_accuracy(self):
        return 0

    @property
    def extra_state_attributes(self):
        f = self._fix
        if f is None:
            return {}
        return {
            "speed_kmh": f.speed_kmh,
            "heading": f.heading_deg,
            "altitude_m": f.altitude_m,
            "satellites": f.satellites,
            "gps_status": f.gps_status.name.lower() if f.gps_status is not None else None,
            "position_time": datetime.datetime.fromtimestamp(
                f.position_time, datetime.UTC
            ).isoformat()
            if f.position_time
            else None,
            "google_maps_url": "https://www.google.com/maps/search/?api=1&query="
            f"{f.latitude},{f.longitude}",
        }

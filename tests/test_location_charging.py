from __future__ import annotations

import asyncio
import dataclasses
import types

from mg_ismart_india_client import (
    Capabilities,
    ChargeStatus,
    GpsPosition,
    GpsStatus,
    Snapshot,
    Status,
    Vehicle,
)

VIN = "VIN12345678901234"


def _charge(**overrides):
    values = {
        f.name: None
        for f in dataclasses.fields(ChargeStatus)
        if f.default is dataclasses.MISSING
        and f.default_factory is dataclasses.MISSING
    }
    values.update(overrides)
    return ChargeStatus(**values)


def _coordinator(status, fetch_charging=True):
    return types.SimpleNamespace(
        data=Snapshot(Vehicle(VIN, "ZS EV"), Capabilities(), status),
        last_update_success=True,
        fetch_charging=fetch_charging,
    )


def _setup(platform_setup, coordinator):
    hass = types.SimpleNamespace(
        data={"mg_ismart_india": {"entry1": {"coordinator": coordinator}}}
    )
    added = []
    asyncio.run(
        platform_setup(hass, types.SimpleNamespace(entry_id="entry1"), added.extend)
    )
    return {entity._attr_name: entity for entity in added}


def test_location_keeps_last_fix_when_gps_drops():
    from custom_components.mg_ismart_india.device_tracker import MgLocation

    fix = GpsPosition(
        latitude=28.6129,
        longitude=77.2295,
        gps_status=GpsStatus.FIX_3D,
        position_time=1_760_000_000,
    )
    coordinator = _coordinator(Status(gps=fix))
    tracker = MgLocation(coordinator)
    assert (tracker.latitude, tracker.longitude) == (28.6129, 77.2295)
    assert tracker.extra_state_attributes["google_maps_url"].endswith(
        "query=28.6129,77.2295"
    )
    assert tracker.extra_state_attributes["gps_status"] == "fix_3d"

    coordinator.data = Snapshot(
        coordinator.data.vehicle,
        Capabilities(),
        Status(gps=GpsPosition(gps_status=GpsStatus.NO_SIGNAL)),
    )
    tracker._remember_fix()
    assert (tracker.latitude, tracker.longitude) == (28.6129, 77.2295)


def test_location_unknown_until_first_fix():
    from custom_components.mg_ismart_india.device_tracker import MgLocation

    tracker = MgLocation(_coordinator(Status()))
    assert tracker.latitude is None
    assert tracker.extra_state_attributes == {}


def test_battery_prefers_charging_frame_soc():
    from custom_components.mg_ismart_india.sensor import MgBatterySensor

    plugged = _coordinator(Status(fuel_level=80, charge=_charge(soc=81.5)))
    assert MgBatterySensor(plugged).native_value == 81.5
    unplugged = _coordinator(Status(fuel_level=80))
    assert MgBatterySensor(unplugged).native_value == 80


def test_charge_entities_follow_charging_frame():
    from custom_components.mg_ismart_india.binary_sensor import (
        async_setup_entry as setup_binary,
    )
    from custom_components.mg_ismart_india.sensor import (
        async_setup_entry as setup_sensors,
    )

    charging = _coordinator(
        Status(
            charge=_charge(
                is_charging=True,
                is_plugged_in=True,
                charging_voltage=400.0,
                charging_current=15.0,
                charge_time_remaining_min=95,
            )
        )
    )
    sensors = _setup(setup_sensors, charging)
    binaries = _setup(setup_binary, charging)
    assert sensors["Charging Power"].native_value == 6.0
    assert sensors["Charge Time Remaining"].native_value == 95
    assert binaries["Charging"].is_on is True
    assert binaries["Charger Plugged In"].is_on is True

    unplugged = _coordinator(Status())
    sensors = _setup(setup_sensors, unplugged)
    binaries = _setup(setup_binary, unplugged)
    assert sensors["Charging Power"].native_value is None
    assert binaries["Charging"].is_on is False
    assert binaries["Charger Plugged In"].is_on is False


def test_charge_entities_skipped_when_charging_fetch_disabled():
    from custom_components.mg_ismart_india.binary_sensor import (
        async_setup_entry as setup_binary,
    )
    from custom_components.mg_ismart_india.sensor import (
        async_setup_entry as setup_sensors,
    )

    coordinator = _coordinator(Status(), fetch_charging=False)
    names = set(_setup(setup_sensors, coordinator)) | set(
        _setup(setup_binary, coordinator)
    )
    assert "Battery" in names
    assert "Front Left Tyre Pressure" in names
    assert not names & {"Charging Power", "Charging", "Charger Plugged In"}


def test_coordinator_polls_status_with_charging_frame():
    from custom_components.mg_ismart_india.coordinator import MgIndiaCoordinator

    calls = []
    vehicle = Vehicle(VIN, "ZS EV")

    class Client:
        vin = VIN

        def __init__(self):
            self.vehicle = None

        async def vehicles(self):
            calls.append("vehicles")
            self.vehicle = vehicle

        async def refresh_capabilities(self):
            calls.append("capabilities")
            return Capabilities(climate=True)

        async def status(self, *, include_charge=False):
            calls.append(("status", include_charge))
            return Status(charge=_charge(soc=70.0))

    fake = types.SimpleNamespace(fetch_charging=True, client=Client())
    snap = asyncio.run(MgIndiaCoordinator._async_update_data(fake))
    assert calls == ["vehicles", "capabilities", ("status", True)]
    assert snap.vehicle is vehicle
    assert snap.status.charge.soc == 70.0


def test_climate_reports_cabin_temperature():
    from custom_components.mg_ismart_india.climate import MgClimate

    coordinator = _coordinator(Status(interior_temperature=41))
    climate = MgClimate(coordinator, types.SimpleNamespace(has_pin=True))
    assert climate.current_temperature == 41

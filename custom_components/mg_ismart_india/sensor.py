from __future__ import annotations
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfEnergy,
    UnitOfLength,
    UnitOfElectricPotential,
    UnitOfPower,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
)
from .const import DOMAIN
from .entity import MgIndiaEntity

SENSORS = [
    ("fuel_level", "Fuel Level", PERCENTAGE, SensorDeviceClass.BATTERY, None),
    ("range_km", "Range", UnitOfLength.KILOMETERS, None, None),
    (
        "odometer_km",
        "Odometer",
        UnitOfLength.KILOMETERS,
        SensorDeviceClass.DISTANCE,
        SensorStateClass.TOTAL_INCREASING,
    ),
    (
        "interior_temperature",
        "Interior Temperature",
        UnitOfTemperature.CELSIUS,
        SensorDeviceClass.TEMPERATURE,
        None,
    ),
    (
        "exterior_temperature",
        "Exterior Temperature",
        UnitOfTemperature.CELSIUS,
        SensorDeviceClass.TEMPERATURE,
        None,
    ),
    (
        "aux_battery_voltage",
        "Aux Battery Voltage",
        UnitOfElectricPotential.VOLT,
        SensorDeviceClass.VOLTAGE,
        None,
    ),
    ("status_time", "Vehicle Status Time", None, SensorDeviceClass.TIMESTAMP, None),
    (
        "last_can_activity",
        "Last Vehicle Activity",
        None,
        SensorDeviceClass.TIMESTAMP,
        None,
    ),
] + [
    (
        f"{tyre}_tyre_psi",
        f"{tyre.replace('_', ' ').title()} Tyre Pressure",
        UnitOfPressure.PSI,
        SensorDeviceClass.PRESSURE,
        SensorStateClass.MEASUREMENT,
    )
    for tyre in ("front_left", "front_right", "rear_left", "rear_right")
]

# Fields of status.charge, which is only present while the vehicle sends its
# charging frame (plugged in).
CHARGE_SENSORS = [
    (
        "charging_current",
        "Charging Current",
        UnitOfElectricCurrent.AMPERE,
        SensorDeviceClass.CURRENT,
    ),
    (
        "charging_voltage",
        "Charging Voltage",
        UnitOfElectricPotential.VOLT,
        SensorDeviceClass.VOLTAGE,
    ),
    (
        "battery_energy_kwh",
        "Battery Energy",
        UnitOfEnergy.KILO_WATT_HOUR,
        SensorDeviceClass.ENERGY_STORAGE,
    ),
    (
        "charge_time_remaining_min",
        "Charge Time Remaining",
        UnitOfTime.MINUTES,
        SensorDeviceClass.DURATION,
    ),
]


async def async_setup_entry(hass, entry, async_add_entities):
    c = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities = [MgIndiaSensor(c, *s) for s in SENSORS] + [
        MgBatterySensor(c),
        MgLastCommandSensor(c),
    ]
    if c.fetch_charging:
        entities += [MgChargeSensor(c, *s) for s in CHARGE_SENSORS]
        entities.append(MgChargingPowerSensor(c))
    async_add_entities(entities)


class MgIndiaSensor(MgIndiaEntity, SensorEntity):
    def __init__(self, c, key, name, unit, device_class, state_class):
        super().__init__(c, key, name)
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class

    @property
    def native_value(self):
        import datetime

        v = getattr(self.status, self._key, None) if self.status else None
        if self._attr_device_class == SensorDeviceClass.TIMESTAMP and isinstance(
            v, int
        ):
            return datetime.datetime.fromtimestamp(v, datetime.UTC)
        return v


class MgBatterySensor(MgIndiaEntity, SensorEntity):
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, c):
        super().__init__(c, "battery_soc", "Battery")

    @property
    def native_value(self):
        if not self.status:
            return None
        # The charging frame carries a finer SOC; fall back to the basic status.
        charge = self.status.charge
        if charge is not None and charge.soc is not None:
            return charge.soc
        return self.status.fuel_level


class MgChargeSensor(MgIndiaEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, c, key, name, unit, device_class):
        super().__init__(c, key, name)
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class

    @property
    def native_value(self):
        charge = self.status.charge if self.status else None
        return getattr(charge, self._key, None) if charge else None


class MgChargingPowerSensor(MgIndiaEntity, SensorEntity):
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, c):
        super().__init__(c, "charging_power", "Charging Power")

    @property
    def native_value(self):
        charge = self.status.charge if self.status else None
        if charge is None:
            return None
        return round(charge.charging_voltage * charge.charging_current / 1000, 2)


class MgLastCommandSensor(MgIndiaEntity, SensorEntity):
    def __init__(self, c):
        super().__init__(c, "last_remote_command", "Last Remote Command")

    @property
    def native_value(self):
        return getattr(self.coordinator, "last_command_status", None)

    @property
    def extra_state_attributes(self):
        return {
            "command": getattr(self.coordinator, "command_name", None),
            "error": getattr(self.coordinator, "last_command_error", None),
        }

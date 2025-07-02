"""Support for the Daikin Madoka HVAC."""
import logging

from pymadoka import (
    ConnectionException,
    Controller,
    FanSpeedEnum,
    FanSpeedStatus,
    OperationModeEnum,
    OperationModeStatus,
    PowerStateStatus,
    SetPointStatus,
)
from pymadoka.connection import ConnectionStatus
from homeassistant.components.climate import ClimateEntity, HVACMode, HVACAction, ClimateEntityFeature
from homeassistant.components.climate.const import (
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    FAN_OFF,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature

from . import DOMAIN
from .const import CONTROLLERS, MAX_TEMP, MIN_TEMP

_LOGGER = logging.getLogger(__name__)

HA_MODE_TO_DAIKIN = {
    HVACMode.FAN_ONLY: OperationModeEnum.FAN,
    HVACMode.DRY: OperationModeEnum.DRY,
    HVACMode.COOL: OperationModeEnum.COOL,
    HVACMode.HEAT: OperationModeEnum.HEAT,
    HVACMode.AUTO: OperationModeEnum.AUTO,
    HVACMode.OFF: OperationModeEnum.AUTO,
}

DAIKIN_TO_HA_MODE = {
    OperationModeEnum.FAN: HVACMode.FAN_ONLY,
    OperationModeEnum.DRY: HVACMode.DRY,
    OperationModeEnum.COOL: HVACMode.COOL,
    OperationModeEnum.HEAT: HVACMode.HEAT,
    OperationModeEnum.AUTO: HVACMode.AUTO,
}

HA_FAN_MODE_TO_DAIKIN = {
    FAN_LOW: FanSpeedEnum.LOW,
    FAN_MEDIUM: FanSpeedEnum.MID,
    FAN_HIGH: FanSpeedEnum.HIGH,
    FAN_AUTO: FanSpeedEnum.AUTO,
}

DAIKIN_TO_HA_FAN_MODE = {
    FanSpeedEnum.LOW: FAN_LOW,
    FanSpeedEnum.MID: FAN_MEDIUM,
    FanSpeedEnum.HIGH: FAN_HIGH,
    FanSpeedEnum.AUTO: FAN_AUTO,
}

DAIKIN_TO_HA_CURRENT_HVAC_MODE = {
    OperationModeEnum.FAN: HVACAction.FAN,
    OperationModeEnum.DRY: HVACAction.DRYING,
    OperationModeEnum.COOL: HVACAction.COOLING,
    OperationModeEnum.HEAT: HVACAction.HEATING,
}

DATA = "data"


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Daikin climate based on config_entry."""

    if entry.entry_id in hass.data[DOMAIN]:
        entities = []
        for controller in hass.data[DOMAIN][entry.entry_id][CONTROLLERS].values():
            try:
                entity = DaikinMadokaClimate(controller)
                entities.append(entity)
                await entity.controller.update()
            except ConnectionAbortedError:
                pass
            except ConnectionException:
                pass

        async_add_entities(entities, update_before_add=True)


class DaikinMadokaClimate(ClimateEntity):
    """Representation of a Daikin HVAC."""

    def __init__(self, controller: Controller):
        """Initialize the climate device."""
        self.controller = controller
        self.dev_info = None

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return (
          ClimateEntityFeature.TARGET_TEMPERATURE
          | ClimateEntityFeature.FAN_MODE
          | ClimateEntityFeature.TURN_ON
          | ClimateEntityFeature.TURN_OFF
        )
    @property
    def available(self):
        """Return the availability."""
        return (
            self.controller.connection.connection_status == ConnectionStatus.CONNECTED
        )

    @property
    def name(self):
        """Return the name of the thermostat, if any."""
        return (
            self.controller.connection.name
            if self.controller.connection.name is not None
            else self.controller.connection.address
        )

    @property
    def unique_id(self):
        """Return a unique ID."""
        return self.controller.connection.address

    @property
    def temperature_unit(self):
        """Return the unit of measurement which this thermostat uses."""
        return UnitOfTemperature.CELSIUS

    @property
    def current_temperature(self):
        """Return the current temperature."""
        if self.controller.temperatures.status is None:
            return None

        return self.controller.temperatures.status.indoor

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""

        if self.controller.set_point.status is None:
            return None

        value = None

        if self.hvac_mode == HVACMode.HEAT:
            value = self.controller.set_point.status.heating_set_point
        else:
            value = self.controller.set_point.status.cooling_set_point
        return value

    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        return 1

    @property
    def min_temp(self):
        """Return the minimum temperature."""
        return MIN_TEMP

    @property
    def max_temp(self):
        """Return the maximum temperature."""
        return MAX_TEMP

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        try:
            new_cooling_set_point = self.controller.set_point.status.cooling_set_point
            new_heating_set_point = self.controller.set_point.status.cooling_set_point
            if (
                self.controller.operation_mode.status.operation_mode
                != OperationModeEnum.HEAT
            ):
                new_cooling_set_point = round(kwargs.get(ATTR_TEMPERATURE))
            if (
                self.controller.operation_mode.status.operation_mode
                != OperationModeEnum.COOL
            ):
                new_heating_set_point = round(kwargs.get(ATTR_TEMPERATURE))

            await self.controller.set_point.update(
                SetPointStatus(new_cooling_set_point, new_heating_set_point)
            )
        except ConnectionAbortedError:
            # pylint: disable=logging-not-lazy
            _LOGGER.warning(
                "Could not set target temperature on %s. "
                + "Connection not available, please reload integration to try reenabling.",
                self.name,
            )
        except ConnectionException:
            pass

    @property
    def hvac_mode(self):
        """Return current operation ie. heat, cool, idle."""

        if self.controller.power_state.status is None:
            return None

        if self.controller.power_state.status.turn_on is False:
            return HVACMode.OFF

        return DAIKIN_TO_HA_MODE.get(
            self.controller.operation_mode.status.operation_mode
        )

    @property
    def hvac_modes(self):
        """Return the list of available operation modes."""
        return list(HA_MODE_TO_DAIKIN)

    @property
    def hvac_action(self):
        """Return the HVAC current action."""

        if self.controller.power_state.status is None:
            return None

        if self.controller.power_state.status.turn_on is False:
            return HVACAction.OFF

        if (
            self.controller.operation_mode.status.operation_mode
            == OperationModeEnum.AUTO
        ):
            # pylint: disable=no-else-return
            if self.target_temperature >= self.current_temperature:
                return HVACAction.HEATING
            else:
                return HVACAction.COOLING
        else:
            return DAIKIN_TO_HA_CURRENT_HVAC_MODE.get(
                self.controller.operation_mode.status.operation_mode
            )

    async def async_set_hvac_mode(self, hvac_mode):
        """Set HVAC mode."""
        try:
            if hvac_mode != HVACMode.OFF:
                await self.controller.operation_mode.update(
                    OperationModeStatus(HA_MODE_TO_DAIKIN.get(hvac_mode))
                )
            await self.controller.power_state.update(
                PowerStateStatus(hvac_mode != HVACMode.OFF)
            )

            self.async_schedule_update_ha_state()
        except ConnectionAbortedError:
            # pylint: disable=logging-not-lazy
            _LOGGER.warning(
                "Could not set HVAC mode on %s. "
                + "Connection not available, please reload integration to try reenabling.",
                self.name,
            )
        except ConnectionException:
            pass

    @property
    def fan_mode(self):
        """Return the fan setting."""

        if self.controller.fan_speed.status is None:
            return None
        # pylint: disable=no-else-return
        if self.hvac_mode == HVACMode.HEAT:
            return DAIKIN_TO_HA_FAN_MODE.get(
                self.controller.fan_speed.status.heating_fan_speed
            )
        else:
            return DAIKIN_TO_HA_FAN_MODE.get(
                self.controller.fan_speed.status.cooling_fan_speed
            )

    async def async_set_fan_mode(self, fan_mode):
        """Set fan mode."""
        try:

            await self.controller.fan_speed.update(
                FanSpeedStatus(
                    HA_FAN_MODE_TO_DAIKIN.get(fan_mode),
                    HA_FAN_MODE_TO_DAIKIN.get(fan_mode),
                )
            )
        except ConnectionAbortedError:
            # pylint: disable=logging-not-lazy
            _LOGGER.warning(
                "Could not set target fan mode on %s. "
                + "Connection not available, please reload integration to try reenabling.",
                self.name,
            )
        except ConnectionException:
            pass

    @property
    def fan_modes(self):
        """List of available fan modes."""
        return list(HA_FAN_MODE_TO_DAIKIN)

    async def async_update(self):
        """Retrieve latest state."""

        try:
            self.dev_info = await self.controller.read_info()
            await self.controller.update()

        except ConnectionAbortedError:
            # pylint: disable=logging-not-lazy
            _LOGGER.warning(
                "Could not update device status for %s. "
                + "Connection not available, please reload integration to try reenabling.",
                self.name,
            )
        except ConnectionException:
            pass

    async def async_turn_on(self):
        """Turn device on."""
        try:
            await self.controller.power_state.update(PowerStateStatus(True))
        except ConnectionAbortedError:
            # pylint: disable=logging-not-lazy
            _LOGGER.warning(
                "Could not turn on %s. "
                + "Connection not available, please reload integration to try reenabling.",
                self.name,
            )
        except ConnectionException:
            pass

    async def async_turn_off(self):
        """Turn device off."""
        try:
            await self.controller.power_state.update(PowerStateStatus(False))
        except ConnectionAbortedError:
            # pylint: disable=logging-not-lazy
            _LOGGER.warning(
                "Could not turn off %s. "
                + "Connection not available, please reload integration to try reenabling.",
                self.name,
            )
        except ConnectionException:
            pass

    @property
    def device_info(self):
        """Return a device description for device registry."""

        model = (
            ("BRC1H" + self.dev_info["Model Number String"])
            if "Model Number String" in self.dev_info
            else ""
        )
        sw_version = (
            self.dev_info["Software Revision String"]
            if "Software Revision String" in self.dev_info
            else ""
        )
        return {
            "identifiers": {
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self.unique_id)
            },
            "name": self.name,
            "manufacturer": "DAIKIN",
            "model": model,
            "sw_version": sw_version,
            "via_device": (DOMAIN, self.unique_id),
        }

"""
Support for reading IDM Terra data through IDM API
Author: Thomas Beyer (solarisproject.de)
Based on: https://github.com/cyberjunky/home-assistant-custom-components/blob/master/sensor/toon_smartmeter.py

configuration.yaml

sensor:
  - platform: idm_heating
    username: user
    password: password
    scan_interval: 300
    resources:
      - mode
      - circuit_mode
      - errors
      - heat_quantity
      - outside_temp
      - forerun_temp_actual
      - forerun_temp_target
      - room_temp_target
      - return_flow_temp
      - hygienic_temp
      - water_temp
"""
import logging
from datetime import timedelta
import hashlib
import requests
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
import homeassistant.helpers.config_validation as cv
from homeassistant.const import (
    CONF_USERNAME, CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_RESOURCES)
from homeassistant.util import Throttle
from homeassistant.helpers.entity import Entity

_LOGGER = logging.getLogger(__name__)

MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=300)

SENSOR_PREFIX = 'Heating '

SENSOR_TYPES = {
    'mode': ['mode', '', 'mdi:settings'],
    'circuit_mode': ['circuit mode', '', 'mdi:settings'],
    'errors': ['errors', '#', 'mdi:alert-circle'],
    'heat_quantity': ['heat quantity', 'kWh', 'mdi:radiator'],
    'outside_temp': ['outside temp.', '°C', 'mdi:thermometer'],
    'forerun_temp_actual': ['forerun temp. (actual)', '°C', 'mdi:temperature-celsius'],
    'forerun_temp_target': ['forerun temp. (target)', '°C', 'mdi:temperature-celsius'],
    'room_temp_target': ['room temp. (target)', '°C', 'mdi:thermometer'],
    'return_flow_temp': ['return flow temp.', '°C', 'mdi:temperature-celsius'],
    'hygienic_temp': ['hygienic temp.', '°C', 'mdi:temperature-celsius'],
    'water_temp': ['water temp.', '°C', 'mdi:temperature-celsius'],
}

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_USERNAME): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
    vol.Required(CONF_RESOURCES, default=[]):
        vol.All(cv.ensure_list, [vol.In(SENSOR_TYPES)]),
})

modeDictionary = {"icon_12": "Aus",
                  "icon_auto": "Automatik",
                  "icon_3": "Warmwasser oder Einmalige WW Ladung"}

circuitModeDictionary = {"icon_12": "Aus",
                         "icon_24": "Zeitprogramm",
                         "icon_21": "Normal",
                         "icon_11": "Eco",
                         "icon_5":  "manuell Heizen",
                         "icon_1":  "manuell Kühlen"}

idmHost = "https://www.myidm.at"
pathLogin = "/api/user/login"
pathInstallations = "/api/installation/values"
headers = {'User-Agent': 'IDM App (Android)'}


def setup_platform(hass, config, add_entities, discovery_info=None):
    _LOGGER.debug("Setup IDM Terra sensors")

    username = config.get(CONF_USERNAME)
    password = config.get(CONF_PASSWORD)
    passwordHashed = hashlib.sha1(password.encode()).hexdigest()
    scanInterval = config.get(CONF_SCAN_INTERVAL)

    try:
        data = IdmData(username, passwordHashed)
    except requests.exceptions.HTTPError as error:
        _LOGGER.error(error)
        return False

    entities = []

    for resource in config[CONF_RESOURCES]:
        sensor_type = resource.lower()

        if sensor_type not in SENSOR_TYPES:
            SENSOR_TYPES[sensor_type] = [
                sensor_type.title(), '', 'mdi:flash']

        entities.append(IdmHeatingSensor(data, sensor_type))

    add_entities(entities)


# pylint: disable=abstract-method
class IdmData(object):

    def __init__(self, username, password):
        self._username = username
        self._password = password
        self.data = None

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def update(self):
        _LOGGER.debug("Updating IDM Terra sensors with remote API")
        try:
            payload = {'username':  self._username, 'password': self._password}
            j = requests.post(idmHost + pathLogin,
                              headers=headers, data=payload, timeout=10).json()
            token = j["token"]
            installation = j["installations"][0]["id"]
            #_LOGGER.debug("Login Data = %s", j)
            #_LOGGER.debug("Token = %s", token)
            #_LOGGER.debug("Installation = %s", installation)

            payload = {'installation': installation, 'token': token}
            self.data = requests.post(
                idmHost + pathInstallations, headers=headers, data=payload, timeout=10).json()
            #_LOGGER.debug("Installation Data = %s", self.data)

        except requests.exceptions.RequestException as exc:
            _LOGGER.error("Error occurred while fetching data: %r", exc)
            self.data = None
            return False


class IdmHeatingSensor(Entity):

    def __init__(self, data, sensor_type):
        self.data = data
        self.type = sensor_type
        self._name = SENSOR_PREFIX + SENSOR_TYPES[self.type][0]
        self._unit = SENSOR_TYPES[self.type][1]
        self._icon = SENSOR_TYPES[self.type][2]
        self._state = None

    @property
    def name(self):
        return self._name

    @property
    def icon(self):
        return self._icon

    @property
    def state(self):
        return self._state

    @property
    def unit_of_measurement(self):
        return self._unit

    def update(self):
        self.data.update()
        heatingData = self.data.data

        try:
            if self.type == 'mode':
                for key, value in modeDictionary.items():
                    heatingData["mode"] = heatingData["mode"].replace(key, value)
                self._state = heatingData["mode"]

            elif self.type == 'circuit_mode':
                for key, value in circuitModeDictionary.items():
                    heatingData["circuits"][0]["mode"] = heatingData["circuits"][0]["mode"].replace(key, value)
                self._state = heatingData["circuits"][0]["mode"]

            elif self.type == 'errors':
                self._state = int(heatingData["error"])

            elif self.type == 'heat_quantity':
                self._state = float(heatingData["sum_heat"].rstrip(" kWh"))

            elif self.type == 'outside_temp':
                self._state = float(heatingData["temp_outside"].rstrip(" °C"))

            elif self.type == 'forerun_temp_actual':
                self._state = float(heatingData["circuits"][0]["temp_forerun_actual"].rstrip(" °C"))

            elif self.type == 'forerun_temp_target':
                self._state = float(heatingData["circuits"][0]["temp_forerun"].rstrip(" °C"))

            elif self.type == 'room_temp_target':
                self._state = float(heatingData["circuits"][0]["temp_room_value"])

            elif self.type == 'return_flow_temp':
                self._state = float(heatingData["temp_heat"].rstrip(" °C"))

            elif self.type == 'hygienic_temp':
                self._state = float(heatingData["temp_hygienic"].rstrip(" °C"))

            elif self.type == 'water_temp':
                self._state = float(heatingData["temp_water"].rstrip(" °C"))
        except ValueError:
            self._state = None


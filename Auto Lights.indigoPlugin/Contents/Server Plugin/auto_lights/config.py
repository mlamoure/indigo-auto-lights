import datetime
import json
from typing import List, Tuple

from auto_lights.auto_lights_config import AutoLightsConfig
from auto_lights.autumn_bedroom_zone import AutumnBedroomZone
from auto_lights.bedroom_hallway_zone import BedroomHallwayZone
from auto_lights.guest_bedroom_zone import GuestBedroomZone
from auto_lights.lighting_period import LightingPeriod
from auto_lights.mbr_zone import MBRZone
from auto_lights.not_while_eating_zone import NotWhileEatingZone
from auto_lights.zone import Zone

try:
    import indigo
except ImportError:
    pass


def load_config() -> Tuple[AutoLightsConfig, List[Zone]]:
    """
    Construct and return the AutoLightsConfig and configured lighting Zones for this script from auto_lights_conf.json.

    Returns:
        tuple: An AutoLightsConfig instance and a list of Zone (or subclass) objects with configured lightingPeriods.
    """

    with open("/Users/mike/Documents/indigo-scripts/auto_lights_conf.json", "r") as f:
        data = json.load(f)

    config = AutoLightsConfig()

    plugin_config = data.get("plugin_config", {})

    # Initialize config from plugin_config
    for key, value in plugin_config.items():
        if hasattr(config, key):
            setattr(config, key, value)

    zones = []
    for zone_data in data.get("zones", []):
        zone_type = zone_data.get("type", "Zone")
        name = zone_data.get("name", "Unknown")
        if zone_type == "AutumnBedroomZone":
            zone = AutumnBedroomZone(name, config)
        elif zone_type == "BedroomHallwayZone":
            zone = BedroomHallwayZone(name, config)
        elif zone_type == "GuestBedroomZone":
            zone = GuestBedroomZone(name, config)
        elif zone_type == "MBRZone":
            zone = MBRZone(name, config)
        elif zone_type == "NotWhileEatingZone":
            zone = NotWhileEatingZone(name, config)
        else:
            zone = Zone(name, config)

        # Set attributes from the JSON if they exist as properties on the zone
        for key, value in zone_data.items():
            if hasattr(zone, key):
                setattr(zone, key, value)

        # Convert lighting_periods from JSON to objects
        lighting_periods = zone_data.get("lighting_periods", [])
        new_periods = []
        for period in lighting_periods:
            lp = LightingPeriod(
                period["name"],
                period["mode"],
                datetime.time(*period["from_time"]),
                datetime.time(*period["to_time"]),
            )
            # Optionally set lock_duration if included
            if "lock_duration" in period:
                lp.lock_duration = period["lock_duration"]
            # Optionally set presence_devId if included
            if "presence_devId" in period:
                lp.presence_devId = period["presence_devId"]

            new_periods.append(lp)
            # indigo.server.log(f"Loaded lighting period: {lp.name}, mode: {lp.mode}, from: {lp.from_time}, to: {lp.to_time}")

        zone.lighting_periods = new_periods

        zones.append(zone)

    return config, zones

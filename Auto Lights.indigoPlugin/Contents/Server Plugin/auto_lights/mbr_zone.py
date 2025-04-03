import datetime

from auto_lights.auto_lights_config import AutoLightsConfig
from auto_lights.zone import Zone


class MBRZone(Zone):
    def __init__(self, name: str, config: AutoLightsConfig):
        super().__init__(name, config)
        self._start_reading_light_hour = None

    @property
    def start_reading_light_hour(self) -> int:
        return self._start_reading_light_hour

    @start_reading_light_hour.setter
    def start_reading_light_hour(self, value: int) -> None:
        self._start_reading_light_hour = value

    def run_special_rules(self) -> None:
        """
        Apply master bedroom-specific logic, such as reading vs overhead lights.

        Args:
            config (AutoLightsConfig): Provides state like goneToBed or presence.
        """
        if self.current_lighting_period.mode == "OffZone":
            return

        if self._config.gone_to_bed:
            self.target_brightness = 0
        elif (
            self.has_presence_detected()
            and self.is_dark()
            and datetime.datetime.now().time().hour >= self.start_reading_light_hour
        ):
            self.target_brightness = [0, 40, 40]
            self.special_rules_adjustment = (
                "turned on the reading lights instead of the main overhead lights."
            )
        elif self.has_presence_detected() and self.is_dark():
            self.target_brightness = [100, 0, 0]
            self.special_rules_adjustment = "turned on overhead lights only."

import datetime

try:
    import indigo
except ImportError:
    pass


class AutoLightsConfig:
    """
    Configuration handler for the auto_lights script, managing time-of-day logic, presence, and brightness values.
    """

    def __init__(self) -> None:
        """
        Initialize the AutoLightsConfig with default numeric values for
        early hours, night hours, and the target brightness.

        The properties can be adjusted as needed to fine-tune lighting behavior.
        """
        self.early_hours_starts: int = 0
        self.early_hours_ends: int = 0
        self.night_hours_starts: int = 0
        self.night_hours_ends: int = 0
        self.target_brightness: int = 0
        self._debug = False
        self._enabled = False

        self._guest_mode = False
        self._someone_home = False
        self._gone_to_bed = False
        self._early_hours_brightness = 0
        self._day_hours_brightness = 0
        self._night_hours_brightness = 0
        self._sleeping_hours_brightness = 0

        self._debug_var_id = -1
        self._enabled_var_id = -1

        self._someone_home_var_id = -1
        self._gone_to_bed_var_id = -1
        self._early_hours_brightness_var_id = -1
        self._day_hours_brightness_var_id = -1
        self._night_hours_brightness_var_id = -1
        self._sleeping_hours_brightness_var_id = -1
        self._guest_mode_var_id = -1
        self._threading_enabled = False
        self._rapid_execution_lock = False
        self._debug_maximum_run_time = 0.0
        self._default_lock_duration = 0
        self._default_lock_extension_duration = 0

    @staticmethod
    def _current_time() -> datetime.time:
        """Return the current time."""
        return datetime.datetime.now().time()

    def _is_time_between(self, start_hour: int, end_hour: int) -> bool:
        """
        Check if the current time is between the given start and end hours.

        This function supports intervals that span midnight.
        For example, if start_hour=22 and end_hour=6, it will return True for times
        between 22:00 and midnight as well as times between midnight and 06:00.
        """
        now = self._current_time()
        start_time = datetime.time(start_hour, 0)
        end_time = datetime.time(end_hour, 0)

        # Normal case: interval does not cross midnight
        if start_time <= end_time:
            return start_time <= now <= end_time
        # Interval crosses midnight (e.g., 22:00 to 06:00)
        else:
            return now >= start_time or now <= end_time

    def is_early_hours(self) -> bool:
        """
        Determine whether the current time is within the early-hours window.

        Returns:
            bool: True if the current time is between early_hours_starts and early_hours_ends.
        """
        return self._is_time_between(self.early_hours_starts, self.early_hours_ends)

    def is_day_time_hours(self) -> bool:
        """
        Check if the current time falls between early_hours_ends and night_hours_starts,
        identifying the 'daytime' window for lighting behavior.

        Returns:
            bool: True if in the daytime window.
        """
        return self._is_time_between(self.early_hours_ends, self.night_hours_starts)

    def is_night_time_hours(self) -> bool:
        """
        Check if the current time is in the designated night hours range.

        Returns:
            bool: True if the current time is between night_hours_starts and night_hours_ends.
        """
        return self._is_time_between(self.night_hours_starts, self.night_hours_ends)

    def is_sleeping_hours(self) -> bool:
        """
        Check if the current time falls outside the early, day, or night windows,
        implying it's 'sleeping hours' with typically very low lighting.

        Returns:
            bool: True if not in early hours, day hours, or night hours.
        """
        return (
            not self.is_early_hours()
            and not self.is_day_time_hours()
            and not self.is_night_time_hours()
        )

    @property
    def debug(self):
        return self._debug

    @debug.setter
    def debug(self, value):
        self._debug = value

    @property
    def debug_var_id(self):
        return self._debug_var_id

    @debug_var_id.setter
    def debug_var_id(self, value):
        self._debug_var_id = value
        self.debug = indigo.variables[self._debug_var_id].getValue(bool)

    @property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        self._enabled = value

    @property
    def enabled_var_id(self):
        return self._enabled_var_id

    @enabled_var_id.setter
    def enabled_var_id(self, value):
        self._enabled_var_id = value
        self._enabled = indigo.variables[self._enabled_var_id].getValue(bool)
        # indigo.server.log("AutoLightsConfig: enabled set to: " + str(self._enabled))

    @property
    def guest_mode(self):
        return self._guest_mode

    @property
    def guest_mode_var_id(self):
        return self._guest_mode_var_id

    @guest_mode_var_id.setter
    def guest_mode_var_id(self, value):
        self._guest_mode_var_id = value
        self._guest_mode = indigo.variables[self._guest_mode_var_id].getValue(bool)

    @property
    def someone_home(self):
        return self._someone_home

    @someone_home.setter
    def someone_home(self, value):
        self._someone_home = value

    @property
    def someone_home_var_id(self):
        return self._someone_home_var_id

    @someone_home_var_id.setter
    def someone_home_var_id(self, value):
        self._someone_home_var_id = value
        self._someone_home = indigo.variables[self._someone_home_var_id].getValue(bool)

    @property
    def gone_to_bed(self):
        return self._gone_to_bed

    @gone_to_bed.setter
    def gone_to_bed(self, value):
        self._gone_to_bed = value

    @property
    def gone_to_bed_var_id(self):
        return self._gone_to_bed_var_id

    @gone_to_bed_var_id.setter
    def gone_to_bed_var_id(self, value):
        self._gone_to_bed_var_id = value
        self._gone_to_bed = indigo.variables[self._gone_to_bed_var_id].getValue(bool)

    @property
    def early_hours_brightness(self):
        return self._early_hours_brightness

    @early_hours_brightness.setter
    def early_hours_brightness(self, value):
        self._early_hours_brightness = value

    @property
    def early_hours_brightness_var_id(self):
        return self._early_hours_brightness_var_id

    @early_hours_brightness_var_id.setter
    def early_hours_brightness_var_id(self, value):
        self._early_hours_brightness_var_id = value
        self._early_hours_brightness = indigo.variables[
            self._early_hours_brightness_var_id
        ].getValue(int)

    @property
    def day_hours_brightness(self):
        return self._day_hours_brightness

    @day_hours_brightness.setter
    def day_hours_brightness(self, value):
        self._day_hours_brightness = value

    @property
    def day_hours_brightness_var_id(self):
        return self._day_hours_brightness_var_id

    @day_hours_brightness_var_id.setter
    def day_hours_brightness_var_id(self, value):
        self._day_hours_brightness_var_id = value
        self._day_hours_brightness = indigo.variables[
            self._day_hours_brightness_var_id
        ].getValue(int)

    @property
    def night_hours_brightness(self):
        return self._night_hours_brightness

    @night_hours_brightness.setter
    def night_hours_brightness(self, value):
        self._night_hours_brightness = value

    @property
    def night_hours_brightness_var_id(self):
        return self._night_hours_brightness_var_id

    @night_hours_brightness_var_id.setter
    def night_hours_brightness_var_id(self, value):
        self._night_hours_brightness_var_id = value
        self._night_hours_brightness = indigo.variables[
            self._night_hours_brightness_var_id
        ].getValue(int)

    @property
    def sleeping_hours_brightness(self):
        return self._sleeping_hours_brightness

    @sleeping_hours_brightness.setter
    def sleeping_hours_brightness(self, value):
        self._sleeping_hours_brightness = value

    @property
    def sleeping_hours_brightness_var_id(self):
        return self._sleeping_hours_brightness_var_id

    @sleeping_hours_brightness_var_id.setter
    def sleeping_hours_brightness_var_id(self, value):
        self._sleeping_hours_brightness_var_id = value
        self._sleeping_hours_brightness = indigo.variables[
            self._sleeping_hours_brightness_var_id
        ].getValue(int)

    @property
    def threading_enabled(self) -> bool:
        return self._threading_enabled

    @threading_enabled.setter
    def threading_enabled(self, value: bool) -> None:
        self._threading_enabled = value

    @property
    def rapid_execution_lock(self) -> bool:
        return self._rapid_execution_lock

    @rapid_execution_lock.setter
    def rapid_execution_lock(self, value: bool) -> None:
        self._rapid_execution_lock = value

    @property
    def debug_maximum_run_time(self) -> float:
        """
        Maximum allowed run time (in seconds) for debugging output.
        """
        return self._debug_maximum_run_time

    @debug_maximum_run_time.setter
    def debug_maximum_run_time(self, value: float) -> None:
        self._debug_maximum_run_time = value

    def get_timed_brightness(self):
        if self.is_early_hours():
            return self.early_hours_brightness
        elif self.is_day_time_hours():
            return self.day_hours_brightness
        elif self.is_night_time_hours():
            return self.night_hours_brightness
        elif self.is_sleeping_hours():
            return self.sleeping_hours_brightness

        return self.target_brightness

    @property
    def default_lock_duration(self) -> int:
        return self._default_lock_duration

    @default_lock_duration.setter
    def default_lock_duration(self, value: int) -> None:
        self._default_lock_duration = value

    @property
    def default_lock_extension_duration(self) -> int:
        return self._default_lock_extension_duration

    @default_lock_extension_duration.setter
    def default_lock_extension_duration(self, value: int) -> None:
        self._default_lock_extension_duration = value

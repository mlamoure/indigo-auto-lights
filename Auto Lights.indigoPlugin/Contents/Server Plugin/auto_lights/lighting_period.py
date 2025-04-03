import datetime
from typing import Optional, Union, List

try:
    import indigo
except ImportError:
    pass


class LightingPeriod:
    """
    Represents a scheduled lighting period with start and end times, plus a designated mode.
    """

    def __init__(
        self,
        name: str,
        mode: str,
        from_time: datetime.time = datetime.time(0, 0),
        to_time: datetime.time = datetime.time(23, 59),
    ) -> None:
        """
        Initialize a LightingPeriod instance.

        Args:
            name (str): The name of the lighting period.
            mode (str): The mode of operation for this period.
            from_time (datetime.time, optional): Start time of the period. Defaults to 00:00.
            to_time (datetime.time, optional): End time of the period. Defaults to 23:59.
        """
        self._name = name
        self._from_time = from_time
        self._to_time = to_time
        self._mode = mode
        self._minimum_luminance = None
        self._minimum_luminance_var_id = None
        self._presence_dev_ids = None
        self._lock_duration = None
        self._uses_luminance_override = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def from_time(self) -> datetime.time:
        return self._from_time

    @from_time.setter
    def from_time(self, value: datetime.time) -> None:
        self._from_time = value

    @property
    def to_time(self) -> datetime.time:
        return self._to_time

    @to_time.setter
    def to_time(self, value: datetime.time) -> None:
        self._to_time = value

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value: str) -> None:
        self._mode = value

    def is_active_period(self) -> bool:
        """
        Determine if the current time falls within this lighting period.

        Returns:
            bool: True if the current time is between from_time and to_time, False otherwise.
        """
        current_time = datetime.datetime.now().time()
        return self._from_time <= current_time <= self._to_time

    @property
    def minimum_luminance(self) -> Optional[float]:
        return self._minimum_luminance

    @minimum_luminance.setter
    def minimum_luminance(self, value: float) -> None:
        """Set the minimum luminance threshold for the period.

        Args:
            value (float): The minimum luminance value.
        """
        self._minimum_luminance = value

    @property
    def minimum_luminance_var_id(self) -> float:
        return self._minimum_luminance_var_id

    @minimum_luminance_var_id.setter
    def minimum_luminance_var_id(self, value: float) -> None:
        """Set the variable ID for minimum luminance and update the minimum luminance value.

        Args:
            value (float): The variable ID.
        """
        self._minimum_luminance_var_id = value
        self._minimum_luminance = indigo.variables[
            self._minimum_luminance_var_id
        ].getValue(float)

    @property
    def presence_dev_ids(self) -> List[int]:
        if self._presence_dev_ids is None:
            return []
        if isinstance(self._presence_dev_ids, list):
            return self._presence_dev_ids
        return [self._presence_dev_ids]

    @presence_dev_ids.setter
    def presence_dev_ids(self, value: Union[int, List[int]]) -> None:
        """Set the device ID(s) used for detecting presence.

        Args:
            value (Union[int, List[int]]): A single device ID or a list of device IDs.
        """
        if isinstance(value, list):
            self._presence_dev_ids = value
        else:
            self._presence_dev_ids = [value]

    @property
    def uses_presence_override(self) -> bool:
        return self._uses_luminance_override

    @property
    def uses_luminance_override(self):
        return self.minimum_luminance is not None

    def has_presence_detected(self) -> bool:
        """
        Determine if any presence sensor indicates presence.

        Returns:
            bool: True if presence is detected on any configured device, False otherwise.
        """
        if not hasattr(self, "_presence_devId"):
            return False

        for dev_id in self.presence_dev_ids:
            device = indigo.devices[dev_id]
            if "onOffState" in device.states:
                if device.states["onOffState"]:
                    return True
            elif device.onState:
                return True

        return False

    @property
    def lock_duration(self) -> int:
        return self._lock_duration

    @lock_duration.setter
    def lock_duration(self, value: int) -> None:
        """Set the lock duration for the period.

        Args:
            value (int): The lock duration in minutes.
        """
        self._lock_duration = value

    @property
    def has_lock_duration_override(self) -> bool:
        """Indicate if a lock duration override has been set.

        Returns:
            bool: True if a lock duration override exists, False otherwise.
        """
        return hasattr(self, "_lockDuration")

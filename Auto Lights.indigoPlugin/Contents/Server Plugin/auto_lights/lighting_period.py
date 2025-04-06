import datetime

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
        self._lock_duration = None
        self._id = None

    @property
    def id(self) -> int:
        return self._id

    @id.setter
    def id(self, value: int) -> None:
        self._id = value

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

    @classmethod
    def from_config_dict(cls, cfg: dict):
        from_time = datetime.time(
            cfg.get("from_time_hour"), cfg.get("from_time_minute")
        )
        to_time = datetime.time(cfg.get("to_time_hour"), cfg.get("to_time_minute"))
        instance = cls(cfg.get("name"), cfg.get("mode"), from_time, to_time)
        if "lock_duration" in cfg:
            instance._lock_duration = cfg["lock_duration"]
        if "id" in cfg:
            instance.id = cfg["id"]
        return instance

    def is_active_period(self) -> bool:
        """
        Determine if the current time falls within this lighting period.

        Returns:
            bool: True if the current time is between from_time and to_time, False otherwise.
        """
        current_time = datetime.datetime.now().time()
        return self._from_time <= current_time <= self._to_time

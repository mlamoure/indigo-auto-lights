from enum import Enum

class LightingPeriodMode(Enum):
    ON_AND_OFF = "On and Off"
    OFF_ONLY   = "Off Only"

    @classmethod
    def from_string(cls, raw: str) -> "LightingPeriodMode":
        """Fold legacy and current mode strings into one enum."""
        if not isinstance(raw, str):
            raise ValueError(f"Invalid mode: {raw!r}")
        norm = raw.strip().lower().replace(" ", "").replace("_", "").replace("-", "")
        if norm in ("onandoff", "onoffzone"):
            return cls.ON_AND_OFF
        if norm in ("offonly", "offonlyzone"):
            return cls.OFF_ONLY
        raise ValueError(f"Unknown lighting period mode: {raw!r}")

    def __str__(self):
        return self.value

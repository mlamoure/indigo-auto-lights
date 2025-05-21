from dataclasses import dataclass
from typing import List, Tuple

@dataclass
class BrightnessPlan:
    # A list of (emoji, message) explaining WHY we did this
    contributions: List[Tuple[str, str]]
    # A list of (emoji, message) for devices excluded from the period
    exclusions: List[Tuple[str, str]]
    # The new raw target_brightness list you will apply to zone.target_brightness
    new_targets: List[dict]
    # A list of (emoji, message) describing the DEVICE-level differences
    device_changes: List[Tuple[str, str]]

import inspect
import logging
from dataclasses import dataclass
from typing import List, Tuple

@dataclass
class BrightnessPlan:
    # A list of (emoji, message) explaining WHY we did this
    contributions: List[Tuple[str, str]]
    # A list of (emoji, message) for devices excluded from the period
    exclusions:      List[Tuple[str, str]]
    # The new raw target_brightness list you will apply to zone.target_brightness
    new_targets:     List[dict]
    # A list of (emoji, message) describing the DEVICE-level differences
    device_changes:  List[Tuple[str, str]]


class AutoLightsBase:
    """
    A base class providing a standardized _debug_log method to all
    classes that inherit from it.
    """

    def __init__(self, logger_name="Plugin"):
        self.logger = logging.getLogger(logger_name)

    def _debug_log(self, message: str) -> None:
        stack = inspect.stack()
        current_fn = stack[1].function if len(stack) > 1 else ""
        caller_fn = stack[2].function if len(stack) > 2 else ""
        caller_line = stack[2].lineno if len(stack) > 2 else 0

        if hasattr(self, "name"):
            self.logger.debug(
                f"[caller: {caller_fn}:{caller_line}][func: {current_fn}][Zone '{self.name}']: {message}"
            )
        else:
            self.logger.debug(
                f"[caller: {caller_fn}:{caller_line}][func: {current_fn}] {message}"
            )

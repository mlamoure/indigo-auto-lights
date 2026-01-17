"""
Indigo API Tools - Direct Object Access

This module provides functions to access Indigo devices, variables, and action groups
using direct Python object access (indigo.devices, indigo.variables, etc.) instead of
HTTP API calls. This is more efficient and doesn't require API keys or network access.

These functions maintain backward compatibility with the original HTTP API-based interface
by returning data in the same dictionary format.
"""

try:
    import indigo
except ImportError:
    # For testing outside of Indigo environment
    indigo = None

KEYS_TO_KEEP = [
    "name",
    "class",
    "enabled",
    "id",
    "onState",
    "onOffState",
    "brightness",
    "energyCurLevel",
    "deviceTypeId",
    "description",
    "batteryLevel",
    "lastChanged",
    "deviceStatus",
    "isPoweredOn",
    "humidity",
    "sensorValue",
    "ZP_State",
    "coolSetPoint",
    "heatSetPoint",
    "hvac_state",
    "model",
    "subModel",
    "value",
    "state",
    "states",
    "objectType",
]
KEYS_TO_KEEP_MINIMAL = KEYS_TO_KEEP


def _device_to_dict(device, keys_to_keep=KEYS_TO_KEEP):
    """
    Convert an Indigo device object to a dictionary with filtered keys.

    Args:
        device: Indigo device object
        keys_to_keep: List of attribute names to include

    Returns:
        dict: Filtered device attributes
    """
    if indigo is None:
        raise RuntimeError("Indigo module not available")

    result = {}

    for key in keys_to_keep:
        if key == "class":
            # Special handling for device class - skip in loop, handle below
            continue

        if hasattr(device, key):
            value = getattr(device, key)
            # Convert indigo.Dict to regular dict
            if hasattr(value, '__iter__') and not isinstance(value, str):
                if hasattr(value, 'items'):
                    # It's a dict-like object
                    result[key] = dict(value)
                else:
                    # It's a list-like object
                    result[key] = list(value)
            else:
                result[key] = value

    # Special handling for device class
    if "class" in keys_to_keep:
        # Get the full class name (e.g., "indigo.DimmerDevice")
        device_class = f"{device.__class__.__module__}.{device.__class__.__name__}"
        result["class"] = device_class

    # Add object type
    result["objectType"] = "device"

    return result


def _variable_to_dict(variable, keys_to_keep=KEYS_TO_KEEP_MINIMAL):
    """
    Convert an Indigo variable object to a dictionary with filtered keys.

    Args:
        variable: Indigo variable object
        keys_to_keep: List of attribute names to include

    Returns:
        dict: Filtered variable attributes
    """
    if indigo is None:
        raise RuntimeError("Indigo module not available")

    result = {}

    for key in keys_to_keep:
        if hasattr(variable, key):
            value = getattr(variable, key)
            result[key] = value

    # Add object type
    result["objectType"] = "variable"

    return result


def _action_group_to_dict(action_group, keys_to_keep=KEYS_TO_KEEP_MINIMAL):
    """
    Convert an Indigo action group object to a dictionary with filtered keys.

    Args:
        action_group: Indigo action group object
        keys_to_keep: List of attribute names to include

    Returns:
        dict: Filtered action group attributes
    """
    if indigo is None:
        raise RuntimeError("Indigo module not available")

    result = {}

    for key in keys_to_keep:
        if hasattr(action_group, key):
            value = getattr(action_group, key)
            result[key] = value

    # Add object type
    result["objectType"] = "actionGroup"

    return result


def indigo_get_all_house_devices() -> list:
    """
    Retrieves a list of all devices in the house using direct Indigo object access.

    Returns:
        list: List of device dictionaries with filtered attributes
    """
    if indigo is None:
        raise RuntimeError("Indigo module not available")

    devices = []
    for device in indigo.devices:
        try:
            dev_dict = _device_to_dict(device, KEYS_TO_KEEP_MINIMAL)
            devices.append(dev_dict)
        except Exception as e:
            # Log error but continue with other devices
            print(f"Error converting device {device.id}: {e}")

    return devices


def indigo_get_house_devices(device_ids: str) -> dict:
    """
    Fetch information about one or more devices given their device IDs.

    Args:
        device_ids (str): A comma-separated list of device IDs.

    Returns:
        dict: Dictionary with 'devices' key containing list of device dicts
    """
    if indigo is None:
        raise RuntimeError("Indigo module not available")

    # Split the input string into a list of IDs
    ids = [int(device_id.strip()) for device_id in device_ids.split(",")]
    device_info_list = []

    for device_id in ids:
        try:
            device = indigo.devices[device_id]
            dev_dict = _device_to_dict(device, KEYS_TO_KEEP)
            device_info_list.append(dev_dict)
        except Exception as e:
            # If device not found or error, add error dict
            device_info_list.append({"id": device_id, "error": str(e)})

    return {"devices": device_info_list}


def indigo_get_all_house_action_groups() -> list:
    """
    Retrieves a list of all action groups in the house using direct Indigo object access.

    Returns:
        list: List of action group dictionaries with filtered attributes
    """
    if indigo is None:
        raise RuntimeError("Indigo module not available")

    action_groups = []
    for ag in indigo.actionGroups:
        try:
            ag_dict = _action_group_to_dict(ag, KEYS_TO_KEEP_MINIMAL)
            action_groups.append(ag_dict)
        except Exception as e:
            # Log error but continue
            print(f"Error converting action group {ag.id}: {e}")

    return action_groups


def indigo_get_all_house_variables() -> list:
    """
    Retrieves a list of all variables in the house using direct Indigo object access.

    Returns:
        list: List of variable dictionaries with filtered attributes
    """
    if indigo is None:
        raise RuntimeError("Indigo module not available")

    variables = []
    for var in indigo.variables:
        try:
            var_dict = _variable_to_dict(var, KEYS_TO_KEEP_MINIMAL)
            variables.append(var_dict)
        except Exception as e:
            # Log error but continue
            print(f"Error converting variable {var.id}: {e}")

    return variables


def indigo_create_new_variable(var_name: str) -> int:
    """
    Creates a new variable in the Indigo system using direct object access.

    Args:
        var_name (str): The name for the new variable

    Returns:
        int: The ID of the newly created variable

    Raises:
        RuntimeError: If Indigo module is not available
        Exception: If variable creation fails
    """
    if indigo is None:
        raise RuntimeError("Indigo module not available")

    try:
        # Create new variable with empty value
        new_var = indigo.variable.create(var_name, value="")
        return new_var.id
    except Exception as e:
        raise Exception(f"Failed to create variable '{var_name}': {e}")


# Legacy compatibility functions (deprecated but maintained for backward compatibility)

def get_indigo_api_url() -> str:
    """
    DEPRECATED: Returns empty string. Direct object access doesn't use API URLs.
    Maintained for backward compatibility only.
    """
    return ""


def indigo_api_call(api_endpoint, api_method, filter_keys=None, message_json=None) -> dict:
    """
    DEPRECATED: Direct object access doesn't use API calls.
    Maintained for backward compatibility only.

    Raises:
        NotImplementedError: This function is deprecated
    """
    raise NotImplementedError(
        "indigo_api_call is deprecated. Use direct indigo object access instead."
    )


def filter_json(json_obj, keys_to_keep):
    """
    Extracts specified properties from each object in a JSON object and returns them as a dictionary.

    This utility function is still used internally for filtering device/variable dictionaries.

    Args:
        json_obj (Dict or List): The object containing an array of json objects to be filtered.
        keys_to_keep (list): A list of property names to extract from each object.

    Returns:
        return: A filtered array of JSON objects containing only the specified keys.
    """
    if not isinstance(keys_to_keep, list):
        raise ValueError("Keys to keep must be provided as a list.")

    if isinstance(json_obj, dict):
        # Filter current dictionary and recurse for nested dictionaries
        return {
            key: (
                filter_json(value, keys_to_keep)
                if isinstance(value, (dict, list))
                else value
            )
            for key, value in json_obj.items()
            if key in keys_to_keep
        }
    elif isinstance(json_obj, list):
        # Recursively process each element in the list
        return [
            filter_json(item, keys_to_keep)
            for item in json_obj
            if isinstance(item, (dict, list))
        ]
    else:
        # If it's not a dict or list, return as-is (should not occur at the top level)
        raise ValueError(
            "Input must be a dictionary, a list of dictionaries, or a nested structure."
        )

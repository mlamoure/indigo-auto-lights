# These are not LLM tools as they get all HA data, which results in too much context.  These are used for vector
# search only, but reside here as they rely on common functions with the LLM tools.
import json
import os
from typing import List

import requests

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


def get_indigo_api_url() -> str:
    to_return = os.getenv("INDIGO_API_URL") + "/v2/api"
    return to_return


def indigo_get_all_house_devices() -> dict:
    """
    Fetches data from the indigo reflector endpoint to retrieve a list of all devices in the house, including
    name, device type, and database id, and returns it as a JSON object.

    Returns:
        dict: The JSON response from the API.
    """

    api_endpoint = f"{get_indigo_api_url()}/indigo.devices"
    return indigo_api_call(api_endpoint, "GET", KEYS_TO_KEEP_MINIMAL)


def indigo_get_house_devices(device_ids: str) -> dict:
    """
    Fetch data from the home automation server about one or more device, given their device id's.
    Return all information abot the device as a JSON object.

    Args:
        device_ids (str): A comma-separated list of device id's.

    Returns:
        dict: From the JSON response of the device from the API.
    """

    # Split the input string into a list of IDs
    ids = [device_id.strip() for device_id in device_ids.split(",")]
    device_info_list = []

    for device_id in ids:
        api_endpoint = f"{get_indigo_api_url()}/indigo.devices/{device_id}"
        device_info_list.append(indigo_api_call(api_endpoint, "GET", KEYS_TO_KEEP))

    return {"devices": device_info_list}


def indigo_get_all_house_action_groups() -> dict:
    """
    Fetches data from the indigo reflector endpoint to retrieve a list of all action groups in the house
    and returns it as a JSON object.  Action groups are user-defined sets of actions to take on the house devices.

    Returns:
        dict: The JSON response from the API.
    """

    api_endpoint = f"{get_indigo_api_url()}/indigo.actionGroups"
    return indigo_api_call(api_endpoint, "GET", KEYS_TO_KEEP_MINIMAL)


def indigo_get_all_house_variables() -> dict:
    """
    Fetches data from the indigo reflector endpoint to retrieve a list of all variables in the house
    and returns it as a JSON object.  Variables contain key information about the home automation system.

    Returns:
        dict: The JSON response from the API.
    """
    api_endpoint = f"{get_indigo_api_url()}/indigo.variables"
    return indigo_api_call(api_endpoint, "GET", KEYS_TO_KEEP_MINIMAL)


def indigo_api_call(
    api_endpoint, api_method, filter_keys=None, message_json=None
) -> dict:
    """
    Fetches data from the indigo reflector endpoint to retrieve a list of all variables in the house
    and returns it as a JSON object.  Variables contain key information about the home automation system.

    Returns:
        dict: The JSON response from the API.
    """
    headers = {
        "Authorization": f'Bearer {os.environ["INDIGO_API_KEY"]}',  # Set the API key in the header
        "Content-Type": "application/json",  # Optional: Specify content type
    }

    try:
        response = None

        if api_method == "GET":
            response = requests.get(api_endpoint, headers=headers)
        elif api_method == "POST":
            message_json = json.dumps(message_json).encode("utf8")
            response = requests.post(api_endpoint, headers=headers, data=message_json)

        response.raise_for_status()  # Raises an HTTPError for bad responses

        if filter_keys is None:
            return response.json()

        filtered_response = filter_json(response.json(), filter_keys)

        return filtered_response

    except requests.exceptions.RequestException as e:
        # Handle errors in the request process
        print(f"An error occurred: {e}")
        return {"error": str(e)}


# Utilities
def filter_json(json_obj, keys_to_keep):
    """
    Extracts specified properties from each object in a JSON object and returns them as a dictionary.

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


def indigo_create_new_variable(var_name):
    """
    Creates a new variable in the Indigo system by sending a POST request to the Indigo API.
    The API endpoint is formed by appending '/message/com.vtmikel.autolights/create_variable'
    to the INDIGO_API_URL environment variable.
    Expects a payload containing "var_name" and returns the new variable's ID.
    """

    endpoint = (
        os.getenv("INDIGO_API_URL") + "/message/com.vtmikel.autolights/create_variable"
    )
    payload = {"var_name": var_name}

    response = indigo_api_call(endpoint, "POST", payload, filter_keys=None)
    var_id = response["var_id"]

    return var_id

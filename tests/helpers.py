
def make_device(dev_id, **kwargs):
    """
    Create a dummy indigo.Device and insert into fake indigo.devices
    Supports: onState, brightness, sensorValue
    """
    import indigo
    d = indigo.Device(
        dev_id,
        name=kwargs.get("name", ""),
        onState=kwargs.get("onState", False),
        brightness=kwargs.get("brightness", 0),
        sensorValue=kwargs.get("sensorValue", None),
    )
    # update any extra states
    for k, v in kwargs.items():
        if k not in ("name", "onState", "brightness", "sensorValue"):
            d.states[k] = v
    indigo.devices[dev_id] = d
    return d

def load_yaml(path):
    import yaml
    with open(path, "r") as f:
        return yaml.safe_load(f)

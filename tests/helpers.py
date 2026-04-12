
def make_device(dev_id, device_cls="dimmer", **kwargs):
    """
    Create a dummy indigo.Device and insert into fake indigo.devices
    Supports: onState, brightness, sensorValue

    device_cls:
      - "dimmer" (default)
      - "relay"
      - "device"
      - a concrete Indigo stub class
    """
    import indigo

    if isinstance(device_cls, str):
        cls_map = {
            "device": indigo.Device,
            "dimmer": indigo.DimmerDevice,
            "relay": indigo.RelayDevice,
        }
        cls = cls_map[device_cls]
    else:
        cls = device_cls

    d = cls(
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
    d.onOffState = d.onState
    d.states["onState"] = d.onState
    d.states["onOffState"] = d.onOffState
    d.states["brightness"] = d.brightness
    indigo.devices[dev_id] = d
    return d

def load_yaml(path):
    import yaml
    with open(path, "r") as f:
        return yaml.safe_load(f)

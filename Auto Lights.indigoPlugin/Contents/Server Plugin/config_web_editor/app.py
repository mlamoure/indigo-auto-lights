import json
import os

from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    IntegerField,
    DecimalField,
    BooleanField,
    SelectField,
    SelectMultipleField,
)
from wtforms.validators import DataRequired

from .tools.indigo_api_tools import (
    indigo_get_all_house_variables,
    indigo_get_all_house_devices,
    indigo_get_house_devices,
    indigo_create_new_variable,
)

app = Flask(__name__)

load_dotenv()
SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev_secret")
INDIGO_API_KEY = os.getenv("INDIGO_API_KEY", "")
INDIGO_API_ENDPOINT = "https://example.com/api"  # static external API endpoint

app.config["SECRET_KEY"] = SECRET_KEY


# Helper to query external API for dropdown options.
def get_dropdown_options():
    # In a real application, you might perform a request like:
    # response = requests.get(f"{EXTERNAL_API_ENDPOINT}/devices", headers={"API-Key": INDIGO_API_KEY})
    # return [(item['id'], item['name']) for item in response.json()]
    # For demo purposes, we return a dummy list.
    return [(1, "Option 1"), (2, "Option 2"), (3, "Option 3")]


def get_lighting_period_choices():
    config_data = load_config()
    lighting_periods = config_data.get("lighting_periods", [])
    choices = []
    for period in lighting_periods:
        if "id" in period and "name" in period:
            choices.append((period["id"], period["name"]))
    return choices


from flask import g


def get_cached_indigo_variables():
    if not hasattr(g, "_indigo_variables"):
        g._indigo_variables = indigo_get_all_house_variables()
    return g._indigo_variables


def get_cached_indigo_devices():
    if not hasattr(g, "_indigo_devices"):
        g._indigo_devices = indigo_get_all_house_devices()
    return g._indigo_devices


def create_field(field_name, field_schema):
    label_text = field_schema.get("title", field_name)
    tooltip_text = field_schema.get("tooltip", "")
    allowed_types = None
    if field_schema.get("x-include-device-classes"):
        allowed_types = {
            cls.strip() for cls in field_schema["x-include-device-classes"].split(",")
        }

    field_type = field_schema.get("type")
    if field_name.endswith("_var_id") and field_schema.get("x-drop-down"):
        options = get_cached_indigo_variables()
        choices = [(opt["id"], opt["name"]) for opt in options]
        if not field_schema.get("required"):
            choices.insert(0, (-1, "None Selected"))
        f = SelectField(
            label=label_text, description=tooltip_text, choices=choices, coerce=int
        )
    elif field_name.endswith("_dev_ids") and field_schema.get("x-drop-down"):
        options = get_cached_indigo_devices()
        if allowed_types:
            options = [
                dev
                for dev in options
                if str(dev.get("class", "")).strip() in allowed_types
            ]
        choices = [(dev["id"], dev["name"]) for dev in options]
        f = SelectMultipleField(
            label=label_text, description=tooltip_text, choices=choices, coerce=int
        )
    elif field_name.endswith("_dev_id") and field_schema.get("x-drop-down"):
        options = get_cached_indigo_devices()
        if allowed_types:
            options = [
                dev
                for dev in options
                if str(dev.get("class", "")).strip() in allowed_types
            ]
        choices = [(dev["id"], dev["name"]) for dev in options]
        f = SelectField(
            label=label_text, description=tooltip_text, choices=choices, coerce=int
        )
    # If field name contains _id or _ids and schema has the custom x-drop-down marker,
    # use a SelectField or SelectMultipleField.
    elif field_name == "lighting_period_ids":
        f = SelectMultipleField(
            label=label_text,
            description=tooltip_text,
            choices=get_lighting_period_choices(),
            coerce=int,
        )
    elif "_ids" in field_name and field_schema.get("x-drop-down"):
        f = SelectMultipleField(
            label=label_text,
            description=tooltip_text,
            choices=get_dropdown_options(),
            coerce=int,
        )
    elif "_id" in field_name and field_schema.get("x-drop-down"):
        f = SelectField(
            label=label_text,
            description=tooltip_text,
            choices=get_dropdown_options(),
            coerce=int,
        )
    elif field_name in ["lock_duration", "default_lock_duration"]:
        f = SelectField(
            label=label_text,
            description=tooltip_text,
            coerce=lambda x: int(x) if x != "" else None,
            choices=[
                ("", "Use Plugin Default"),
                (1, "1 Minute"),
                (2, "2 Minutes"),
                (5, "5 Minutes"),
                (10, "10 Minutes"),
                (15, "15 Minutes"),
                (30, "30 Minutes"),
                (45, "45 Minutes"),
                (60, "1 hour"),
                (120, "2 hours"),
            ],
        )
    elif field_type == "integer":
        f = IntegerField(
            label=label_text, description=tooltip_text, validators=[DataRequired()]
        )
    elif field_type == "number":
        f = DecimalField(
            label=label_text, description=tooltip_text, validators=[DataRequired()]
        )
    elif field_type == "boolean":
        f = BooleanField(label=label_text, description=tooltip_text)
    elif field_type == "string" and field_schema.get("enum"):
        enum_values = field_schema.get("enum", [])
        choices = [(val, val) for val in enum_values]
        f = SelectField(label=label_text, description=tooltip_text, choices=choices)
    else:
        # Default to string field for any other types.
        f = StringField(
            label=label_text, description=tooltip_text, validators=[DataRequired()]
        )

    f.description = tooltip_text
    return f


def generate_form_class_from_schema(schema):
    # Dynamically creates a WTForms class using the provided schema definition.
    attrs = OrderedDict()
    for prop, subschema in schema.get("properties", {}).items():
        required_fields = schema.get("required", [])
        if not isinstance(required_fields, list):
            required_fields = []
        subschema["required"] = (prop in required_fields)
        if subschema.get("type") == "object":
            from wtforms import FormField

            subform_class = generate_form_class_from_schema(subschema)
            attrs[prop] = FormField(subform_class, label=subschema.get("title", prop))
        else:
            attrs[prop] = create_field(prop, subschema)

    class DynamicFormNoCSRF(FlaskForm):
        class Meta:
            csrf = False

    return type("DynamicFormNoCSRF", (DynamicFormNoCSRF,), attrs)


# Load JSON schema from file.
from collections import OrderedDict
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
schema_path = os.path.join(current_dir, "config_schema.json")
with open(schema_path) as f:
    config_schema = json.load(f, object_pairs_hook=OrderedDict)


def load_config():
    try:
        with open("config/auto_lights_conf.json") as f:
            return json.load(f)
    except Exception:
        return {"plugin_config": {}, "zones": []}


def save_config(config_data):
    with open("config/auto_lights_conf.json", "w") as f:
        json.dump(config_data, f, indent=2)


@app.route("/plugin_config", methods=["GET", "POST"])
def plugin_config():
    config_data = load_config()
    plugin_schema = config_schema["properties"]["plugin_config"]
    PluginFormClass = generate_form_class_from_schema(plugin_schema)
    plugin_form = PluginFormClass(data=config_data.get("plugin_config", {}))
    if request.method == "POST":
        updated_config = {
            field_name: field.data
            for field_name, field in plugin_form._fields.items()
            if field_name != "submit"
        }
        config_data["plugin_config"] = updated_config
        save_config(config_data)
        flash("Plugin configuration saved.")
        return redirect(url_for("plugin_config"))
    return render_template("plugin_edit.html", plugin_form=plugin_form)


@app.route("/zones", methods=["GET", "POST"])
def zones():
    config_data = load_config()
    ZonesFormClass = generate_form_class_from_schema(
        config_schema["properties"]["zones"]["items"]
    )
    zones = config_data.get("zones", [])
    zones_forms = [ZonesFormClass(data=zone) for zone in zones]
    if request.method == "POST":
        updated_zones = []
        for zone_form in zones_forms:
            zone_data = {
                field_name: field.data
                for field_name, field in zone_form._fields.items()
                if field_name != "submit"
            }
            updated_zones.append(zone_data)
        config_data["zones"] = updated_zones
        save_config(config_data)
        flash("Zones updated.")
        return redirect(url_for("zones"))
    return render_template("zones.html", zones_forms=zones_forms)


@app.route("/lighting_periods", methods=["GET", "POST"])
def lighting_periods():
    config_data = load_config()
    lighting_periods_schema = config_schema["properties"]["lighting_periods"]["items"]
    LightingPeriodsFormClass = generate_form_class_from_schema(lighting_periods_schema)
    lighting_periods = config_data.get("lighting_periods", [])
    lighting_periods_forms = [
        LightingPeriodsFormClass(data=period) for period in lighting_periods
    ]
    if request.method == "POST":
        updated_periods = []
        for period_form in lighting_periods_forms:
            period_data = {
                field_name: field.data
                for field_name, field in period_form._fields.items()
                if field_name != "submit"
            }
            updated_periods.append(period_data)
        config_data["lighting_periods"] = updated_periods
        save_config(config_data)
        flash("Lighting periods updated.")
        return redirect(url_for("lighting_periods"))
    return render_template(
        "lighting_periods.html", lighting_periods_forms=lighting_periods_forms
    )


@app.route("/zone/<zone_id>", methods=["GET", "POST"])
def zone_config(zone_id):
    config_data = load_config()
    zones = config_data.get("zones", [])
    if zone_id == "new":
        zone_schema = config_schema["properties"]["zones"]["items"]
        defaults = {}
        for field, subschema in zone_schema.get("properties", {}).items():
            if "default" in subschema:
                defaults[field] = subschema["default"]
        zone = defaults
        is_new = True
    else:
        index = int(zone_id)
        if index < 0 or index >= len(zones):
            flash("Invalid zone index.")
            return redirect(url_for("zones"))
        zone = zones[index]
        is_new = False
    ZonesFormClass = generate_form_class_from_schema(
        config_schema["properties"]["zones"]["items"]
    )
    zone_form = ZonesFormClass(data=zone)
    if request.method == "POST":
        zone_data = {
            field_name: field.data
            for field_name, field in zone_form._fields.items()
            if field_name != "submit"
        }
        if is_new:
            zones.append(zone_data)
            config_data["zones"] = zones
            save_config(config_data)
            flash("New zone created successfully.")
            return redirect(url_for("zones"))
        else:
            zones[index] = zone_data
            config_data["zones"] = zones
            save_config(config_data)
            flash("Zone updated.")
            return redirect(url_for("zone_config", zone_id=zone_id))
    return render_template("zone_edit.html", zone_form=zone_form, index=zone_id)


@app.route("/lighting_period/<period_id>", methods=["GET", "POST"])
def lighting_period_config(period_id):
    config_data = load_config()
    lighting_periods = config_data.get("lighting_periods", [])
    if period_id == "new":
        period_schema = config_schema["properties"]["lighting_periods"]["items"]
        defaults = {}
        for field, subschema in period_schema.get("properties", {}).items():
            if "default" in subschema:
                defaults[field] = subschema["default"]
        period = defaults
        is_new = True
    else:
        index = int(period_id)
        if index < 0 or index >= len(lighting_periods):
            flash("Invalid lighting period index.")
            return redirect(url_for("lighting_periods"))
        period = lighting_periods[index]
        is_new = False
    LightingPeriodFormClass = generate_form_class_from_schema(
        config_schema["properties"]["lighting_periods"]["items"]
    )
    if hasattr(LightingPeriodFormClass, "id"):
        delattr(LightingPeriodFormClass, "id")
    lighting_period_form = LightingPeriodFormClass(data=period)
    if request.method == "POST":
        period_data = {
            field_name: field.data
            for field_name, field in lighting_period_form._fields.items()
            if field_name != "submit"
        }
        if is_new:
            new_id = max([p.get("id", 0) for p in lighting_periods] or [0]) + 1
            period_data["id"] = new_id
            lighting_periods.append(period_data)
            config_data["lighting_periods"] = lighting_periods
            save_config(config_data)
            flash("New lighting period created successfully.")
            return redirect(url_for("lighting_periods"))
        else:
            period_data["id"] = period.get("id")
            lighting_periods[index] = period_data
            config_data["lighting_periods"] = lighting_periods
            save_config(config_data)
            flash("Lighting period updated.")
            return redirect(url_for("lighting_period_config", period_id=period_id))
    return render_template(
        "lighting_period_edit.html",
        lighting_period_form=lighting_period_form,
        index=period_id,
    )


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/README.MD")
def readme():
    try:
        with open("README.MD", "r") as f:
            text = f.read()
        return text, 200, {"Content-Type": "text/markdown"}
    except Exception as e:
        return "Error loading README.MD", 500


@app.route("/create_new_variable", methods=["POST"])
def create_new_variable():
    data = request.get_json()
    var_name = data.get("name", "")
    new_var_id = indigo_create_new_variable(var_name)
    return {"var_id": new_var_id, "var_name": var_name}


@app.route("/zone/delete/<zone_id>")
def zone_delete(zone_id):
    config_data = load_config()
    zones = config_data.get("zones", [])
    try:
        index = int(zone_id)
        if index < 0 or index >= len(zones):
            flash("Invalid zone index.")
        else:
            del zones[index]
            config_data["zones"] = zones
            save_config(config_data)
            flash("Zone deleted.")
    except Exception as e:
        flash("Error deleting zone: " + str(e))
    return redirect(url_for("zones"))


@app.route("/refresh_variables", methods=["GET"])
def refresh_variables():
    # Force a refresh by calling the Indigo API function directly.
    refreshed = indigo_get_all_house_variables()
    from flask import g

    g._indigo_variables = refreshed
    return {"variables": refreshed}


@app.route("/get_luminance_value", methods=["POST"])
def get_luminance_value():
    data = request.get_json()
    device_ids = data.get("device_ids", [])
    if not device_ids:
        return {"average": 0}
    ids_str = ",".join(str(id) for id in device_ids)
    devices = indigo_get_house_devices(ids_str)
    sensor_values = [
        d.get("sensorValue", 0)
        for d in devices.get("devices", [])
        if d.get("sensorValue") is not None
    ]
    if sensor_values:
        avg = sum(sensor_values) / len(sensor_values)
    else:
        avg = 0
    return {"average": avg}

def run_flask_app(host: str = "0.0.0.0", port: int = 9000) -> None:
    # Configure host and port as needed
    app.run(host=host, port=port, debug=False)

"""
This module implements the web configuration editor for the Auto Lights plugin.
It provides routes for editing plugin configuration, zones, lighting periods, and backups.
All functions and major code blocks are documented for clarity and PEP8 compliance.
"""
import json
import os
import secrets
import threading
import time
from collections import OrderedDict
from datetime import datetime

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

# Set refresh interval (default: 15 minutes)
REFRESH_INTERVAL_SECONDS = 900  # 15 minutes

# Global caches for devices and variables
_indigo_devices_cache = {"data": None}
_indigo_variables_cache = {"data": None}

# Lock for synchronizing access to caches
_cache_lock = threading.Lock()


def refresh_indigo_caches():
    """
    Periodically refreshes the caches for Indigo devices and variables.
    Runs indefinitely with a sleep interval defined by REFRESH_INTERVAL_SECONDS.
    """
    while True:
        try:
            new_devices = indigo_get_all_house_devices()
            new_variables = indigo_get_all_house_variables()
            with _cache_lock:
                _indigo_devices_cache["data"] = new_devices
                _indigo_variables_cache["data"] = new_variables
            app.logger.info(f"[{datetime.now()}] Indigo caches refreshed")
        except Exception as e:
            app.logger.error(f"Error refreshing caches: {e}")
        time.sleep(REFRESH_INTERVAL_SECONDS)


from .tools.indigo_api_tools import (
    indigo_get_all_house_variables,
    indigo_get_all_house_devices,
    indigo_get_house_devices,
    indigo_create_new_variable,
)

load_dotenv()
app = Flask(__name__)
SECRET_KEY = secrets.token_hex(16)
app.config["SECRET_KEY"] = SECRET_KEY
app.jinja_env.globals.update(enumerate=enumerate)


def start_cache_refresher():
    """
    Starts the cache refresher thread which periodically refreshes Indigo caches.
    """
    thread = threading.Thread(target=refresh_indigo_caches, daemon=True)
    thread.start()


def get_lighting_period_choices():
    """
    Retrieves lighting period choices from the configuration.
    Returns a list of tuples containing (id, name) for each lighting period.
    """
    config_data = load_config()
    lighting_periods = config_data.get("lighting_periods", [])
    choices = []
    for period in lighting_periods:
        if "id" in period and "name" in period:
            choices.append((period["id"], period["name"]))
    return choices


def get_cached_indigo_variables():
    """
    Retrieves the Indigo variables from cache (or refreshes them if not available).
    """
    with _cache_lock:
        if _indigo_variables_cache["data"] is None:
            try:
                new_variables = indigo_get_all_house_variables()
                _indigo_variables_cache["data"] = new_variables
                app.logger.info(f"[{datetime.now()}] Indigo variables cache refreshed")
            except Exception as e:
                app.logger.error(f"Error refreshing variables cache: {e}")
        return _indigo_variables_cache["data"]


app.jinja_env.globals.update(get_cached_indigo_variables=get_cached_indigo_variables)


def get_cached_indigo_devices():
    """
    Retrieves the Indigo devices from cache (or refreshes them if not available).
    """
    with _cache_lock:
        if _indigo_devices_cache["data"] is None:
            try:
                new_devices = indigo_get_all_house_devices()
                _indigo_devices_cache["data"] = new_devices
                app.logger.info(
                    f"[{datetime.now()}] Indigo devices cache manually refreshed"
                )
            except Exception as e:
                app.logger.error(f"Error manually refreshing devices cache: {e}")
        return _indigo_devices_cache["data"]


def create_field(field_name, field_schema):
    """
    Creates a WTForms field based on the provided field schema.

    Args:
        field_name (str): The name of the field.
        field_schema (dict): Schema definition for the field.

    Returns:
        A WTForms field object.
    """
    label_text = field_schema.get("title", field_name)
    tooltip_text = field_schema.get("tooltip", "")
    required = field_schema.get("required", False)
    validators = []
    if required:
        validators.append(DataRequired())
    allowed_types = None
    if field_schema.get("x-include-device-classes"):
        allowed_types = {
            cls.strip() for cls in field_schema["x-include-device-classes"].split(",")
        }

    field_type = field_schema.get("type")
    if field_name.endswith("_var_id") and field_schema.get("x-drop-down"):
        options = get_cached_indigo_variables()
        choices = [(opt["id"], opt["name"]) for opt in options]
        if not required:
            choices.insert(0, (-1, "None Selected"))
        f = SelectField(
            label=label_text,
            description=tooltip_text,
            choices=choices,
            coerce=int,
            validators=validators,
        )
    elif field_name.endswith("_dev_ids") and field_schema.get("x-drop-down"):
        local_validators = list(validators)
        options = get_cached_indigo_devices()
        if allowed_types:
            options = [
                dev
                for dev in options
                if str(dev.get("class", "")).strip() in allowed_types
                or str(dev.get("deviceTypeId", "")).strip() in allowed_types
            ]
        choices = [(dev["id"], dev["name"]) for dev in options]
        f = SelectMultipleField(
            label=label_text,
            description=tooltip_text,
            choices=choices,
            coerce=int,
            validators=local_validators,
        )
    elif field_name.endswith("_dev_id") and field_schema.get("x-drop-down"):
        options = get_cached_indigo_devices()
        if allowed_types:
            options = [
                dev
                for dev in options
                if str(dev.get("class", "")).strip() in allowed_types
                or str(dev.get("deviceTypeId", "")).strip() in allowed_types
            ]

        choices = [(dev["id"], dev["name"]) for dev in options]
        f = SelectField(
            label=label_text,
            description=tooltip_text,
            choices=choices,
            coerce=int,
            validators=validators,
            render_kw=({"required": True} if required else {}),
        )
    # If field name contains _id or _ids and schema has the custom x-drop-down marker,
    # use a SelectField or SelectMultipleField.
    elif field_name == "lighting_period_ids":
        f = SelectMultipleField(
            label=label_text,
            description=tooltip_text,
            choices=get_lighting_period_choices(),
            coerce=int,
            validators=validators,
        )
    elif field_name in [
        "lock_duration",
        "default_lock_duration",
        "default_lock_extension_duration",
    ]:
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
            label=label_text, description=tooltip_text, validators=validators
        )
    elif field_type == "number":
        f = DecimalField(
            label=label_text, description=tooltip_text, validators=validators
        )
    elif field_type == "boolean":
        f = BooleanField(
            label=label_text, description=tooltip_text, validators=validators
        )
    elif field_type == "string" and field_schema.get("enum"):
        enum_values = field_schema.get("enum", [])
        choices = [(val, val) for val in enum_values]
        f = SelectField(
            label=label_text,
            description=tooltip_text,
            choices=choices,
            validators=validators,
        )
    else:
        # Default to string field for any other types.
        f = StringField(
            label=label_text, description=tooltip_text, validators=validators
        )

    f.description = tooltip_text
    return f


def generate_form_class_from_schema(schema):
    """
    Dynamically creates a WTForms form class from the provided JSON schema.

    Args:
        schema (dict): JSON schema defining form properties.

    Returns:
        A dynamically generated WTForms form class.
    """
    attrs = OrderedDict()
    for prop, subschema in schema.get("properties", {}).items():
        required_fields = schema.get("required", [])
        if not isinstance(required_fields, list):
            required_fields = []
        subschema_is_required = prop in required_fields

        if subschema.get("type") == "object":
            from wtforms import FormField

            # Ensure nested properties are marked required
            nested_required = subschema.get("required", [])
            if not isinstance(nested_required, list):
                nested_required = []
            for nested_prop, nested_sub in subschema.get("properties", {}).items():
                nested_sub["required"] = nested_prop in nested_required

            subform_class = generate_form_class_from_schema(subschema)
            attrs[prop] = FormField(subform_class, label=subschema.get("title", prop))
        else:
            # Mark this property as required based on top-level "required"
            subschema["required"] = subschema_is_required
            attrs[prop] = create_field(prop, subschema)

    class DynamicFormNoCSRF(FlaskForm):
        class Meta:
            csrf = False

    return type("DynamicFormNoCSRF", (DynamicFormNoCSRF,), attrs)


current_dir = os.path.dirname(os.path.abspath(__file__))
schema_path = os.path.join(current_dir, "config/config_schema.json")
with open(schema_path) as f:
    config_schema = json.load(f, object_pairs_hook=OrderedDict)


def load_config():
    """
    Loads the auto lights configuration from the JSON file.

    Returns:
        dict: The configuration dictionary.
    """
    config_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config", "auto_lights_conf.json"
    )
    try:
        with open(config_path) as f:
            return json.load(f)
    except Exception:
        return {"plugin_config": {}, "zones": []}


def save_config(config_data):
    """
    Saves the auto lights configuration to the JSON file.
    Prior to saving, creates a backup in the auto_backups folder with a timestamp
    and prunes backups beyond 20.

    Args:
        config_data (dict): The configuration to be saved.
    """
    config_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config", "auto_lights_conf.json"
    )
    if os.path.exists(config_path):
        backup_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "config", "auto_backups"
        )
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_file = os.path.join(backup_dir, f"auto_backup_{timestamp}.json")
        import shutil

        shutil.copy2(config_path, backup_file)
        import glob

        backups = sorted(glob.glob(os.path.join(backup_dir, "auto_backup_*.json")))
        while len(backups) > 20:
            os.remove(backups[0])
            backups.pop(0)
    with open(config_path, "w") as f:
        json.dump(config_data, f, indent=2)


@app.route("/plugin_config", methods=["GET", "POST"])
def plugin_config():
    """
    Route for viewing and updating the plugin configuration.

    GET: Renders the plugin configuration form.
    POST: Updates the configuration with submitted data and saves changes.
    """
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
        # --- Begin new code to process global_behavior_variables ---
        global_vars = []
        for key in request.form:
            if key.startswith("global_behavior_variables-") and key.endswith("-var_id"):
                parts = key.split("-")
                if len(parts) >= 3:
                    index = parts[1]
                    var_id_value = request.form.get(key)
                    var_value_value = request.form.get(
                        f"global_behavior_variables-{index}-var_value", ""
                    )
                    try:
                        var_id_int = int(var_id_value)
                    except (ValueError, TypeError):
                        continue
                    global_vars.append(
                        {
                            "var_id": var_id_int,
                            "var_value": var_value_value,
                        }
                    )
        updated_config["global_behavior_variables"] = global_vars
        # --- End new code ---
        config_data["plugin_config"] = updated_config
        save_config(config_data)
        flash("Plugin configuration saved.")
        return redirect(url_for("plugin_config"))
    return render_template("plugin_edit.html", plugin_form=plugin_form)


@app.route("/zones", methods=["GET", "POST"])
def zones():
    """
    Route for displaying and updating zones.

    GET: Renders the zones configuration form.
    POST: Processes updates to zone configurations and saves them.
    """
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
    """
    Route for viewing and updating lighting periods.

    GET: Renders the lighting periods configuration form.
    POST: Saves changes made to lighting periods.
    """
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
    """
    Route for viewing, updating, or creating a zone configuration.

    GET: Renders the form for the specified zone.
    POST: Updates an existing zone or creates a new zone and saves the configuration.

    Args:
        zone_id (str): Index of the zone or 'new' for creating a new zone.
    """
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
    try:
        on_lights = zone.get("device_settings", {}).get("on_lights_dev_ids", [])
        off_lights = zone.get("device_settings", {}).get("off_lights_dev_ids", [])
        union_ids = set(on_lights) | set(off_lights)
        devices = {dev["id"]: dev["name"] for dev in get_cached_indigo_devices()}
        choices = [(i, devices.get(i, str(i))) for i in union_ids]
        zone_form.advanced_settings.exclude_from_lock_dev_ids.choices = choices
    except Exception:
        pass
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
    """
    Route for viewing, updating, or creating a lighting period.

    GET: Renders the form for the specified lighting period.
    POST: Updates an existing period or creates a new one and saves the configuration.

    Args:
        period_id (str): Index of the lighting period or 'new' for creating a new period.
    """
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
    """
    Route for the home page.

    Returns:
        Rendered index.html template.
    """
    return render_template("index.html")


@app.route("/README.MD")
def readme():
    """
    Route for serving the README.MD file as markdown.

    Returns:
        The README content with the appropriate Content-Type header.
    """
    try:
        with open("README.MD", "r") as f:
            text = f.read()
        return text, 200, {"Content-Type": "text/markdown"}
    except Exception as e:
        return "Error loading README.MD", 500


@app.route("/create_new_variable", methods=["POST"])
def create_new_variable():
    """
    Route to create a new Indigo variable.

    Expects JSON data containing 'name'.
    Returns:
        JSON response with the new variable's id and name.
    """
    data = request.get_json()
    var_name = data.get("name", "")
    new_var_id = indigo_create_new_variable(var_name)
    return {"var_id": new_var_id, "var_name": var_name}


@app.route("/zone/delete/<zone_id>")
def zone_delete(zone_id):
    """
    Route to delete a specified zone.

    Args:
        zone_id (str): Index of the zone to delete.
    """
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
    """
    Route to force a refresh of the Indigo variables cache.

    Returns:
        JSON response with the refreshed variables.
    """
    # Force a refresh by calling the Indigo API function directly.
    refreshed = indigo_get_all_house_variables()
    from flask import g

    g._indigo_variables = refreshed
    return {"variables": refreshed}


@app.route("/get_luminance_value", methods=["POST"])
def get_luminance_value():
    """
    Route to compute the average luminance value from a list of device IDs.

    Expects JSON with a "device_ids" key.
    Returns:
        JSON with the computed average luminance.
    """
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


@app.route("/config_backup", methods=["GET", "POST"])
def config_backup():
    """
    Route for managing configuration backups.

    GET: Displays available manual and automatic backups.
    POST: Handles creation, restoration, or deletion of backups.
    """
    import shutil, glob

    config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config")
    manual_backup_dir = os.path.join(config_dir, "backups")
    auto_backup_dir = os.path.join(config_dir, "auto_backups")
    os.makedirs(manual_backup_dir, exist_ok=True)
    os.makedirs(auto_backup_dir, exist_ok=True)

    if request.method == "POST":
        action = request.form.get("action")
        backup_type = request.form.get("backup_type")
        backup_file = request.form.get("backup_file")
        config_path = os.path.join(config_dir, "auto_lights_conf.json")
        if action == "create_manual":
            dest = os.path.join(
                manual_backup_dir,
                f"manual_backup_{datetime.now().strftime('%Y%m%d%H%M%S')}.json",
            )
            shutil.copy2(config_path, dest)
            flash("Manual backup created.")
        elif action == "restore":
            if backup_file:
                src = os.path.join(
                    manual_backup_dir if backup_type == "manual" else auto_backup_dir,
                    backup_file,
                )
                shutil.copy2(src, config_path)
                flash("Backup restored.")
        elif action == "delete":
            if backup_file:
                path_to_delete = os.path.join(
                    manual_backup_dir if backup_type == "manual" else auto_backup_dir,
                    backup_file,
                )
                if os.path.exists(path_to_delete):
                    os.remove(path_to_delete)
                    flash("Backup deleted.")
        return redirect(url_for("config_backup"))

    manual_backups = [
        os.path.basename(p)
        for p in glob.glob(os.path.join(manual_backup_dir, "*.json"))
    ]
    auto_backups_files = sorted(
        glob.glob(os.path.join(auto_backup_dir, "auto_backup_*.json")), reverse=True
    )
    auto_backups = []
    for ab in auto_backups_files:
        desc = "Automatic backup"
        auto_backups.append({"filename": os.path.basename(ab), "description": desc})
    return render_template(
        "config_backup.html", manual_backups=manual_backups, auto_backups=auto_backups
    )


@app.route("/shutdown", methods=["POST"])
def shutdown():
    """
    Route to shut down the Flask development server.

    Returns:
        Confirmation message upon server shutdown.
    """
    shutdown_func = request.environ.get("werkzeug.server.shutdown")
    if shutdown_func is None:
        raise RuntimeError("Not running with the Werkzeug Server")
    shutdown_func()
    return "Server shutting down..."


def run_flask_app(
    host: str = "127.0.0.1", port: int = 9500, debug: bool = False
) -> None:
    """
    Runs the Flask web application for the Auto Lights plugin.

    Args:
        host (str): Host address for the server.
        port (int): Port number.
        debug (bool): Whether to run the server in debug mode.
    """
    # Configure host and port as needed
    try:
        new_devices = indigo_get_all_house_devices()
        new_variables = indigo_get_all_house_variables()
        with _cache_lock:
            _indigo_devices_cache["data"] = new_devices
            _indigo_variables_cache["data"] = new_variables
        app.logger.info(f"[{datetime.now()}] Indigo caches refreshed")
    except Exception as e:
        app.logger.error(f"Error refreshing caches: {e}")
    start_cache_refresher()
    app.run(host=host, port=port, debug=debug)

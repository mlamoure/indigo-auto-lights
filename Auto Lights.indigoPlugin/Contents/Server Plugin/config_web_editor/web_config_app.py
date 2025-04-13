"""
This module implements the web configuration editor for the Auto Lights plugin.
It provides routes for editing plugin configuration, zones, lighting periods, and backups.
All functions and major code blocks are documented for clarity and PEP8 compliance.
"""

import glob
# --- Standard library imports (alphabetical) ---
import json
import os
import secrets
import shutil
from collections import OrderedDict
from datetime import datetime

# --- Third-party imports ---
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, current_app, send_file
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

from .config_editor import WebConfigEditor
# --- Local imports ---
from .tools.indigo_api_tools import (
    indigo_get_all_house_variables,
    indigo_get_house_devices,
    indigo_create_new_variable,
)

# Load environment variables if needed
load_dotenv()

# Flask application setup
app = Flask(__name__)
SECRET_KEY = secrets.token_hex(16)
app.config["SECRET_KEY"] = SECRET_KEY
app.jinja_env.globals.update(enumerate=enumerate)

# Lock for synchronizing access to caches


def load_config():

    return current_app.config["config_editor"].load_config()


def get_lighting_period_choices():
    """
    Retrieves lighting period choices from the configuration.
    Returns a list of tuples (id, name) for each lighting period.
    """
    config_data = load_config()
    lighting_periods = config_data.get("lighting_periods", [])
    choices = []
    for period in lighting_periods:
        if "id" in period and "name" in period:
            choices.append((period["id"], period["name"]))
    return choices


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

    # Example of variable-specific drop-down for Indigo variables
    if field_name.endswith("_var_id") and field_schema.get("x-drop-down"):

        options = current_app.config["config_editor"].get_cached_indigo_variables()
        choices = [(opt["id"], opt["name"]) for opt in options]
        if not required:
            choices.insert(0, (-1, "None Selected"))
        field = SelectField(
            label=label_text,
            description=tooltip_text,
            choices=choices,
            coerce=int,
            validators=validators,
        )

    # Example of multi-select for device IDs
    elif field_name.endswith("_dev_ids") and field_schema.get("x-drop-down"):

        options = current_app.config["config_editor"].get_cached_indigo_devices()
        if allowed_types:
            options = [
                dev
                for dev in options
                if str(dev.get("class", "")).strip() in allowed_types
                or str(dev.get("deviceTypeId", "")).strip() in allowed_types
            ]
        choices = [(dev["id"], dev["name"]) for dev in options]
        field = SelectMultipleField(
            label=label_text,
            description=tooltip_text,
            choices=choices,
            coerce=int,
            validators=validators,
        )

    # Single select for device IDs
    elif field_name.endswith("_dev_id") and field_schema.get("x-drop-down"):
        options = current_app.config["config_editor"].get_cached_indigo_devices()
        if allowed_types:
            options = [
                dev
                for dev in options
                if str(dev.get("class", "")).strip() in allowed_types
                or str(dev.get("deviceTypeId", "")).strip() in allowed_types
            ]
        choices = [(dev["id"], dev["name"]) for dev in options]
        field = SelectField(
            label=label_text,
            description=tooltip_text,
            choices=choices,
            coerce=int,
            validators=validators,
            render_kw=({"required": True} if required else {}),
        )

    elif field_name == "lighting_period_ids":
        field = SelectMultipleField(
            label=label_text,
            description=tooltip_text,
            choices=get_lighting_period_choices(),
            coerce=int,
            validators=validators,
        )

    # Example of an enumerated select for lock durations
    elif field_name in [
        "lock_duration",
        "default_lock_duration",
        "default_lock_extension_duration",
    ]:
        field = SelectField(
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

    # Basic integer field
    elif field_type == "integer":
        field = IntegerField(
            label=label_text, description=tooltip_text, validators=validators
        )

    # Basic decimal/float field
    elif field_type == "number":
        field = DecimalField(
            label=label_text, description=tooltip_text, validators=validators
        )

    # Simple boolean
    elif field_type == "boolean":
        field = BooleanField(
            label=label_text, description=tooltip_text, validators=validators
        )

    # Simple enumerated string select
    elif field_type == "string" and field_schema.get("enum"):
        enum_values = field_schema.get("enum", [])
        choices = [(val, val) for val in enum_values]
        field = SelectField(
            label=label_text,
            description=tooltip_text,
            choices=choices,
            validators=validators,
        )

    # Default to basic string field
    else:
        field = StringField(
            label=label_text, description=tooltip_text, validators=validators
        )

    field.description = tooltip_text
    return field


def generate_form_class_from_schema(schema):
    """
    Dynamically creates a WTForms form class from the provided JSON schema.

    Args:
        schema (dict): JSON schema defining form properties.

    Returns:
        A dynamically generated WTForms form class (subclass of FlaskForm).
    """
    from collections import OrderedDict
    from wtforms import FormField

    attrs = OrderedDict()
    for prop, subschema in schema.get("properties", {}).items():
        required_fields = schema.get("required", [])
        if not isinstance(required_fields, list):
            required_fields = []
        subschema_is_required = prop in required_fields

        if subschema.get("type") == "object":
            # If the property is itself an object, create a subform
            nested_required = subschema.get("required", [])
            if not isinstance(nested_required, list):
                nested_required = []
            for nested_prop, nested_sub in subschema.get("properties", {}).items():
                nested_sub["required"] = nested_prop in nested_required

            subform_class = generate_form_class_from_schema(subschema)
            attrs[prop] = FormField(subform_class, label=subschema.get("title", prop))
        else:
            # Mark property as required based on top-level schema
            subschema["required"] = subschema_is_required
            attrs[prop] = create_field(prop, subschema)

    class DynamicFormNoCSRF(FlaskForm):
        class Meta:
            csrf = False

    return type("DynamicFormNoCSRF", (DynamicFormNoCSRF,), attrs)


def save_config(config_data):
    """
    Saves the auto lights configuration to the JSON file. Before saving,
    creates a timestamped backup if an existing config is found, and prunes
    older backups beyond 20.

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

        shutil.copy2(config_path, backup_file)

        backups = sorted(glob.glob(os.path.join(backup_dir, "auto_backup_*.json")))
        while len(backups) > 20:
            os.remove(backups[0])
            backups.pop(0)

    with open(config_path, "w") as f:
        json.dump(config_data, f, indent=2)


@app.route("/plugin_config", methods=["GET", "POST"])
def plugin_config():
    """
    Route that displays or updates the plugin configuration.
    GET: Renders the configuration form with current plugin settings.
    POST: Saves updated configuration to the JSON file, then redirects.
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
        # Process global_behavior_variables
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

        config_data["plugin_config"] = updated_config
        save_config(config_data)
        flash("Plugin configuration saved.")
        return redirect(url_for("plugin_config"))

    return render_template("plugin_edit.html", plugin_form=plugin_form)


@app.route("/zones", methods=["GET", "POST"])
def zones():
    """
    Route for displaying and updating all zones.
    GET: Shows the current zones in a form.
    POST: Saves new or updated zone data to the configuration.
    """
    config_data = load_config()
    ZonesFormClass = generate_form_class_from_schema(
        config_schema["properties"]["zones"]["items"]
    )
    zones_data = config_data.get("zones", [])
    zones_forms = [ZonesFormClass(data=zone) for zone in zones_data]

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
    GET: Shows a form for each lighting period.
    POST: Saves changes to those periods in the JSON config.
    """
    config_data = load_config()
    lighting_periods_schema = config_schema["properties"]["lighting_periods"]["items"]
    LightingPeriodsFormClass = generate_form_class_from_schema(lighting_periods_schema)

    lighting_periods_data = config_data.get("lighting_periods", [])
    lighting_periods_forms = [
        LightingPeriodsFormClass(data=period) for period in lighting_periods_data
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
    Route for viewing, updating, or creating a single zone.
    GET: Displays a form for the specified zone (or a new one if zone_id = 'new').
    POST: Updates or creates the zone in the configuration, then saves.
    """
    config_data = load_config()
    zones_data = config_data.get("zones", [])

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
        if index < 0 or index >= len(zones_data):
            flash("Invalid zone index.")
            return redirect(url_for("zones"))
        zone = zones_data[index]
        is_new = False

    ZonesFormClass = generate_form_class_from_schema(
        config_schema["properties"]["zones"]["items"]
    )
    zone_form = ZonesFormClass(data=zone)

    # Attempt to update choices for exclude_from_lock_dev_ids
    try:
        on_lights = zone.get("device_settings", {}).get("on_lights_dev_ids", [])
        off_lights = zone.get("device_settings", {}).get("off_lights_dev_ids", [])
        union_ids = set(on_lights) | set(off_lights)
        devices = {
            dev["id"]: dev["name"]
            for dev in current_app.config["config_editor"].get_cached_indigo_devices()
        }
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
            zones_data.append(zone_data)
            config_data["zones"] = zones_data
            save_config(config_data)
            flash("New zone created successfully.")
            return redirect(url_for("zones"))
        else:
            zones_data[index] = zone_data
            config_data["zones"] = zones_data
            save_config(config_data)
            flash("Zone updated.")
            return redirect(url_for("zone_config", zone_id=zone_id))

    return render_template("zone_edit.html", zone_form=zone_form, index=zone_id)


@app.route("/lighting_period/<period_id>", methods=["GET", "POST"])
def lighting_period_config(period_id):
    """
    Route for viewing, updating, or creating a single lighting period.
    GET: Displays a form for the specified period (or a new one if period_id = 'new').
    POST: Updates or creates the period, then saves.
    """
    config_data = load_config()
    lighting_periods_data = config_data.get("lighting_periods", [])

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
        if index < 0 or index >= len(lighting_periods_data):
            flash("Invalid lighting period index.")
            return redirect(url_for("lighting_periods"))
        period = lighting_periods_data[index]
        is_new = False

    LightingPeriodFormClass = generate_form_class_from_schema(
        config_schema["properties"]["lighting_periods"]["items"]
    )
    if hasattr(LightingPeriodFormClass, "id"):
        # Remove the 'id' attribute from the dynamic form class if it causes collisions
        delattr(LightingPeriodFormClass, "id")

    lighting_period_form = LightingPeriodFormClass(data=period)

    if request.method == "POST":
        period_data = {
            field_name: field.data
            for field_name, field in lighting_period_form._fields.items()
            if field_name != "submit"
        }
        if is_new:
            new_id = max([p.get("id", 0) for p in lighting_periods_data] or [0]) + 1
            period_data["id"] = new_id
            lighting_periods_data.append(period_data)
            config_data["lighting_periods"] = lighting_periods_data
            save_config(config_data)
            flash("New lighting period created successfully.")
            return redirect(url_for("lighting_periods"))
        else:
            period_data["id"] = period.get("id")
            lighting_periods_data[index] = period_data
            config_data["lighting_periods"] = lighting_periods_data
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
    Route for the home page of this configuration interface.
    Displays a simple index or landing page.
    """
    return render_template("index.html")


@app.route("/README.MD")
def readme():
    """
    Route that serves the README file as markdown content.
    Returns the file content with 'text/markdown' Content-Type.
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
    Returns the new variable's ID and name as JSON.
    """
    data = request.get_json()
    var_name = data.get("name", "")
    new_var_id = indigo_create_new_variable(var_name)
    return {"var_id": new_var_id, "var_name": var_name}


@app.route("/zone/delete/<zone_id>")
def zone_delete(zone_id):
    """
    Route to delete a specified zone by its index.
    Redirects back to the zones list after deletion.
    """
    config_data = load_config()
    zones_data = config_data.get("zones", [])
    try:
        index = int(zone_id)
        if index < 0 or index >= len(zones_data):
            flash("Invalid zone index.")
        else:
            del zones_data[index]
            config_data["zones"] = zones_data
            save_config(config_data)
            flash("Zone deleted.")
    except Exception as e:
        flash("Error deleting zone: " + str(e))
    return redirect(url_for("zones"))


@app.route("/refresh_variables", methods=["GET"])
def refresh_variables():
    """
    Route to force a refresh of Indigo variables in the in-memory cache.
    Returns the refreshed variables as JSON.
    """
    refreshed = indigo_get_all_house_variables()
    from flask import g

    g._indigo_variables = refreshed
    return {"variables": refreshed}


@app.route("/get_luminance_value", methods=["POST"])
def get_luminance_value():
    """
    Route to compute the average luminance from a list of device IDs (in JSON).
    Returns the average sensor value in JSON.
    """
    data = request.get_json()
    device_ids = data.get("device_ids", [])
    if not device_ids:
        return {"average": 0}
    ids_str = ",".join(str(dev_id) for dev_id in device_ids)
    devices = indigo_get_house_devices(ids_str)
    sensor_values = [
        d.get("sensorValue", 0)
        for d in devices.get("devices", [])
        if d.get("sensorValue") is not None
    ]
    avg = sum(sensor_values) / len(sensor_values) if sensor_values else 0
    return {"average": avg}


@app.route("/config_backup", methods=["GET", "POST"])
def config_backup():
    """
    Route for managing configuration backups.
    GET: Lists available manual and automatic backups.
    POST: Handles creation, restoration, or deletion of selected backups.
    """
    config_editor = current_app.config["config_editor"]

    if request.method == "POST":
        action = request.form.get("action")
        backup_type = request.form.get("backup_type")
        backup_file = request.form.get("backup_file")

        if action == "create_manual":
            config_editor.create_manual_backup()
            flash("Manual backup created.")

        elif action == "restore":
            if backup_file and config_editor.restore_backup(backup_type, backup_file):
                flash("Backup restored.")
            else:
                flash("Error restoring backup.")

        elif action == "delete":
            if backup_file and config_editor.delete_backup(backup_type, backup_file):
                flash("Backup deleted.")
            else:
                flash("Error deleting backup.")

        return redirect(url_for("config_backup"))

    manual_backups = config_editor.list_manual_backups()
    auto_backups_files = config_editor.list_auto_backups()
    auto_backups = []
    for ab in auto_backups_files:
        auto_backups.append({"filename": os.path.basename(ab), "description": "Automatic backup"})

    return render_template("config_backup.html", manual_backups=manual_backups, auto_backups=auto_backups)


@app.route("/shutdown", methods=["POST"])
def shutdown():
    """
    Route to gracefully shut down the Flask development server.
    """
    shutdown_func = request.environ.get("werkzeug.server.shutdown")
    if shutdown_func is None:
        raise RuntimeError("Not running with the Werkzeug Server")
    shutdown_func()
    return "Server shutting down..."

@app.route("/download_config", methods=["GET"])
def download_config():
    """
    Route to download the current configuration file.
    """
    config_editor = current_app.config["config_editor"]
    return send_file(config_editor.config_file, as_attachment=True, download_name="auto_lights_conf.json")

@app.route("/upload_config", methods=["POST"])
def upload_config():
    """
    Route to upload a new configuration file.
    Before overwriting, the current config is backed up.
    """
    if "config_file_upload" not in request.files:
        flash("No file part in the request.")
        return redirect(url_for("config_backup"))
    file = request.files["config_file_upload"]
    if file.filename == "":
        flash("No file selected for uploading.")
        return redirect(url_for("config_backup"))
    config_editor = current_app.config["config_editor"]
    config_path = config_editor.config_file
    if os.path.exists(config_path):
        backup_dir = os.path.join(os.path.dirname(config_path), "auto_backups")
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_file = os.path.join(backup_dir, f"auto_backup_{timestamp}.json")
        shutil.copy2(config_path, backup_file)
    file.save(config_path)
    flash("Configuration file uploaded and current config backed up.")
    return redirect(url_for("config_backup"))


def run_flask_app(
    host: str = "127.0.0.1",
    port: int = 9500,
    debug: bool = False,
    config_file: str = None,
) -> None:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if config_file is None:
        config_dir = os.path.join(current_dir, "config")
        config_file = os.path.join(config_dir, "auto_lights_conf.json")
    else:
        config_dir = os.path.dirname(os.path.abspath(config_file))
    schema_file = os.path.join(current_dir, "config/config_schema.json")
    backup_dir = os.path.join(config_dir, "backups")
    auto_backup_dir = os.path.join(config_dir, "auto_backups")
    config_editor = WebConfigEditor(
        config_file, schema_file, backup_dir, auto_backup_dir
    )
    app.config["config_editor"] = config_editor
    app.jinja_env.globals["get_cached_indigo_variables"] = config_editor.get_cached_indigo_variables
    try:
        # Initialize caches via config_editor
        config_editor.get_cached_indigo_devices()
        config_editor.get_cached_indigo_variables()
        app.logger.info(f"[{datetime.now()}] Indigo caches initialized")
    except Exception as e:
        app.logger.error(f"Error initializing caches: {e}")

    config_editor.start_cache_refresher()
    app.run(host=host, port=port, debug=debug, use_reloader=False)


# JSON schema loaded at module level, so it can be referenced by multiple routes
current_dir = os.path.dirname(os.path.abspath(__file__))
schema_path = os.path.join(current_dir, "config", "config_schema.json")
with open(schema_path) as f:
    config_schema = json.load(f, object_pairs_hook=OrderedDict)

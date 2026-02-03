"""
IWS Web Handler for Auto Lights Plugin

This module handles HTTP requests through Indigo's Web Server (IWS) for the
Auto Lights configuration interface. It replaces the Flask-based web server
with a Jinja2-standalone implementation that integrates with IWS.
"""

import json
import logging
import os
import mimetypes
from typing import Dict, Any, Tuple, Optional
from urllib.parse import parse_qs, unquote_plus
from werkzeug.datastructures import MultiDict

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config_editor import WebConfigEditor
from .iws_form_helpers import generate_form_class_from_schema

# Try to import indigo for production use
try:
    import indigo
    HAS_INDIGO = True
except ImportError:
    HAS_INDIGO = False

logger = logging.getLogger("Plugin")


def create_reply_dict() -> Dict[str, Any]:
    """
    Create a reply dict for IWS responses.
    Uses indigo.Dict() in production, regular dict in tests.

    Returns:
        indigo.Dict() if indigo is available, otherwise {}
    """
    if HAS_INDIGO:
        return indigo.Dict()
    else:
        return {}


def create_headers_dict(headers: Dict[str, str]) -> Dict[str, str]:
    """
    Create a headers dict for IWS responses.
    Uses indigo.Dict() in production, regular dict in tests.

    Args:
        headers: Dictionary of header key-value pairs

    Returns:
        indigo.Dict(headers) if indigo is available, otherwise headers
    """
    if HAS_INDIGO:
        return indigo.Dict(headers)
    else:
        return headers


def dict_to_multidict(d: Dict[str, Any]) -> MultiDict:
    """
    Convert a regular dict to MultiDict for WTForms compatibility.

    IWS provides body_params as a dict where multi-value fields (like checkboxes
    or multi-selects) have list values. This function converts it to MultiDict
    format that WTForms expects.

    Handles edge cases:
    - indigo.List objects (IWS returns these for multi-select fields)
    - Nested lists are flattened (IWS sometimes wraps multi-values in extra list)
    - All values are converted to strings (WTForms expects string form data)

    Args:
        d: Dictionary from IWS body_params

    Returns:
        MultiDict with expanded list values as strings
    """
    items = []
    for key, value in d.items():
        # Check if value is list-like (handles both list and indigo.List)
        # Use duck typing: check for __iter__ but exclude strings
        is_list_like = (
            hasattr(value, '__iter__')
            and not isinstance(value, (str, bytes))
        )

        if is_list_like:
            # Convert to Python list to ensure we can iterate properly
            try:
                value_list = list(value)
            except (TypeError, ValueError):
                # If conversion fails, treat as single value
                items.append((key, str(value) if value is not None else ''))
                continue

            # Flatten and convert list values
            for v in value_list:
                # Check for nested list-like objects
                v_is_list_like = (
                    hasattr(v, '__iter__')
                    and not isinstance(v, (str, bytes))
                )
                if v_is_list_like:
                    # Nested list - flatten it
                    try:
                        for inner_v in list(v):
                            items.append((key, str(inner_v)))
                    except (TypeError, ValueError):
                        items.append((key, str(v)))
                else:
                    items.append((key, str(v)))
        else:
            items.append((key, str(value) if value is not None else ''))
    return MultiDict(items)


def create_html_response(html: str, status: int = 200) -> Dict[str, Any]:
    """
    Create an HTML response using indigo.Dict() format.

    Args:
        html: HTML content to return
        status: HTTP status code (default 200)

    Returns:
        Response dict (indigo.Dict() in production, regular dict in tests)
    """
    reply = create_reply_dict()
    reply["status"] = status
    reply["headers"] = create_headers_dict({"Content-Type": "text/html; charset=utf-8"})
    reply["content"] = html
    return reply


class IWSWebHandler:
    """
    Handles web requests through Indigo's Web Server (IWS) using Jinja2 for templating.
    """

    def __init__(self, config_editor: WebConfigEditor, plugin_id: str):
        """
        Initialize the IWS web handler.

        Args:
            config_editor: The WebConfigEditor instance for config management
            plugin_id: The plugin ID for generating IWS URLs
        """
        self.config_editor = config_editor
        self.plugin_id = plugin_id

        # Set up Jinja2 environment
        template_dir = os.path.join(os.path.dirname(__file__), 'templates')
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(['html', 'xml']),
        )

        # Register custom functions for templates
        self.jinja_env.globals['url_for'] = self._url_for
        self.jinja_env.globals['enumerate'] = enumerate
        self.jinja_env.globals['os'] = os
        self.jinja_env.globals['get_cached_indigo_variables'] = (
            self.config_editor.get_cached_indigo_variables
        )

        # Create a simple plugin object for templates (matches SDK pattern)
        # Templates can use {{ plugin.pluginId }} to reference the plugin ID
        class PluginRef:
            def __init__(self, plugin_id):
                self.pluginId = plugin_id

        self.jinja_env.globals['plugin'] = PluginRef(plugin_id)

        logger.debug("IWSWebHandler initialized")

    def _normalize_array_fields(self, data: dict, array_fields: list) -> dict:
        """
        Ensure array fields are never None (convert to empty list).

        WTForms can return None for empty array fields, which causes crashes
        when the config is reloaded. This function ensures all array fields
        are valid lists.

        Args:
            data: Dictionary to normalize
            array_fields: List of field names that should be arrays

        Returns:
            The same dictionary (modified in place) with normalized arrays
        """
        for field in array_fields:
            if data.get(field) is None:
                logger.debug(f"Normalizing field '{field}' from None to []")
                data[field] = []
        return data

    def _url_for(self, endpoint: str, **kwargs) -> str:
        """
        Generate IWS-compatible URLs to replace Flask's url_for().

        Args:
            endpoint: The route endpoint (e.g., 'zones', 'plugin_config')
            **kwargs: Additional URL parameters

        Returns:
            IWS URL string
        """
        # Static files - automatically served from Resources/static/ by IWS
        if endpoint == 'static':
            filename = kwargs.get('filename', '')
            return f"/{self.plugin_id}/static/{filename}"

        # Regular pages
        page_map = {
            'index': '',
            'zones': 'zones',
            'zone_config': f"zone/{kwargs.get('zone_id', '')}",
            'plugin_config': 'plugin_config',
            'lighting_periods': 'lighting_periods',
            'lighting_period_config': f"lighting_period/{kwargs.get('period_id', '')}",
            'config_backup': 'config_backup',
            'zone_delete': f"zone/delete/{kwargs.get('zone_id', '')}",
            'lighting_period_delete': f"lighting_period/delete/{kwargs.get('period_id', '')}",
            'create_new_variable': 'create_new_variable',
            'refresh_variables': 'refresh_variables',
            'get_luminance_value': 'get_luminance_value',
        }

        page = page_map.get(endpoint, endpoint)
        base_url = f"/message/{self.plugin_id}/web_ui/"

        if page:
            return f"{base_url}?page={page}"
        return base_url

    def handle_request(
        self,
        method: str,
        headers: Dict[str, str],
        body_params: Dict[str, Any],
        params: Dict[str, str] = None,
        request_body: str = ""
    ) -> Dict[str, Any]:
        """
        Handle an HTTP request from IWS.

        Args:
            method: HTTP method (GET, POST, etc.)
            headers: Request headers dict
            body_params: Pre-parsed POST body parameters from IWS (body_params)
            params: Pre-parsed URL query parameters from IWS (url_query_args)
            request_body: Raw request body (for JSON POST requests)

        Returns:
            Response dict with status, headers, and content
        """
        logger.debug(f"IWS Web Handler: {method} request received")

        # Use pre-parsed params from IWS (no manual parsing needed)
        if params is None:
            params = {}

        logger.debug(f"URL query params: {params}")

        try:
            # Extract page parameter (IWS provides params as dict, not list)
            page = params.get('page', '')  # Get value directly (already parsed by IWS)
            logger.debug(f"Extracted page parameter: '{page}' (type: {type(page).__name__})")
            logger.debug(f"Page is empty: {not page}, Page == 'index': {page == 'index'}")
            logger.debug(f"Will render page: {page if page else 'index (default)'}")

            # Route to appropriate handler
            if method == "GET":
                return self._handle_get(page, params)
            elif method == "POST":
                return self._handle_post(page, body_params, params, request_body)
            else:
                return self._error_response(405, "Method Not Allowed")

        except Exception as e:
            logger.exception(f"Error handling IWS request: {e}")
            return self._error_response(500, f"Internal Server Error: {str(e)}")

    def _handle_get(self, page: str, params: Dict[str, str]) -> Dict[str, Any]:
        """Handle GET requests with pre-parsed params from IWS."""
        logger.debug(f"_handle_get called with page='{page}'")

        # Flash messages are no longer passed via URL (POST/re-render pattern, not POST/redirect/GET)
        flash = {}

        # Route to appropriate page handler (pass flash messages)
        if not page or page == 'index':
            logger.debug("Routing to: _render_index (page is empty or 'index')")
            return self._render_index(flash)
        elif page == 'zones':
            logger.debug("Routing to: _render_zones")
            return self._render_zones(flash)
        elif page.startswith('zone/'):
            zone_id = page.split('/')[-1]
            logger.debug(f"Routing to: _render_zone_edit with zone_id='{zone_id}'")
            return self._render_zone_edit(zone_id, flash)
        elif page == 'plugin_config':
            logger.debug("Routing to: _render_plugin_config")
            return self._render_plugin_config(flash)
        elif page == 'lighting_periods':
            logger.debug("Routing to: _render_lighting_periods")
            return self._render_lighting_periods(flash)
        elif page.startswith('lighting_period/'):
            period_id = page.split('/')[-1]
            logger.debug(f"Routing to: _render_lighting_period_edit with period_id='{period_id}'")
            return self._render_lighting_period_edit(period_id, flash)
        elif page == 'config_backup':
            logger.debug("Routing to: _render_config_backup")
            return self._render_config_backup(flash)
        else:
            logger.warning(f"No route matched for page='{page}', returning 404")
            return self._error_response(404, f"Page not found: {page}")

    def _handle_post(self, page: str, body_params: Dict[str, Any], params: Dict[str, str], request_body: str = "") -> Dict[str, Any]:
        """Handle POST requests with pre-parsed body_params from IWS."""
        logger.debug(f"POST to page: {page}")
        logger.debug(f"Body params keys: {list(body_params.keys())}")

        # Route to specific POST handler
        if not page or page == 'zones':
            return self._post_zones(body_params)
        elif page.startswith('zone/delete/'):
            zone_id = page.split('/')[-1]
            return self._post_zone_delete(zone_id)
        elif page.startswith('zone/'):
            zone_id = page.split('/')[-1]
            return self._post_zone_save(zone_id, body_params)
        elif page == 'plugin_config':
            return self._post_plugin_config(body_params)
        elif page == 'lighting_periods':
            return self._post_lighting_periods(body_params)
        elif page.startswith('lighting_period/delete/'):
            period_id = page.split('/')[-1]
            return self._post_lighting_period_delete(period_id)
        elif page.startswith('lighting_period/'):
            period_id = page.split('/')[-1]
            return self._post_lighting_period_save(period_id, body_params)
        elif page == 'config_backup':
            return self._post_config_backup(body_params)
        elif page == 'create_new_variable':
            return self._post_create_variable(body_params)
        elif page == 'refresh_variables':
            return self._post_refresh_variables()
        elif page == 'get_luminance_value':
            return self._post_get_luminance_value(request_body)
        else:
            return self._error_response(404, f"Unknown POST endpoint: {page}")

    def _post_zone_save(self, zone_id: str, body_params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle zone save POST."""
        flash = {}

        try:
            # Convert IWS body_params dict to MultiDict for WTForms
            form_data = dict_to_multidict(body_params)

            # Load config
            config_data = self.config_editor.load_config()
            zones_data = config_data.get("zones", [])
            zone_schema = self.config_editor.config_schema["properties"]["zones"]["items"]

            # Generate form and populate with POST data
            ZonesFormClass = generate_form_class_from_schema(zone_schema)
            zone_form = ZonesFormClass(formdata=form_data)

            # Extract data
            zone_data = {
                field_name: field.data
                for field_name, field in zone_form._fields.items()
                if field_name != "submit"
            }

            # Ensure top-level array fields are never None
            self._normalize_array_fields(zone_data, ["lighting_period_ids"])

            # Ensure nested array fields in device_settings are never None
            if "device_settings" in zone_data and zone_data["device_settings"]:
                self._normalize_array_fields(zone_data["device_settings"], [
                    "on_lights_dev_ids",
                    "off_lights_dev_ids",
                    "luminance_dev_ids",
                    "presence_dev_ids"
                ])

            # Ensure nested array fields in advanced_settings are never None
            if "advanced_settings" in zone_data and zone_data["advanced_settings"]:
                self._normalize_array_fields(zone_data["advanced_settings"], [
                    "exclude_from_lock_dev_ids"
                ])

            # Save based on new or existing
            if zone_id == "new":
                zones_data.append(zone_data)
                config_data["zones"] = zones_data
                self.config_editor.save_config(config_data)

                # Re-render zones list with success message
                flash["message"] = "New zone created successfully"
                return self._render_zones(flash)
            else:
                index = int(zone_id)
                zones_data[index] = zone_data
                config_data["zones"] = zones_data
                self.config_editor.save_config(config_data)

                # Re-render zone edit page with success message
                flash["message"] = "Zone updated successfully"
                return self._render_zone_edit(zone_id, flash)

        except Exception as e:
            logger.exception(f"Error saving zone: {e}")
            flash["error"] = f"Error saving zone: {str(e)}"
            # Try to render the appropriate page based on zone_id
            if zone_id == "new":
                return self._render_zones(flash)
            else:
                return self._render_zone_edit(zone_id, flash)

    def _post_zone_delete(self, zone_id: str) -> Dict[str, Any]:
        """Handle zone delete."""
        flash = {}

        try:
            config_data = self.config_editor.load_config()
            zones_data = config_data.get("zones", [])

            index = int(zone_id)
            if 0 <= index < len(zones_data):
                deleted_zone = zones_data.pop(index)
                config_data["zones"] = zones_data
                self.config_editor.save_config(config_data)
                flash["message"] = f"Zone '{deleted_zone.get('name', index)}' deleted successfully"
            else:
                flash["error"] = "Invalid zone index"

        except Exception as e:
            logger.exception(f"Error deleting zone: {e}")
            flash["error"] = f"Error deleting zone: {str(e)}"

        # Re-render zones list page
        return self._render_zones(flash)

    def _post_zones(self, body_params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle zones list update (if needed)."""
        # This may not be used, but included for completeness
        return self._render_zones({})

    def _post_plugin_config(self, body_params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle plugin config save."""
        flash = {}

        try:
            logger.debug("_post_plugin_config: Starting plugin config save")
            logger.debug(f"_post_plugin_config: Body params keys: {list(body_params.keys())}")

            form_data = dict_to_multidict(body_params)
            logger.debug(f"_post_plugin_config: Parsed form data keys: {list(form_data.keys())}")

            config_data = self.config_editor.load_config()
            plugin_schema = self.config_editor.config_schema["properties"]["plugin_config"]

            PluginFormClass = generate_form_class_from_schema(plugin_schema)
            plugin_form = PluginFormClass(formdata=form_data)

            plugin_config = {
                field_name: field.data
                for field_name, field in plugin_form._fields.items()
                if field_name != "submit"
            }

            # Ensure array fields are never None (prevents crashes on reload)
            self._normalize_array_fields(plugin_config, ["global_behavior_variables"])

            logger.debug(f"_post_plugin_config: Extracted plugin_config keys: {list(plugin_config.keys())}")
            logger.debug(f"_post_plugin_config: plugin_config types: {[(k, type(v).__name__) for k, v in plugin_config.items()]}")

            config_data["plugin_config"] = plugin_config
            logger.debug("_post_plugin_config: Calling save_config")
            self.config_editor.save_config(config_data)
            logger.debug("_post_plugin_config: save_config completed")

            # Re-render plugin config page with success message
            flash["message"] = "Plugin configuration saved successfully"
            logger.debug("_post_plugin_config: Re-rendering plugin config page with success message")
            return self._render_plugin_config(flash)

        except Exception as e:
            logger.exception(f"Error saving plugin config: {e}")
            flash["error"] = f"Error saving: {str(e)}"
            return self._render_plugin_config(flash)

    def _post_lighting_periods(self, body_params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle lighting periods save."""
        return self._render_lighting_periods({})

    def _post_lighting_period_save(self, period_id: str, body_params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle lighting period save."""
        logger.debug(f"Saving lighting period: period_id='{period_id}', body_params_keys={list(body_params.keys())}")
        flash = {}

        try:
            form_data = dict_to_multidict(body_params)
            logger.debug(f"Form data parsed successfully")

            config_data = self.config_editor.load_config()
            periods_data = config_data.get("lighting_periods", [])
            period_schema = self.config_editor.config_schema["properties"]["lighting_periods"]["items"]

            PeriodFormClass = generate_form_class_from_schema(period_schema)
            period_form = PeriodFormClass(formdata=form_data)
            logger.debug(f"Period form created successfully")

            # Extract form data, excluding submit button and id field (id is always set programmatically)
            period_data = {
                field_name: field.data
                for field_name, field in period_form._fields.items()
                if field_name not in ["submit", "id"]
            }
            logger.debug(f"Extracted period_data fields (without id): {list(period_data.keys())}")

            # Apply schema defaults for None values (prevents errors during config reload)
            # This mirrors the defensive validation in _render_lighting_periods()
            if period_data.get("name") is None:
                period_data["name"] = "New Lighting Period"
            if period_data.get("mode") is None:
                period_data["mode"] = "On and Off"
            if period_data.get("from_time_hour") is None:
                period_data["from_time_hour"] = 0
            if period_data.get("from_time_minute") is None:
                period_data["from_time_minute"] = 0
            if period_data.get("to_time_hour") is None:
                period_data["to_time_hour"] = 23
            if period_data.get("to_time_minute") is None:
                period_data["to_time_minute"] = 45
            if period_data.get("lock_duration") is None:
                period_data["lock_duration"] = -1
            if period_data.get("limit_brightness") is None:
                period_data["limit_brightness"] = -1

            if period_id == "new":
                # Generate new integer ID (max existing ID + 1)
                existing_ids = [p.get("id", 0) for p in periods_data if isinstance(p.get("id"), int)]
                new_id = max(existing_ids, default=0) + 1
                period_data["id"] = new_id
                periods_data.append(period_data)
                config_data["lighting_periods"] = periods_data
                self.config_editor.save_config(config_data)

                # Re-render the lighting periods list page with success message
                flash["message"] = "New lighting period created successfully"
                return self._render_lighting_periods(flash)
            else:
                # Update existing (convert period_id to integer)
                try:
                    period_id_int = int(period_id)
                    for i, period in enumerate(periods_data):
                        if period.get("id") == period_id_int:
                            period_data["id"] = period_id_int  # Preserve ID as integer
                            periods_data[i] = period_data
                            break
                    config_data["lighting_periods"] = periods_data
                    self.config_editor.save_config(config_data)

                    # Re-render the edit page with success message
                    flash["message"] = "Lighting period updated successfully"
                    return self._render_lighting_period_edit(period_id, flash)
                except ValueError:
                    flash["error"] = f"Invalid period ID: {period_id}"
                    return self._render_lighting_periods(flash)

        except Exception as e:
            logger.exception(f"Error saving lighting period: {e}")
            flash["error"] = f"Error saving: {str(e)}"
            # Try to render the edit page, fall back to list if period_id is invalid
            if period_id == "new":
                return self._render_lighting_periods(flash)
            else:
                return self._render_lighting_period_edit(period_id, flash)

    def _post_lighting_period_delete(self, period_id: str) -> Dict[str, Any]:
        """Handle lighting period delete."""
        flash = {}

        try:
            config_data = self.config_editor.load_config()
            periods_data = config_data.get("lighting_periods", [])

            # Convert period_id to integer
            try:
                period_id_int = int(period_id)
            except ValueError:
                flash["error"] = f"Invalid period ID: {period_id}"
                return self._render_lighting_periods(flash)

            # Find and remove the period
            period = next((p for p in periods_data if p.get("id") == period_id_int), None)

            if period:
                periods_data.remove(period)
                config_data["lighting_periods"] = periods_data
                self.config_editor.save_config(config_data)
                flash["message"] = f"Lighting period '{period.get('name', period_id)}' deleted successfully"
            else:
                flash["error"] = f"Lighting period {period_id} not found"

        except Exception as e:
            logger.exception(f"Error deleting lighting period: {e}")
            flash["error"] = f"Error deleting: {str(e)}"

        # Re-render lighting periods list page
        return self._render_lighting_periods(flash)

    def _post_config_backup(self, body_params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle config backup operations."""
        flash = {}
        form_data = body_params
        action = form_data.get("action")

        try:
            if action == "create_manual_backup":
                self.config_editor.create_manual_backup()
                flash["message"] = "Manual backup created successfully"
            elif action == "restore":
                backup_type = form_data.get("backup_type")
                backup_file = form_data.get("backup_file")
                if self.config_editor.restore_backup(backup_type, backup_file):
                    flash["message"] = "Configuration restored successfully"
                else:
                    flash["error"] = "Backup file not found"
            elif action == "delete":
                backup_type = form_data.get("backup_type")
                backup_file = form_data.get("backup_file")
                if self.config_editor.delete_backup(backup_type, backup_file):
                    flash["message"] = "Backup deleted successfully"
                else:
                    flash["error"] = "Could not delete backup"
            elif action == "download":
                # Download action returns file directly, no re-render
                backup_type = form_data.get("backup_type")
                backup_file = form_data.get("backup_file")
                return self._download_backup_file(backup_type, backup_file)
            elif action == "download_config":
                # Download current config returns file directly, no re-render
                return self._get_download_config()
            elif action == "reset_defaults":
                # Reset defaults has its own re-render logic
                return self._post_reset_defaults()
            elif action == "upload_config":
                # Upload config has its own logic
                return self._post_upload_config(body_params)
            else:
                flash["error"] = "Unknown action"

        except Exception as e:
            logger.exception(f"Error in config backup operation: {e}")
            flash["error"] = f"Error: {str(e)}"

        # Re-render config backup page (except for download/reset/upload which return early)
        return self._render_config_backup(flash)

    def _post_create_variable(self, body_params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle create new variable API endpoint."""
        try:
            from .tools.indigo_api_tools import indigo_create_new_variable
            # IWS pre-parses JSON POST bodies into body_params
            var_name = body_params.get("var_name")
            var_id = indigo_create_new_variable(var_name)
            reply = create_reply_dict()
            reply["status"] = 200
            reply["headers"] = create_headers_dict({"Content-Type": "application/json"})
            reply["content"] = json.dumps({"var_id": var_id})
            return reply
        except Exception as e:
            logger.exception(f"Error creating variable: {e}")
            reply = create_reply_dict()
            reply["status"] = 500
            reply["headers"] = create_headers_dict({"Content-Type": "application/json"})
            reply["content"] = json.dumps({"error": str(e)})
            return reply

    def _post_refresh_variables(self) -> Dict[str, Any]:
        """Handle refresh variables API endpoint."""
        try:
            variables = self.config_editor.get_cached_indigo_variables()
            reply = create_reply_dict()
            reply["status"] = 200
            reply["headers"] = create_headers_dict({"Content-Type": "application/json"})
            reply["content"] = json.dumps(variables)
            return reply
        except Exception as e:
            logger.exception(f"Error refreshing variables: {e}")
            reply = create_reply_dict()
            reply["status"] = 500
            reply["headers"] = create_headers_dict({"Content-Type": "application/json"})
            reply["content"] = json.dumps({"error": str(e)})
            return reply

    def _post_get_luminance_value(self, request_body: str) -> Dict[str, Any]:
        """
        Handle get_luminance_value API endpoint.

        Computes the average luminance from a list of device IDs sent as JSON.

        Args:
            request_body: Raw JSON request body with {"device_ids": [id1, id2, ...]}

        Returns:
            JSON response with {"average": float}
        """
        try:
            # Parse JSON from request body
            import json as json_module
            data = json_module.loads(request_body) if request_body else {}
            device_ids = data.get("device_ids", [])

            if not device_ids:
                reply = create_reply_dict()
                reply["status"] = 200
                reply["headers"] = create_headers_dict({"Content-Type": "application/json"})
                reply["content"] = json.dumps({"average": 0})
                return reply

            # Get sensor values from Indigo devices
            import indigo
            sensor_values = []
            for dev_id in device_ids:
                try:
                    dev = indigo.devices[int(dev_id)]
                    if hasattr(dev, 'sensorValue'):
                        sensor_value = dev.sensorValue
                        if sensor_value is not None:
                            sensor_values.append(float(sensor_value))
                except (KeyError, ValueError, AttributeError) as e:
                    logger.debug(f"Could not get sensor value for device {dev_id}: {e}")
                    continue

            # Calculate average
            avg = sum(sensor_values) / len(sensor_values) if sensor_values else 0

            reply = create_reply_dict()
            reply["status"] = 200
            reply["headers"] = create_headers_dict({"Content-Type": "application/json"})
            reply["content"] = json.dumps({"average": avg})
            return reply

        except Exception as e:
            logger.exception(f"Error getting luminance value: {e}")
            reply = create_reply_dict()
            reply["status"] = 500
            reply["headers"] = create_headers_dict({"Content-Type": "application/json"})
            reply["content"] = json.dumps({"error": str(e), "average": 0})
            return reply

    def _render_index(self, flash: Optional[Dict[str, Optional[str]]] = None) -> Dict[str, Any]:
        """Render the index/home page."""
        template = self.jinja_env.get_template('index.html')
        html = template.render(flash=flash or {})
        return create_html_response(html)

    def _render_zones(self, flash: Optional[Dict[str, Optional[str]]] = None) -> Dict[str, Any]:
        """Render the zones list page."""
        logger.debug(f"_render_zones called with flash={flash}")
        try:
            # Load config and schema
            logger.debug("Loading config data...")
            config_data = self.config_editor.load_config()
            zones_data = config_data.get("zones", [])
            logger.debug(f"Loaded {len(zones_data)} zones from config")

            # Generate form class from schema
            logger.debug("Generating form class from schema...")
            zone_schema = self.config_editor.config_schema["properties"]["zones"]["items"]
            ZonesFormClass = generate_form_class_from_schema(zone_schema)

            # Create form for each zone with data validation
            logger.debug(f"Creating {len(zones_data)} zone forms...")
            zones_forms = []
            for idx, zone in enumerate(zones_data):
                logger.debug(f"Processing zone {idx}: {zone.get('name', 'unnamed')}")

                # Validate and fix array fields (prevent "bool is not iterable" errors)
                # Array fields in zone schema: lighting_period_ids, on_lights_dev_ids, off_lights_dev_ids, luminance_dev_ids, presence_dev_ids
                array_fields = ['lighting_period_ids']
                if 'device_settings' in zone:
                    for field in ['on_lights_dev_ids', 'off_lights_dev_ids', 'luminance_dev_ids', 'presence_dev_ids']:
                        if field in zone['device_settings']:
                            value = zone['device_settings'][field]
                            if not isinstance(value, list):
                                logger.warning(f"Zone {idx} device_settings.{field} is {type(value).__name__}, coercing to empty list")
                                zone['device_settings'][field] = []

                # Validate array fields in advanced_settings
                if 'advanced_settings' in zone:
                    for field in ['exclude_from_lock_dev_ids']:
                        if field in zone['advanced_settings']:
                            value = zone['advanced_settings'][field]
                            if not isinstance(value, list):
                                logger.warning(f"Zone {idx} advanced_settings.{field} is {type(value).__name__}, coercing to empty list")
                                zone['advanced_settings'][field] = []

                for field in array_fields:
                    if field in zone:
                        value = zone[field]
                        if not isinstance(value, list):
                            logger.warning(f"Zone {idx} {field} is {type(value).__name__} ({value}), coercing to empty list")
                            zone[field] = []

                try:
                    zone_form = ZonesFormClass(data=zone)
                    zones_forms.append(zone_form)
                    logger.debug(f"Successfully created form for zone {idx}")
                except Exception as e:
                    logger.exception(f"Error creating form for zone {idx} ({zone.get('name', 'unnamed')}): {e}")
                    raise

            # Render template
            logger.debug("Rendering zones.html template...")
            template = self.jinja_env.get_template('zones.html')
            html = template.render(zones_forms=zones_forms, flash=flash or {})
            logger.debug(f"Template rendered successfully, HTML length: {len(html)} bytes")

            logger.debug("Returning zones page response with status 200")
            return create_html_response(html)
        except Exception as e:
            logger.exception(f"Error rendering zones page: {e}")
            return self._error_response(500, f"Error rendering zones: {str(e)}")

    def _render_zone_edit(self, zone_id: str, flash: Optional[Dict[str, Optional[str]]] = None) -> Dict[str, Any]:
        """Render the zone edit page."""
        try:
            # Load config and data
            config_data = self.config_editor.load_config()
            zones_data = config_data.get("zones", [])
            zone_schema = self.config_editor.config_schema["properties"]["zones"]["items"]

            # Determine if creating new or editing existing
            if zone_id == "new":
                # Create new zone with defaults
                defaults = {}
                for field, subschema in zone_schema.get("properties", {}).items():
                    if "default" in subschema:
                        defaults[field] = subschema["default"]
                zone = defaults
                is_new = True
            else:
                # Load existing zone
                try:
                    index = int(zone_id)
                    if index < 0 or index >= len(zones_data):
                        return self._error_response(404, f"Zone index {index} not found")
                    zone = zones_data[index]
                    is_new = False
                except ValueError:
                    return self._error_response(400, f"Invalid zone ID: {zone_id}")

            # Generate form class and create instance
            ZonesFormClass = generate_form_class_from_schema(zone_schema)
            zone_form = ZonesFormClass(data=zone)

            # Update choices for lighting period dropdown
            try:
                lighting_periods = config_data.get("lighting_periods", [])
                period_choices = [(period.get("id"), period.get("name", f"Period {period.get('id')}"))
                                 for period in lighting_periods]

                if hasattr(zone_form, 'lighting_period_ids'):
                    zone_form.lighting_period_ids.choices = period_choices

            except Exception as e:
                logger.warning(f"Could not update lighting period choices: {e}")

            # Update choices for device dropdowns with cached data (filtered by device class)
            try:
                devices = self.config_editor.get_cached_indigo_devices()
                logger.debug(f"[Zone Edit] Got {len(devices)} devices from cache")

                # Get schema for device_settings to access x-include-device-classes
                device_settings_schema = zone_schema.get("properties", {}).get("device_settings", {})
                device_fields_schema = device_settings_schema.get("properties", {})

                # Helper function to filter devices by allowed classes
                def filter_devices_by_class(devices, allowed_classes_str):
                    if not allowed_classes_str:
                        return devices
                    allowed_classes = {cls.strip() for cls in allowed_classes_str.split(",")}

                    # Debug: Show sample device classes
                    if devices:
                        sample_classes = set()
                        for d in devices[:10]:  # Sample first 10 devices
                            sample_classes.add(d.get("class", ""))
                        logger.debug(f"[Zone Edit] Sample device classes from cache: {sample_classes}")
                        logger.debug(f"[Zone Edit] Looking for classes: {allowed_classes}")

                    filtered = []
                    for d in devices:
                        device_class = str(d.get("class", "")).strip()
                        device_type_id = str(d.get("deviceTypeId", "")).strip()
                        # Check if device class OR deviceTypeId matches any allowed class
                        # (native devices match by class, plugin devices match by deviceTypeId)
                        if device_class in allowed_classes or device_type_id in allowed_classes:
                            filtered.append(d)
                    return filtered

                # Update device selection fields with filtered choices
                if hasattr(zone_form, 'device_settings'):
                    logger.debug("[Zone Edit] zone_form has device_settings")
                    logger.debug(f"[Zone Edit] device_settings type: {type(zone_form.device_settings)}")
                    logger.debug(f"[Zone Edit] device_settings has .form: {hasattr(zone_form.device_settings, 'form')}")

                    # Access the nested form using .form attribute
                    device_form = zone_form.device_settings.form
                    logger.debug(f"[Zone Edit] device_form type: {type(device_form)}")
                    logger.debug(f"[Zone Edit] device_form fields: {list(device_form._fields.keys())}")

                    device_fields = ['on_lights_dev_ids', 'off_lights_dev_ids',
                                    'luminance_dev_ids', 'presence_dev_ids']
                    for field_name in device_fields:
                        logger.debug(f"[Zone Edit] Checking field: {field_name}")
                        if hasattr(device_form, field_name):
                            # Get allowed classes from schema
                            field_schema = device_fields_schema.get(field_name, {})
                            allowed_classes = field_schema.get("x-include-device-classes", "")
                            logger.debug(f"[Zone Edit] Field {field_name} allowed classes: {allowed_classes}")

                            # Filter devices and create choices
                            filtered_devices = filter_devices_by_class(devices, allowed_classes)
                            field_choices = [(d["id"], d["name"]) for d in filtered_devices]
                            logger.debug(f"[Zone Edit] Field {field_name} filtered to {len(field_choices)} choices")

                            # Update field choices
                            field_obj = getattr(device_form, field_name)
                            logger.debug(f"[Zone Edit] Field {field_name} type: {type(field_obj)}")
                            logger.debug(f"[Zone Edit] Field {field_name} before choices: {len(field_obj.choices) if hasattr(field_obj, 'choices') else 'N/A'}")
                            field_obj.choices = field_choices
                            logger.debug(f"[Zone Edit] Field {field_name} after choices: {len(field_obj.choices)}")
                        else:
                            logger.warning(f"[Zone Edit] device_form does NOT have {field_name}")
                else:
                    logger.warning("[Zone Edit] zone_form does NOT have device_settings attribute")

            except Exception as e:
                logger.exception(f"[Zone Edit] Could not update device choices: {e}")

            # Update variable dropdowns
            try:
                variables = self.config_editor.get_cached_indigo_variables()
                var_choices = [(-1, "None Selected")] + [(v["id"], v["name"]) for v in variables]

                # Helper function to update _var_id fields recursively
                def update_var_id_fields(form_obj):
                    for field_name, field in form_obj._fields.items():
                        if field_name.endswith("_var_id"):
                            field.choices = var_choices
                        # Recursively handle nested FormFields
                        elif hasattr(field, 'form'):
                            update_var_id_fields(field.form)

                # Update all _var_id fields (including nested ones)
                update_var_id_fields(zone_form)

            except Exception as e:
                logger.warning(f"Could not update variable choices: {e}")

            # Update choices for advanced settings device dropdowns
            try:
                devices = self.config_editor.get_cached_indigo_devices()

                # Get the zone's on_lights and off_lights device IDs
                device_settings = zone.get("device_settings", {})
                on_lights_ids = set(device_settings.get("on_lights_dev_ids", []) or [])
                off_lights_ids = set(device_settings.get("off_lights_dev_ids", []) or [])

                # Combine both lists - these are the only valid choices for exclude_from_lock
                allowed_device_ids = on_lights_ids | off_lights_ids

                # Filter to only devices in on_lights or off_lights
                device_choices = [(d["id"], d["name"]) for d in devices if d["id"] in allowed_device_ids]

                if hasattr(zone_form, 'advanced_settings'):
                    advanced_form = zone_form.advanced_settings.form
                    if hasattr(advanced_form, 'exclude_from_lock_dev_ids'):
                        advanced_form.exclude_from_lock_dev_ids.choices = device_choices

            except Exception as e:
                logger.warning(f"Could not update advanced settings device choices: {e}")

            # Configure global_behavior_variables_map field
            try:
                from .iws_form_helpers import GlobalBehaviorMapWidget

                plugin_config = config_data.get("plugin_config", {})
                global_vars = plugin_config.get("global_behavior_variables", [])
                # Get variable IDs from global_behavior_variables
                wanted_var_ids = {g.get("var_id") for g in global_vars if g.get("var_id")}

                # Filter cached variables to only those in global_behavior_variables
                variables = self.config_editor.get_cached_indigo_variables()
                filtered_vars = [v for v in variables if v["id"] in wanted_var_ids]

                # Configure the field with filtered variables
                if hasattr(zone_form, 'global_behavior_variables_map'):
                    zone_form.global_behavior_variables_map.variables = filtered_vars
                    # Re-create widget with updated variables list
                    zone_form.global_behavior_variables_map.widget = GlobalBehaviorMapWidget(filtered_vars)

            except Exception as e:
                logger.warning(f"Could not configure global_behavior_variables_map: {e}")

            # Configure device_period_map field
            try:
                from .iws_form_helpers import DevicePeriodMapWidget

                # Get devices and filter to only on_lights for this zone
                devices = self.config_editor.get_cached_indigo_devices()
                on_light_ids = zone.get("device_settings", {}).get("on_lights_dev_ids", [])
                filtered_devices = [d for d in devices if d["id"] in on_light_ids]

                # Get lighting periods and filter to only those linked to this zone
                lighting_periods = config_data.get("lighting_periods", [])
                period_ids = zone.get("lighting_period_ids", [])
                # Filter by period ID (not array index)
                filtered_periods = [p for p in lighting_periods if p.get("id") in period_ids]

                # Configure the field with filtered devices and periods
                if hasattr(zone_form, 'device_period_map'):
                    zone_form.device_period_map.devices = filtered_devices
                    zone_form.device_period_map.lighting_periods = filtered_periods
                    # Re-create widget with updated data
                    zone_form.device_period_map.widget = DevicePeriodMapWidget(filtered_devices, filtered_periods)

            except Exception as e:
                logger.warning(f"Could not configure device_period_map: {e}")

            # Render template
            template = self.jinja_env.get_template('zone_edit.html')
            html = template.render(zone_form=zone_form, index=zone_id, flash=flash or {})

            return create_html_response(html)

        except Exception as e:
            logger.exception(f"Error rendering zone edit page: {e}")
            return self._error_response(500, f"Error rendering zone edit: {str(e)}")

    def _render_plugin_config(self, flash: Optional[Dict[str, Optional[str]]] = None) -> Dict[str, Any]:
        """Render the plugin configuration page."""
        try:
            config_data = self.config_editor.load_config()
            plugin_config = config_data.get("plugin_config", {})

            # Generate form from schema
            plugin_schema = self.config_editor.config_schema["properties"]["plugin_config"]
            PluginFormClass = generate_form_class_from_schema(plugin_schema)
            plugin_form = PluginFormClass(data=plugin_config)

            # Update variable choices
            try:
                variables = self.config_editor.get_cached_indigo_variables()
                var_choices = [(-1, "None Selected")] + [(v["id"], v["name"]) for v in variables]
                for field_name, field in plugin_form._fields.items():
                    if field_name.endswith("_var_id"):
                        field.choices = var_choices
            except Exception as e:
                logger.warning(f"Could not update variable choices: {e}")

            template = self.jinja_env.get_template('plugin_edit.html')
            html = template.render(plugin_form=plugin_form, flash=flash or {})

            return create_html_response(html)
        except Exception as e:
            logger.exception(f"Error rendering plugin config page: {e}")
            return self._error_response(500, f"Error rendering plugin config: {str(e)}")

    def _render_lighting_periods(self, flash: Optional[Dict[str, Optional[str]]] = None) -> Dict[str, Any]:
        """Render the lighting periods list page."""
        try:
            config_data = self.config_editor.load_config()
            periods_data = config_data.get("lighting_periods", [])
            zones_data = config_data.get("zones", [])

            # Generate form class from schema
            period_schema = self.config_editor.config_schema["properties"]["lighting_periods"]["items"]
            PeriodFormClass = generate_form_class_from_schema(period_schema)

            # Validate and fix null values in period data before creating forms
            for idx, period in enumerate(periods_data):
                # Apply defaults to prevent template rendering errors
                if period.get("name") is None:
                    period["name"] = "Unnamed Lighting Period"
                if period.get("mode") is None:
                    period["mode"] = "On and Off"
                if period.get("from_time_hour") is None:
                    period["from_time_hour"] = 0
                if period.get("from_time_minute") is None:
                    period["from_time_minute"] = 0
                if period.get("to_time_hour") is None:
                    period["to_time_hour"] = 23
                if period.get("to_time_minute") is None:
                    period["to_time_minute"] = 45

            # Create form for each period
            period_forms = [PeriodFormClass(data=period) for period in periods_data]

            template = self.jinja_env.get_template('lighting_periods.html')
            html = template.render(
                lighting_periods_forms=period_forms,
                zones=zones_data,
                flash=flash or {}
            )

            return create_html_response(html)
        except Exception as e:
            logger.exception(f"Error rendering lighting periods page: {e}")
            return self._error_response(500, f"Error rendering lighting periods: {str(e)}")

    def _render_lighting_period_edit(self, period_id: str, flash: Optional[Dict[str, Optional[str]]] = None) -> Dict[str, Any]:
        """Render the lighting period edit page."""
        try:
            config_data = self.config_editor.load_config()
            periods_data = config_data.get("lighting_periods", [])
            period_schema = self.config_editor.config_schema["properties"]["lighting_periods"]["items"]

            # Determine if creating new or editing existing
            if period_id == "new":
                # Create new period with defaults
                defaults = {}
                for field, subschema in period_schema.get("properties", {}).items():
                    if "default" in subschema:
                        defaults[field] = subschema["default"]
                period = defaults
                is_new = True
            else:
                # Find existing period by ID (convert string to integer)
                try:
                    period_id_int = int(period_id)
                    period = next((p for p in periods_data if p.get("id") == period_id_int), None)
                    if not period:
                        return self._error_response(404, f"Lighting period {period_id} not found")
                    is_new = False
                except ValueError:
                    return self._error_response(400, f"Invalid period ID: {period_id}")

            # Generate form
            PeriodFormClass = generate_form_class_from_schema(period_schema)
            period_form = PeriodFormClass(data=period)

            template = self.jinja_env.get_template('lighting_period_edit.html')
            html = template.render(lighting_period_form=period_form, period_id=period_id, flash=flash or {})

            return create_html_response(html)
        except Exception as e:
            logger.exception(f"Error rendering lighting period edit page: {e}")
            return self._error_response(500, f"Error rendering lighting period edit: {str(e)}")

    def _render_config_backup(self, flash: Optional[Dict[str, Optional[str]]] = None) -> Dict[str, Any]:
        """Render the config backup page."""
        try:
            # Get backup lists from config editor
            manual_backups_raw = self.config_editor.list_manual_backups()
            auto_backups_raw = self.config_editor.list_auto_backups()

            # Convert to dictionaries for template compatibility
            manual_backups = [{"filename": filename} for filename in manual_backups_raw]

            # Extract filenames and create dict structure for auto backups
            auto_backups = [
                {
                    "filename": os.path.basename(path),
                    "description": "Automatic backup"
                }
                for path in auto_backups_raw
            ]

            template = self.jinja_env.get_template('config_backup.html')
            html = template.render(
                manual_backups=manual_backups,
                auto_backups=auto_backups,
                flash=flash or {}
            )

            return create_html_response(html)
        except Exception as e:
            logger.exception(f"Error rendering config backup page: {e}")
            return self._error_response(500, f"Error rendering config backup: {str(e)}")

    def _get_download_config(self) -> Dict[str, Any]:
        """Handle download current config request."""
        try:
            config_data = self.config_editor.load_config()
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"autolights_config_{timestamp}.json"

            reply = create_reply_dict()
            reply["status"] = 200
            reply["headers"] = create_headers_dict({
                "Content-Type": "application/json",
                "Content-Disposition": f'attachment; filename="{filename}"'
            })
            reply["content"] = json.dumps(config_data, indent=2)
            return reply
        except Exception as e:
            logger.exception(f"Error downloading config: {e}")
            return self._error_response(500, f"Error downloading config: {str(e)}")

    def _download_backup_file(self, backup_type: str, backup_file: str) -> Dict[str, Any]:
        """Download a specific backup file."""
        flash = {}

        try:
            if backup_type == "manual":
                backup_path = os.path.join(self.config_editor.backup_dir, backup_file)
            else:
                backup_path = os.path.join(self.config_editor.auto_backup_dir, backup_file)

            if not os.path.exists(backup_path):
                flash["error"] = "Backup file not found"
                return self._render_config_backup(flash)

            with open(backup_path, 'r') as f:
                content = f.read()

            reply = create_reply_dict()
            reply["status"] = 200
            reply["headers"] = create_headers_dict({
                "Content-Type": "application/json",
                "Content-Disposition": f'attachment; filename="{backup_file}"'
            })
            reply["content"] = content
            return reply
        except Exception as e:
            logger.exception(f"Error downloading backup: {e}")
            flash["error"] = f"Error downloading backup: {str(e)}"
            return self._render_config_backup(flash)

    def _post_reset_defaults(self) -> Dict[str, Any]:
        """Reset configuration to defaults."""
        flash = {}

        try:
            # Create backup before resetting
            if os.path.exists(self.config_editor.config_file):
                from datetime import datetime
                import shutil
                # Ensure backup directory exists
                os.makedirs(self.config_editor.auto_backup_dir, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                backup_path = os.path.join(
                    self.config_editor.auto_backup_dir,
                    f"auto_backup_{timestamp}.json"
                )
                shutil.copy2(self.config_editor.config_file, backup_path)

            # Load default config from schema
            default_config = {}
            for field, schema in self.config_editor.config_schema.get("properties", {}).items():
                if "default" in schema:
                    default_config[field] = schema["default"]
                elif field == "zones":
                    default_config[field] = []
                elif field == "lighting_periods":
                    default_config[field] = []
                elif field == "plugin_config":
                    default_config[field] = {}

            # Save default config
            self.config_editor.save_config(default_config)

            flash["message"] = "Configuration reset to defaults successfully"
        except Exception as e:
            logger.exception(f"Error resetting to defaults: {e}")
            flash["error"] = f"Error resetting config: {str(e)}"

        # Re-render config backup page
        return self._render_config_backup(flash)

    def _post_upload_config(self, body_params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle config file upload."""
        flash = {}

        try:
            # Parse multipart form data
            # Note: This is a simplified implementation. For full multipart/form-data support,
            # you may need to use a library like python-multipart

            # For now, return error indicating this feature needs implementation
            flash["error"] = "Config upload not yet supported in IWS mode. Please use download/restore from backups."
        except Exception as e:
            logger.exception(f"Error uploading config: {e}")
            flash["error"] = f"Error uploading config: {str(e)}"

        # Re-render config backup page
        return self._render_config_backup(flash)

    def _error_response(self, status: int, message: str) -> Dict[str, Any]:
        """Generate an error response using indigo.Dict() format."""
        template = self.jinja_env.get_template('config_editor_error.html')
        html = template.render(message=message)
        return create_html_response(html, status=status)

    # Static files are now automatically served from Resources/static/ by IWS
    # No custom handler needed - IWS handles Resources/static/, Resources/images/, Resources/video/ automatically

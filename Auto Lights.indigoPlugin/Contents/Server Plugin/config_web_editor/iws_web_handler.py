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

logger = logging.getLogger(__name__)


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

        logger.debug("IWSWebHandler initialized")

    def _parse_form_data(self, body: str) -> MultiDict:
        """
        Parse URL-encoded form data from POST body into a MultiDict for WTForms.

        Args:
            body: URL-encoded form data string

        Returns:
            MultiDict suitable for WTForms processing
        """
        # Parse the form data
        parsed = parse_qs(body, keep_blank_values=True)

        # Convert to list of tuples for MultiDict
        items = []
        for key, values in parsed.items():
            for value in values:
                # Decode the value
                decoded_value = unquote_plus(value)
                items.append((key, decoded_value))

        return MultiDict(items)

    def _redirect(self, url: str, message: Optional[str] = None, error: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate a redirect response.

        Args:
            url: URL to redirect to
            message: Optional success message
            error: Optional error message

        Returns:
            Redirect response dict
        """
        # Add message/error to query string
        if message:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}message={message}"
        if error:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}error={error}"

        return {
            "status": 302,
            "headers": {"Location": url},
            "content": ""
        }

    def _url_for(self, endpoint: str, **kwargs) -> str:
        """
        Generate IWS-compatible URLs to replace Flask's url_for().

        Args:
            endpoint: The route endpoint (e.g., 'zones', 'plugin_config')
            **kwargs: Additional URL parameters

        Returns:
            IWS URL string
        """
        # Static files
        if endpoint == 'static':
            filename = kwargs.get('filename', '')
            return f"/message/{self.plugin_id}/static/?file={filename}"

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
        body: str,
        query_string: str = ""
    ) -> Dict[str, Any]:
        """
        Handle an HTTP request from IWS.

        Args:
            method: HTTP method (GET, POST, etc.)
            headers: Request headers dict
            body: Request body (for POST requests)
            query_string: URL query string

        Returns:
            Response dict with status, headers, and content
        """
        logger.debug(f"IWS Web Handler: {method} request received")
        logger.debug(f"Query string: {query_string}")

        try:
            # Parse query parameters
            params = parse_qs(query_string) if query_string else {}
            page = params.get('page', [''])[0]  # Get first value or empty string

            logger.debug(f"Requested page: {page or 'index'}")

            # Route to appropriate handler
            if method == "GET":
                return self._handle_get(page, params)
            elif method == "POST":
                return self._handle_post(page, body, params)
            else:
                return self._error_response(405, "Method Not Allowed")

        except Exception as e:
            logger.exception(f"Error handling IWS request: {e}")
            return self._error_response(500, f"Internal Server Error: {str(e)}")

    def _extract_flash_messages(self, params: Dict[str, list]) -> Dict[str, Optional[str]]:
        """
        Extract flash messages from query parameters.

        Args:
            params: Query string parameters

        Returns:
            Dict with 'message' and 'error' keys
        """
        message = params.get('message', [''])[0] if 'message' in params else None
        error = params.get('error', [''])[0] if 'error' in params else None
        return {"message": message, "error": error}

    def _handle_get(self, page: str, params: Dict[str, list]) -> Dict[str, Any]:
        """Handle GET requests."""
        # Extract flash messages
        flash = self._extract_flash_messages(params)

        # Route to appropriate page handler (pass flash messages)
        if not page or page == 'index':
            return self._render_index(flash)
        elif page == 'zones':
            return self._render_zones(flash)
        elif page.startswith('zone/'):
            zone_id = page.split('/')[-1]
            return self._render_zone_edit(zone_id, flash)
        elif page == 'plugin_config':
            return self._render_plugin_config(flash)
        elif page == 'lighting_periods':
            return self._render_lighting_periods(flash)
        elif page.startswith('lighting_period/'):
            period_id = page.split('/')[-1]
            return self._render_lighting_period_edit(period_id, flash)
        elif page == 'config_backup':
            return self._render_config_backup(flash)
        else:
            return self._error_response(404, f"Page not found: {page}")

    def _handle_post(self, page: str, body: str, params: Dict[str, list]) -> Dict[str, Any]:
        """Handle POST requests."""
        logger.debug(f"POST to page: {page}")
        logger.debug(f"Body length: {len(body)}")

        # Route to specific POST handler
        if not page or page == 'zones':
            return self._post_zones(body)
        elif page.startswith('zone/delete/'):
            zone_id = page.split('/')[-1]
            return self._post_zone_delete(zone_id)
        elif page.startswith('zone/'):
            zone_id = page.split('/')[-1]
            return self._post_zone_save(zone_id, body)
        elif page == 'plugin_config':
            return self._post_plugin_config(body)
        elif page == 'lighting_periods':
            return self._post_lighting_periods(body)
        elif page.startswith('lighting_period/'):
            period_id = page.split('/')[-1]
            return self._post_lighting_period_save(period_id, body)
        elif page == 'config_backup':
            return self._post_config_backup(body)
        elif page == 'create_new_variable':
            return self._post_create_variable(body)
        elif page == 'refresh_variables':
            return self._post_refresh_variables()
        else:
            return self._error_response(404, f"Unknown POST endpoint: {page}")

    def _post_zone_save(self, zone_id: str, body: str) -> Dict[str, Any]:
        """Handle zone save POST."""
        try:
            # Parse form data
            form_data = self._parse_form_data(body)

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

            # Save based on new or existing
            if zone_id == "new":
                zones_data.append(zone_data)
                config_data["zones"] = zones_data
                self.config_editor.save_config(config_data)
                return self._redirect(self._url_for("zones"), message="New zone created successfully")
            else:
                index = int(zone_id)
                zones_data[index] = zone_data
                config_data["zones"] = zones_data
                self.config_editor.save_config(config_data)
                return self._redirect(self._url_for("zone_config", zone_id=zone_id), message="Zone updated")

        except Exception as e:
            logger.exception(f"Error saving zone: {e}")
            return self._redirect(self._url_for("zones"), error=f"Error saving zone: {str(e)}")

    def _post_zone_delete(self, zone_id: str) -> Dict[str, Any]:
        """Handle zone delete."""
        try:
            config_data = self.config_editor.load_config()
            zones_data = config_data.get("zones", [])

            index = int(zone_id)
            if 0 <= index < len(zones_data):
                deleted_zone = zones_data.pop(index)
                config_data["zones"] = zones_data
                self.config_editor.save_config(config_data)
                return self._redirect(self._url_for("zones"), message=f"Zone '{deleted_zone.get('name', index)}' deleted")
            else:
                return self._redirect(self._url_for("zones"), error="Invalid zone index")

        except Exception as e:
            logger.exception(f"Error deleting zone: {e}")
            return self._redirect(self._url_for("zones"), error=f"Error deleting zone: {str(e)}")

    def _post_zones(self, body: str) -> Dict[str, Any]:
        """Handle zones list update (if needed)."""
        # This may not be used, but included for completeness
        return self._redirect(self._url_for("zones"))

    def _post_plugin_config(self, body: str) -> Dict[str, Any]:
        """Handle plugin config save."""
        try:
            form_data = self._parse_form_data(body)
            config_data = self.config_editor.load_config()
            plugin_schema = self.config_editor.config_schema["properties"]["plugin_config"]

            PluginFormClass = generate_form_class_from_schema(plugin_schema)
            plugin_form = PluginFormClass(formdata=form_data)

            plugin_config = {
                field_name: field.data
                for field_name, field in plugin_form._fields.items()
                if field_name != "submit"
            }

            config_data["plugin_config"] = plugin_config
            self.config_editor.save_config(config_data)
            return self._redirect(self._url_for("plugin_config"), message="Plugin configuration saved")

        except Exception as e:
            logger.exception(f"Error saving plugin config: {e}")
            return self._redirect(self._url_for("plugin_config"), error=f"Error saving: {str(e)}")

    def _post_lighting_periods(self, body: str) -> Dict[str, Any]:
        """Handle lighting periods save."""
        return self._redirect(self._url_for("lighting_periods"))

    def _post_lighting_period_save(self, period_id: str, body: str) -> Dict[str, Any]:
        """Handle lighting period save."""
        try:
            form_data = self._parse_form_data(body)
            config_data = self.config_editor.load_config()
            periods_data = config_data.get("lighting_periods", [])
            period_schema = self.config_editor.config_schema["properties"]["lighting_periods"]["items"]

            PeriodFormClass = generate_form_class_from_schema(period_schema)
            period_form = PeriodFormClass(formdata=form_data)

            period_data = {
                field_name: field.data
                for field_name, field in period_form._fields.items()
                if field_name != "submit"
            }

            if period_id == "new":
                # Generate new ID
                import uuid
                period_data["id"] = str(uuid.uuid4())
                periods_data.append(period_data)
                config_data["lighting_periods"] = periods_data
                self.config_editor.save_config(config_data)
                return self._redirect(self._url_for("lighting_periods"), message="New lighting period created")
            else:
                # Update existing
                for i, period in enumerate(periods_data):
                    if period.get("id") == period_id:
                        period_data["id"] = period_id  # Preserve ID
                        periods_data[i] = period_data
                        break
                config_data["lighting_periods"] = periods_data
                self.config_editor.save_config(config_data)
                return self._redirect(self._url_for("lighting_period_config", period_id=period_id), message="Lighting period updated")

        except Exception as e:
            logger.exception(f"Error saving lighting period: {e}")
            return self._redirect(self._url_for("lighting_periods"), error=f"Error saving: {str(e)}")

    def _post_config_backup(self, body: str) -> Dict[str, Any]:
        """Handle config backup operations."""
        # Parse form to determine action
        form_data = self._parse_form_data(body)
        action = form_data.get("action")

        try:
            if action == "create_manual_backup":
                self.config_editor.create_manual_backup()
                return self._redirect(self._url_for("config_backup"), message="Manual backup created")
            elif action == "restore":
                backup_type = form_data.get("backup_type")
                backup_file = form_data.get("backup_file")
                if self.config_editor.restore_backup(backup_type, backup_file):
                    return self._redirect(self._url_for("config_backup"), message="Configuration restored")
                else:
                    return self._redirect(self._url_for("config_backup"), error="Backup file not found")
            elif action == "delete":
                backup_type = form_data.get("backup_type")
                backup_file = form_data.get("backup_file")
                if self.config_editor.delete_backup(backup_type, backup_file):
                    return self._redirect(self._url_for("config_backup"), message="Backup deleted")
                else:
                    return self._redirect(self._url_for("config_backup"), error="Could not delete backup")
            else:
                return self._redirect(self._url_for("config_backup"), error="Unknown action")

        except Exception as e:
            logger.exception(f"Error in config backup operation: {e}")
            return self._redirect(self._url_for("config_backup"), error=f"Error: {str(e)}")

    def _post_create_variable(self, body: str) -> Dict[str, Any]:
        """Handle create new variable API endpoint."""
        try:
            from .tools.indigo_api_tools import indigo_create_new_variable
            data = json.loads(body)
            var_name = data.get("var_name")
            var_id = indigo_create_new_variable(var_name)
            return {
                "status": 200,
                "headers": {"Content-Type": "application/json"},
                "content": json.dumps({"var_id": var_id})
            }
        except Exception as e:
            logger.exception(f"Error creating variable: {e}")
            return {
                "status": 500,
                "headers": {"Content-Type": "application/json"},
                "content": json.dumps({"error": str(e)})
            }

    def _post_refresh_variables(self) -> Dict[str, Any]:
        """Handle refresh variables API endpoint."""
        try:
            variables = self.config_editor.get_cached_indigo_variables()
            return {
                "status": 200,
                "headers": {"Content-Type": "application/json"},
                "content": json.dumps(variables)
            }
        except Exception as e:
            logger.exception(f"Error refreshing variables: {e}")
            return {
                "status": 500,
                "headers": {"Content-Type": "application/json"},
                "content": json.dumps({"error": str(e)})
            }

    def _render_index(self, flash: Optional[Dict[str, Optional[str]]] = None) -> Dict[str, Any]:
        """Render the index/home page."""
        template = self.jinja_env.get_template('index.html')
        html = template.render(flash=flash or {})
        return {
            "status": 200,
            "headers": {"Content-Type": "text/html; charset=utf-8"},
            "content": html
        }

    def _render_zones(self, flash: Optional[Dict[str, Optional[str]]] = None) -> Dict[str, Any]:
        """Render the zones list page."""
        try:
            # Load config and schema
            config_data = self.config_editor.load_config()
            zones_data = config_data.get("zones", [])

            # Generate form class from schema
            zone_schema = self.config_editor.config_schema["properties"]["zones"]["items"]
            ZonesFormClass = generate_form_class_from_schema(zone_schema)

            # Create form for each zone
            zones_forms = [ZonesFormClass(data=zone) for zone in zones_data]

            # Render template
            template = self.jinja_env.get_template('zones.html')
            html = template.render(zones_forms=zones_forms, flash=flash or {})

            return {
                "status": 200,
                "headers": {"Content-Type": "text/html; charset=utf-8"},
                "content": html
            }
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

            # Update choices for device dropdowns with cached data
            try:
                devices = self.config_editor.get_cached_indigo_devices()
                device_choices = [(d["id"], d["name"]) for d in devices]

                # Update on_lights_dev_ids choices
                if hasattr(zone_form.device_settings, 'on_lights_dev_ids'):
                    zone_form.device_settings.on_lights_dev_ids.choices = device_choices

                # Update off_lights_dev_ids choices
                if hasattr(zone_form.device_settings, 'off_lights_dev_ids'):
                    zone_form.device_settings.off_lights_dev_ids.choices = device_choices

            except Exception as e:
                logger.warning(f"Could not update device choices: {e}")

            # Update variable dropdowns
            try:
                variables = self.config_editor.get_cached_indigo_variables()
                var_choices = [(-1, "None Selected")] + [(v["id"], v["name"]) for v in variables]

                # Update all _var_id fields
                for field_name, field in zone_form._fields.items():
                    if field_name.endswith("_var_id"):
                        field.choices = var_choices

            except Exception as e:
                logger.warning(f"Could not update variable choices: {e}")

            # Render template
            template = self.jinja_env.get_template('zone_edit.html')
            html = template.render(zone_form=zone_form, index=zone_id, flash=flash or {})

            return {
                "status": 200,
                "headers": {"Content-Type": "text/html; charset=utf-8"},
                "content": html
            }

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

            return {
                "status": 200,
                "headers": {"Content-Type": "text/html; charset=utf-8"},
                "content": html
            }
        except Exception as e:
            logger.exception(f"Error rendering plugin config page: {e}")
            return self._error_response(500, f"Error rendering plugin config: {str(e)}")

    def _render_lighting_periods(self, flash: Optional[Dict[str, Optional[str]]] = None) -> Dict[str, Any]:
        """Render the lighting periods list page."""
        try:
            config_data = self.config_editor.load_config()
            periods_data = config_data.get("lighting_periods", [])

            # Generate form class from schema
            period_schema = self.config_editor.config_schema["properties"]["lighting_periods"]["items"]
            PeriodFormClass = generate_form_class_from_schema(period_schema)

            # Create form for each period
            period_forms = [PeriodFormClass(data=period) for period in periods_data]

            template = self.jinja_env.get_template('lighting_periods.html')
            html = template.render(lighting_periods_forms=period_forms, flash=flash or {})

            return {
                "status": 200,
                "headers": {"Content-Type": "text/html; charset=utf-8"},
                "content": html
            }
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
                # Find existing period by ID
                period = next((p for p in periods_data if p.get("id") == period_id), None)
                if not period:
                    return self._error_response(404, f"Lighting period {period_id} not found")
                is_new = False

            # Generate form
            PeriodFormClass = generate_form_class_from_schema(period_schema)
            period_form = PeriodFormClass(data=period)

            template = self.jinja_env.get_template('lighting_period_edit.html')
            html = template.render(lighting_period_form=period_form, period_id=period_id, flash=flash or {})

            return {
                "status": 200,
                "headers": {"Content-Type": "text/html; charset=utf-8"},
                "content": html
            }
        except Exception as e:
            logger.exception(f"Error rendering lighting period edit page: {e}")
            return self._error_response(500, f"Error rendering lighting period edit: {str(e)}")

    def _render_config_backup(self, flash: Optional[Dict[str, Optional[str]]] = None) -> Dict[str, Any]:
        """Render the config backup page."""
        try:
            # Get backup lists from config editor
            manual_backups = self.config_editor.list_manual_backups()
            auto_backups = self.config_editor.list_auto_backups()

            # Extract just filenames for auto backups
            auto_backup_files = [os.path.basename(path) for path in auto_backups]

            template = self.jinja_env.get_template('config_backup.html')
            html = template.render(
                manual_backups=manual_backups,
                auto_backups=auto_backup_files,
                flash=flash or {}
            )

            return {
                "status": 200,
                "headers": {"Content-Type": "text/html; charset=utf-8"},
                "content": html
            }
        except Exception as e:
            logger.exception(f"Error rendering config backup page: {e}")
            return self._error_response(500, f"Error rendering config backup: {str(e)}")

    def _error_response(self, status: int, message: str) -> Dict[str, Any]:
        """Generate an error response."""
        template = self.jinja_env.get_template('config_editor_error.html')
        html = template.render(message=message)
        return {
            "status": status,
            "headers": {"Content-Type": "text/html; charset=utf-8"},
            "content": html
        }

    def serve_static_file(self, query_string: str) -> Dict[str, Any]:
        """
        Serve static files (CSS, images, etc.).

        Args:
            query_string: URL query string containing ?file=path/to/file

        Returns:
            Response dict with file contents
        """
        try:
            params = parse_qs(query_string) if query_string else {}
            filename = params.get('file', [''])[0]

            if not filename:
                return self._error_response(400, "No file specified")

            # Prevent directory traversal
            if '..' in filename or filename.startswith('/'):
                return self._error_response(403, "Forbidden")

            static_dir = os.path.join(os.path.dirname(__file__), 'static')
            file_path = os.path.join(static_dir, filename)

            if not os.path.exists(file_path):
                return self._error_response(404, f"File not found: {filename}")

            # Read file
            mode = 'rb' if not filename.endswith(('.css', '.js', '.html', '.md', '.MD')) else 'r'
            encoding = 'utf-8' if mode == 'r' else None

            with open(file_path, mode, encoding=encoding) as f:
                content = f.read()

            # Determine content type
            content_type, _ = mimetypes.guess_type(filename)
            if not content_type:
                content_type = 'application/octet-stream'

            return {
                "status": 200,
                "headers": {"Content-Type": content_type},
                "content": content
            }

        except Exception as e:
            logger.exception(f"Error serving static file: {e}")
            return self._error_response(500, f"Error serving file: {str(e)}")

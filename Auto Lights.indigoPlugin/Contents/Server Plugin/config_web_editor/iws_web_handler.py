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
from urllib.parse import parse_qs

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

    def _handle_get(self, page: str, params: Dict[str, list]) -> Dict[str, Any]:
        """Handle GET requests."""
        # Route to appropriate page handler
        if not page or page == 'index':
            return self._render_index()
        elif page == 'zones':
            return self._render_zones()
        elif page.startswith('zone/'):
            zone_id = page.split('/')[-1]
            return self._render_zone_edit(zone_id)
        elif page == 'plugin_config':
            return self._render_plugin_config()
        elif page == 'lighting_periods':
            return self._render_lighting_periods()
        elif page.startswith('lighting_period/'):
            period_id = page.split('/')[-1]
            return self._render_lighting_period_edit(period_id)
        elif page == 'config_backup':
            return self._render_config_backup()
        else:
            return self._error_response(404, f"Page not found: {page}")

    def _handle_post(self, page: str, body: str, params: Dict[str, list]) -> Dict[str, Any]:
        """Handle POST requests."""
        # TODO: Implement POST handlers for forms
        logger.debug(f"POST to page: {page}")
        logger.debug(f"Body length: {len(body)}")
        return self._error_response(501, "POST handling not yet implemented")

    def _render_index(self) -> Dict[str, Any]:
        """Render the index/home page."""
        template = self.jinja_env.get_template('index.html')
        html = template.render()
        return {
            "status": 200,
            "headers": {"Content-Type": "text/html; charset=utf-8"},
            "content": html
        }

    def _render_zones(self) -> Dict[str, Any]:
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
            html = template.render(zones_forms=zones_forms)

            return {
                "status": 200,
                "headers": {"Content-Type": "text/html; charset=utf-8"},
                "content": html
            }
        except Exception as e:
            logger.exception(f"Error rendering zones page: {e}")
            return self._error_response(500, f"Error rendering zones: {str(e)}")

    def _render_zone_edit(self, zone_id: str) -> Dict[str, Any]:
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
            html = template.render(zone_form=zone_form, index=zone_id)

            return {
                "status": 200,
                "headers": {"Content-Type": "text/html; charset=utf-8"},
                "content": html
            }

        except Exception as e:
            logger.exception(f"Error rendering zone edit page: {e}")
            return self._error_response(500, f"Error rendering zone edit: {str(e)}")

    def _render_plugin_config(self) -> Dict[str, Any]:
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
            html = template.render(plugin_form=plugin_form)

            return {
                "status": 200,
                "headers": {"Content-Type": "text/html; charset=utf-8"},
                "content": html
            }
        except Exception as e:
            logger.exception(f"Error rendering plugin config page: {e}")
            return self._error_response(500, f"Error rendering plugin config: {str(e)}")

    def _render_lighting_periods(self) -> Dict[str, Any]:
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
            html = template.render(lighting_periods_forms=period_forms)

            return {
                "status": 200,
                "headers": {"Content-Type": "text/html; charset=utf-8"},
                "content": html
            }
        except Exception as e:
            logger.exception(f"Error rendering lighting periods page: {e}")
            return self._error_response(500, f"Error rendering lighting periods: {str(e)}")

    def _render_lighting_period_edit(self, period_id: str) -> Dict[str, Any]:
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
            html = template.render(lighting_period_form=period_form, period_id=period_id)

            return {
                "status": 200,
                "headers": {"Content-Type": "text/html; charset=utf-8"},
                "content": html
            }
        except Exception as e:
            logger.exception(f"Error rendering lighting period edit page: {e}")
            return self._error_response(500, f"Error rendering lighting period edit: {str(e)}")

    def _render_config_backup(self) -> Dict[str, Any]:
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
                auto_backups=auto_backup_files
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

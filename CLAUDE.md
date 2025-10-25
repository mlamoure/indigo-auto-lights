# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Testing
- Run all tests: `source .venv/bin/activate && python -m pytest`
- Run specific test: `source .venv/bin/activate && python -m pytest tests/test_specific_name.py`
- Run tests with verbose output: `source .venv/bin/activate && python -m pytest -v`

### Code Formatting
- Format code: `source .venv/bin/activate && black .`

### Development Environment
- Activate virtual environment: `source .venv/bin/activate`
- Install dependencies: `pip install -r requirements.txt`

### Development Machine Testing

**Plugin Restart**:
```bash
python3 /Users/mike/Mike_Sync_Documents/Programming/mike-local-development-scripts/restart_indigo_plugin.py com.vtmikel.autolights
```

**Log Location**:
- Indigo logs: `/Library/Application Support/Perceptive Automation/Indigo 2025.1/Logs`
- Current day events: `/Library/Application Support/Perceptive Automation/Indigo 2025.1/Logs/YYYY-MM-DD Events.txt`
- View recent logs: `tail -100 "/Library/Application Support/Perceptive Automation/Indigo 2025.1/Logs/$(date +%Y-%m-%d) Events.txt" | grep "Auto Lights"`

**Web Configuration Access**:
- URL: `http://localhost:8176/message/com.vtmikel.autolights/web_ui/`
- Or from network: `http://<indigo-server-ip>:8176/message/com.vtmikel.autolights/web_ui/`

**Indigo Server Credentials** (Development Machine):
- Username: `indigo_server`
- Password: `indigo_server`
- Note: Insecure password acceptable for development machine only

## Architecture Overview

This is an Indigo Home Automation plugin for automatic lighting control written in Python. The plugin implements a zone-based lighting automation system with presence detection, luminance awareness, and time-based control.

### Core Components

**Plugin Structure (Indigo Plugin Bundle)**:
- `Auto Lights.indigoPlugin/` - The main plugin bundle
- `Contents/Server Plugin/plugin.py` - Main plugin entry point that interfaces with Indigo
- `Contents/Server Plugin/auto_lights/` - Core automation logic modules

**Key Modules**:
- `AutoLightsAgent` (auto_lights_agent.py) - Main automation engine that processes zones and handles device/variable changes
- `AutoLightsConfig` (auto_lights_config.py) - Configuration management with JSON schema validation
- `Zone` (zone.py) - Individual lighting zone logic with locking mechanisms and brightness plans
- `BrightnessPlan` (brightness_plan.py) - Luminance-based brightness calculation
- `LightingPeriod` (lighting_period.py) - Time-based lighting control periods

**Web Configuration Interface** (IWS-based):
- `config_web_editor/` - Web UI for zone configuration using Indigo Web Server (IWS)
- **Architecture**: Migrated from standalone Flask server to Indigo's integrated web server (IWS)
- **Routing**: Action-based routing via Actions.xml entries mapped to plugin handler methods
- **URL Structure**: `http://localhost:8176/message/<plugin_id>/web_ui/?page=<page_name>`
- **Data Access**: Direct `indigo.devices`, `indigo.variables` object access (no HTTP API needed)
- **Templating**: Jinja2 standalone with custom `url_for()` helper function
- **Forms**: WTForms without Flask (using `Form` base class, no CSRF)
- **Form Processing**: Werkzeug's MultiDict for POST data handling
- **Configuration**: Stored as JSON with schema validation

**IWS Key Components**:
- `iws_web_handler.py` - IWS request handler (replaces Flask routing)
- `iws_form_helpers.py` - WTForms utilities for IWS (dynamic form generation from JSON schema)
- `indigo_api_tools.py` - Direct indigo object access utilities (replaces HTTP API calls)
- `Actions.xml` - Defines IWS action endpoints (`web_ui`, `static`)
- Legacy Flask code preserved (commented out) for rollback capability

### Key Concepts

**Zones**: Logical groupings of lights with shared automation rules, presence sensors, and luminance sensors.

**Zone Locking**: Temporary override mechanism that prevents automation when users manually control lights. Locks expire after configurable timeouts or can be reset.

**Presence-Based Control**: Uses motion sensors or virtual presence devices to determine zone occupancy before turning on lights.

**Luminance Awareness**: Optional brightness adjustment based on ambient light levels using luminance sensors.

**Configuration Schema**: JSON-based configuration with schema validation for both global settings and individual zones.

### Testing

Tests use pytest with a custom `conftest.py` that stubs the Indigo module since tests run outside the Indigo environment. The test suite covers zone logic, locking mechanisms, and configuration validation.

### Plugin Integration

The plugin integrates with Indigo through:
- Device state monitoring (deviceUpdated callback)
- Variable change monitoring (variableUpdated callback)
- Custom plugin devices for zones and global configuration
- Actions for manual zone lock resets
- Menu items for debugging locked zones
- IWS action handlers for web UI requests (handle_web_ui, serve_static_file)

## IWS Migration Details

### Migration Overview

The plugin was migrated from a standalone Flask web server to Indigo's integrated Web Server (IWS). This migration provides several benefits:

- **No Separate Server**: Web UI runs through Indigo's built-in web server (port 8176)
- **Direct Object Access**: Uses `indigo.devices` and `indigo.variables` instead of HTTP API calls
- **No API Keys**: Eliminated need for API URL and API key configuration
- **Simplified Deployment**: No network configuration required (bind IP, port)
- **Integrated Experience**: Web UI accessible through standard Indigo web server

### Key Architecture Changes

**Request Handling**:
- **Before**: Flask routes (`@app.route('/zones')`)
- **After**: IWS action handlers in Actions.xml mapped to plugin methods

**URL Structure**:
- **Before**: `http://localhost:9000/zones`
- **After**: `http://localhost:8176/message/com.vtmikel.autolights/web_ui/?page=zones`

**Data Access**:
- **Before**: HTTP API calls with requests library
- **After**: Direct iteration over `indigo.devices`, `indigo.variables`

**Form Processing**:
- **Before**: Flask-WTF with CSRF protection
- **After**: WTForms base `Form` class with Werkzeug MultiDict

**Templating**:
- **Before**: Flask's integrated Jinja2
- **After**: Standalone Jinja2 Environment with custom `url_for()` function

### Accessing the Web UI

The web configuration interface is available at:
```
http://localhost:8176/message/com.vtmikel.autolights/web_ui/
```

Or from any machine on your network (replace localhost with Indigo server address):
```
http://<indigo-server-ip>:8176/message/com.vtmikel.autolights/web_ui/
```

### Rollback Instructions

All Flask-related code has been preserved (commented out) for rollback capability. To revert to Flask:

1. Uncomment Flask imports in `plugin.py:15-16`
2. Uncomment `start_configuration_web_server()` call in `plugin.py:84-85`
3. Uncomment Flask server code in `start_configuration_web_server()` method
4. Uncomment API environment variables in `closedPrefsConfigUi()` method
5. Uncomment web server restart logic in `closedPrefsConfigUi()` method
6. Restore PluginConfig.xml fields (API URL, API key, web server settings)
7. Update requirements.txt to include Flask dependencies

### Dependencies

**Current (IWS mode)**:
- WTForms~=3.2.1 - Form generation and validation
- Jinja2~=3.1.6 - Template rendering
- Werkzeug~=3.1.3 - MultiDict for WTForms
- MarkupSafe~=3.0.2 - Jinja2 dependency
- python-dotenv~=1.1.1 - Environment configuration
- pytest~=8.4.1 - Testing

**Removed (Flask mode)**:
- Flask, Flask-WTF, requests, click, blinker, itsdangerous, certifi, urllib3, idna, charset-normalizer

## Indigo Web Server (IWS) Integration Reference

This section provides comprehensive documentation on how this plugin integrates with Indigo's Web Server (IWS), based on the official Indigo SDK 2024.2 examples.

### IWS Architecture Overview

Indigo Web Server (IWS) is a built-in HTTP server that runs on port 8176 (by default) and allows plugins to expose web interfaces without running separate web servers.

**Key Benefits**:
- No separate server process required
- No port configuration needed
- Integrated authentication via Indigo credentials
- Automatic SSL/TLS when using Indigo Reflector
- Simplified deployment

**Request Flow**:
1. Browser makes HTTP request to `http://localhost:8176/message/<plugin_id>/<action_id>/`
2. IWS identifies the plugin and action from the URL
3. IWS calls the plugin's action callback method with request details
4. Plugin processes request and returns response dict
5. IWS sends HTTP response to browser

### Automatic Static File Serving

IWS automatically serves files from specific directories in the plugin bundle without any custom code:

**Auto-Served Directories** (in `Contents/Resources/`):
- `Resources/static/` → Served at `/{plugin_id}/static/{filename}`
- `Resources/images/` → Served at `/{plugin_id}/images/{filename}`
- `Resources/video/` → Served at `/{plugin_id}/video/{filename}`
- `Resources/public/` → Served at `/{plugin_id}/public/{filename}` (no authentication required)

**Authentication**:
- Most directories require Indigo authentication (HTTP auth or API key)
- `Resources/public/` is accessible without authentication

**Example URLs**:
```
http://localhost:8176/com.vtmikel.autolights/static/css/main.css
http://localhost:8176/com.vtmikel.autolights/static/images/icon.png
http://localhost:8176/com.vtmikel.autolights/static/Documentation.MD
```

**Important**: After adding these directories to a deployed plugin, you must restart IWS:
```bash
indigo-restart-plugin com.indigodomo.webserver
```

### Actions.xml Configuration

IWS actions are defined in `Actions.xml` with `uiPath="hidden"` to prevent them from appearing in Indigo's UI.

**Web UI Action** (`Contents/Server Plugin/Actions.xml`):
```xml
<Action id="web_ui" uiPath="hidden">
    <Name>Web UI Handler</Name>
    <CallbackMethod>handle_web_ui</CallbackMethod>
</Action>
```

**URL Pattern**: `/message/{plugin_id}/web_ui/?page={page_name}`

**No Static File Action Needed**: Previously had a `static` action, but removed because IWS serves `Resources/static/` automatically.

### Action Callback Signature

**Method Signature**:
```python
def handle_web_ui(self, action, dev=None, callerWaitingForResult=True):
    """
    Args:
        action: indigo.Action object with request details in action.props
        dev: Optional device reference (usually None for web actions)
        callerWaitingForResult: Always True for HTTP requests

    Returns:
        Dict with status, headers, and content
    """
```

**Request Data** (in `action.props`):
- `incoming_request_method`: HTTP method ("GET", "POST", etc.)
- `headers`: Dict of HTTP headers
- `request_body`: POST body (URL-encoded string)
- `query_string`: URL query string (e.g., "page=zones&id=5")
- `file_path`: List of URL path components
- `url_query_args`: Dict of parsed query string parameters

**Response Dict**:
```python
{
    "status": 200,                          # HTTP status code
    "headers": {                            # Optional HTTP headers
        "Content-Type": "text/html; charset=utf-8",
        "Location": "/redirect/path"        # For 302 redirects
    },
    "content": "<html>...</html>"          # Response body (string or bytes)
}
```

### Template Integration

**Template Location**: `Contents/Server Plugin/config_web_editor/templates/`

**Jinja2 Setup** (in `iws_web_handler.py`):
```python
from jinja2 import Environment, FileSystemLoader, select_autoescape

template_dir = os.path.join(os.path.dirname(__file__), 'templates')
self.jinja_env = Environment(
    loader=FileSystemLoader(template_dir),
    autoescape=select_autoescape(['html', 'xml']),
)
```

**Template Globals** (available in all templates):
```python
# Custom url_for function for generating IWS URLs
self.jinja_env.globals['url_for'] = self._url_for

# Plugin object for accessing plugin ID in templates
class PluginRef:
    def __init__(self, plugin_id):
        self.pluginId = plugin_id

self.jinja_env.globals['plugin'] = PluginRef(plugin_id)

# Standard Python functions
self.jinja_env.globals['enumerate'] = enumerate
self.jinja_env.globals['os'] = os
```

**Template Usage**:
```html
<!-- Static files -->
<link rel="stylesheet" href="{{ url_for('static', filename='css/main.css') }}">
<!-- Generates: /com.vtmikel.autolights/static/css/main.css -->

<!-- Page links -->
<a href="{{ url_for('zones') }}">Zones</a>
<!-- Generates: /message/com.vtmikel.autolights/web_ui/?page=zones -->

<!-- Page with parameters -->
<a href="{{ url_for('zone_config', zone_id=5) }}">Edit Zone</a>
<!-- Generates: /message/com.vtmikel.autolights/web_ui/?page=zone/5 -->
```

### Custom url_for() Implementation

The `_url_for()` method generates IWS-compatible URLs:

**Static Files**:
```python
if endpoint == 'static':
    filename = kwargs.get('filename', '')
    return f"/{self.plugin_id}/static/{filename}"
```

**Regular Pages**:
```python
page_map = {
    'index': '',
    'zones': 'zones',
    'zone_config': f"zone/{kwargs.get('zone_id', '')}",
    'plugin_config': 'plugin_config',
    # ...
}
page = page_map.get(endpoint, endpoint)
return f"/message/{self.plugin_id}/web_ui/?page={page}"
```

### Form Processing

**WTForms Without Flask**:
```python
from wtforms import Form  # NOT FlaskForm
from werkzeug.datastructures import MultiDict

# Parse POST body to MultiDict
form_data = self._parse_form_data(body)

# Create form with formdata parameter
form = MyFormClass(formdata=form_data)

# Extract validated data
data = {field_name: field.data for field_name, field in form._fields.items()}
```

**Parsing POST Body**:
```python
def _parse_form_data(self, body: str) -> MultiDict:
    """Parse URL-encoded form data to MultiDict"""
    from urllib.parse import parse_qs, unquote_plus

    parsed = parse_qs(body, keep_blank_values=True)
    items = []
    for key, values in parsed.items():
        for value in values:
            decoded_value = unquote_plus(value)
            items.append((key, decoded_value))

    return MultiDict(items)
```

**Note**: Multipart/form-data (file uploads) requires additional parsing library (not currently implemented).

### Page Routing Pattern

**GET Request Routing**:
```python
def _handle_get(self, page: str, params: Dict[str, list]):
    if not page or page == 'index':
        return self._render_index()
    elif page == 'zones':
        return self._render_zones()
    elif page.startswith('zone/'):
        zone_id = page.split('/')[-1]
        return self._render_zone_edit(zone_id)
    # ... more routes
```

**POST Request Routing**:
```python
def _handle_post(self, page: str, body: str, params: Dict[str, list]):
    if page.startswith('zone/'):
        zone_id = page.split('/')[-1]
        return self._post_zone_save(zone_id, body)
    # ... more routes
```

### Flash Messages

Since Flask's flash() isn't available, use query string parameters for success/error messages:

**Redirect with Message**:
```python
def _redirect(self, url: str, message: Optional[str] = None, error: Optional[str] = None):
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
```

**Extract in GET Handler**:
```python
def _extract_flash_messages(self, params: Dict[str, list]):
    message = params.get('message', [''])[0] if 'message' in params else None
    error = params.get('error', [''])[0] if 'error' in params else None
    return {"message": message, "error": error}
```

**Template Display**:
```html
{% if flash.message %}
    <div class="success">{{ flash.message }}</div>
{% endif %}
{% if flash.error %}
    <div class="error">{{ flash.error }}</div>
{% endif %}
```

### Direct Indigo Object Access

**No HTTP API Required**: Plugin runs in same process as Indigo, so can directly access:

```python
# Devices
for dev in indigo.devices:
    device_data = {
        "id": dev.id,
        "name": dev.name,
        "enabled": dev.enabled,
        "states": dict(dev.states)
    }

# Variables
for var in indigo.variables:
    var_data = {
        "id": var.id,
        "name": var.name,
        "value": var.value
    }

# Create variable
new_var = indigo.variable.create("My Variable", value="initial")
```

**Caching**: Web handler caches device/variable lists for performance:
```python
self.config_editor.get_cached_indigo_devices()
self.config_editor.get_cached_indigo_variables()
```

### Lazy Initialization Pattern

To avoid `__file__` issues during plugin startup, IWS handler is initialized on first request:

```python
def handle_web_ui(self, action, dev=None, callerWaitingForResult=True):
    # Lazy initialization - create handler on first request
    if not self._iws_web_handler:
        self.logger.debug("Lazy initializing IWS web handler on first request")
        self._init_iws_web_handler()

    # If initialization failed, return error
    if not self._iws_web_handler:
        self.logger.error("IWS web handler failed to initialize")
        return {
            "status": 503,
            "headers": {"Content-Type": "text/html; charset=utf-8"},
            "content": "<html><body><h1>Service Unavailable</h1></body></html>"
        }

    # Extract request details and delegate
    method = action.props.get("incoming_request_method", "GET").upper()
    headers = dict(action.props.get("headers", {}))
    body = action.props.get("request_body", "")
    query_string = action.props.get("query_string", "")

    return self._iws_web_handler.handle_request(method, headers, body, query_string)
```

### Complete IWS Request Example

**User navigates to**: `http://localhost:8176/message/com.vtmikel.autolights/web_ui/?page=zones`

**IWS calls**: `plugin.handle_web_ui(action, ...)`

**Plugin processes**:
1. Extracts method ("GET"), query_string ("page=zones")
2. Parses page parameter → "zones"
3. Routes to `_handle_get("zones", params)`
4. Calls `_render_zones()` which:
   - Loads config data
   - Generates WTForms for each zone
   - Renders `zones.html` template
   - Returns HTML response dict

**IWS returns**: HTML page to browser

**Browser requests static files**:
- `/{plugin_id}/static/css/main.css`
- `/{plugin_id}/static/images/icon.png`
- IWS serves these directly from `Resources/static/` (no plugin code involved)

### Debugging Tips

**Enable Debug Logging** (in plugin.py):
```python
self.logger.debug(f"IWS Web UI: {method} {query_string}")
self.logger.debug(f"Request body length: {len(body)}")
self.logger.debug(f"Rendering page: {page}")
```

**Check Indigo Event Log**: Window → Event Log shows all plugin log messages

**Verify Static Files**: Check that `Resources/static/` exists and contains files:
```bash
ls -la "Contents/Resources/static/"
```

**Restart IWS After Changes**:
```bash
indigo-restart-plugin com.indigodomo.webserver
```

**Browser Console**: Check for 404 errors on static files

### Migration from Flask Checklist

When migrating a Flask-based web interface to IWS:

- [ ] Move templates to `Contents/Server Plugin/config_web_editor/templates/`
- [ ] Move static files to `Contents/Resources/static/`
- [ ] Create Actions.xml entry for web UI handler
- [ ] Implement action callback method in plugin.py
- [ ] Create IWS web handler class with Jinja2 environment
- [ ] Implement custom `url_for()` function
- [ ] Replace Flask routes with page routing in `_handle_get()` and `_handle_post()`
- [ ] Replace `flask.request` with action.props parsing
- [ ] Replace `flask.redirect()` with redirect response dict
- [ ] Replace `flask.flash()` with query string message parameters
- [ ] Replace Flask-WTF with base WTForms + MultiDict
- [ ] Replace HTTP API calls with direct indigo object access
- [ ] Test all pages and forms
- [ ] Restart IWS to activate static file serving
- [ ] Update documentation

### Critical IWS Learnings (Debugging Notes)

This section documents important discoveries made during IWS migration debugging that are critical for successful implementation.

#### 1. Query Parameters: Use `url_query_args` NOT `query_string`

**Problem**: Initially used `action.props.get("query_string")` which returned empty string, breaking all page routing.

**Root Cause**: IWS provides query parameters in **two different fields**:
- `query_string` - Raw query string (e.g., `"page=zones&message=success"`)
- `url_query_args` - **Pre-parsed dictionary** (e.g., `{"page": "zones", "message": "success"}`)

**Solution**: Always use the pre-parsed `url_query_args` dictionary:

```python
# ❌ WRONG - query_string is often empty
query_string = action.props.get("query_string") or ""
params = parse_qs(query_string)
page = params.get('page', [''])[0]

# ✅ CORRECT - url_query_args is pre-parsed by IWS
url_query_args = dict(action.props.get("url_query_args", {}))
page = url_query_args.get('page', '')
```

**Why query_string is empty**: IWS parses query parameters into `url_query_args` and may not always populate the raw `query_string` field. The Indigo SDK Example HTTP Responder uses `url_query_args` exclusively.

**Type Difference**:
- `parse_qs()` returns `Dict[str, List[str]]` - values are lists
- `url_query_args` returns `Dict[str, str]` - values are strings (IWS already extracted first value)

**Impact**: This discovery fixed the "all pages show Documentation" bug where navigation links didn't work.

#### 2. Array Fields in WTForms Must Be Handled Explicitly

**Problem**: Zones page crashed with `TypeError: argument of type 'bool' is not iterable`

**Root Cause**: The `create_field()` function in `iws_form_helpers.py` didn't handle `type: "array"` fields properly:

- Array fields like `lighting_period_ids` (`type: "array"`, `x-drop-down: true`)
- Didn't match special cases for `_var_id` or `_dev_ids`
- Fell through to default StringField instead of SelectMultipleField
- When WTForms tried to populate StringField with array/boolean data → crash

**Solution**: Add explicit array field handling in `create_field()`:

```python
# Array fields with dropdown (e.g., lighting_period_ids)
elif field_type == "array" and field_schema.get("x-drop-down"):
    choices = []
    # Determine coerce type from items schema
    items_type = field_schema.get("items", {}).get("type", "string")
    coerce_func = int if items_type == "integer" else str
    f = SelectMultipleField(label=label_text, description=tooltip_text,
                           choices=choices, coerce=coerce_func, validators=validators)
```

**Array Fields in Zone Schema**:
- `lighting_period_ids` - Array of integer IDs
- `on_lights_dev_ids` - Array of device IDs
- `off_lights_dev_ids` - Array of device IDs

**Best Practice**: Always check `field_type == "array"` before falling back to StringField.

#### 3. Data Validation: Coerce Array Fields to Lists

**Problem**: Zone data sometimes contained boolean values (`true`/`false`) in array fields, causing iteration errors.

**Root Cause**: JSON schema defaults or manual edits could set array fields to `true` instead of `[]`.

**Solution**: Validate and coerce array fields before creating forms:

```python
# Validate array fields before form creation
array_fields = ['lighting_period_ids']
for field in array_fields:
    if field in zone:
        value = zone[field]
        if not isinstance(value, list):
            logger.warning(f"Zone {idx} {field} is {type(value).__name__}, coercing to empty list")
            zone[field] = []
```

**Why This Matters**: WTForms SelectMultipleField expects list data. If it receives a boolean, the field's internal processing tries to iterate over it, causing `TypeError: argument of type 'bool' is not iterable`.

**Best Practice**: Always validate array field types before passing data to WTForms, especially when loading from JSON configuration files.

#### 4. Debug Logging Strategy for IWS

**Effective Debug Points**:

1. **Plugin action callback** (`plugin.py`):
   ```python
   self.logger.debug(f"URL query args from action.props: {url_query_args}")
   ```

2. **IWS handler entry point** (`iws_web_handler.py`):
   ```python
   logger.debug(f"URL query params: {params}")
   logger.debug(f"Extracted page parameter: '{page}'")
   ```

3. **Routing decisions**:
   ```python
   logger.debug(f"Routing to: _render_zones")
   ```

4. **Form creation** (especially for debugging array field issues):
   ```python
   for idx, zone in enumerate(zones_data):
       logger.debug(f"Processing zone {idx}: {zone.get('name', 'unnamed')}")
       try:
           zone_form = ZonesFormClass(data=zone)
           logger.debug(f"Successfully created form for zone {idx}")
       except Exception as e:
           logger.exception(f"Error creating form for zone {idx}: {e}")
           raise
   ```

**Check Logs**: Window → Event Log in Indigo shows all plugin debug messages

#### 5. Common Pitfalls

**Pitfall #1**: Assuming `query_string` works like Flask's `request.query_string`
- **Fix**: Use `url_query_args` instead

**Pitfall #2**: Not handling all JSON schema field types in form generation
- **Fix**: Add explicit cases for `type: "array"`, `type: "object"`, etc.

**Pitfall #3**: Trusting JSON data types without validation
- **Fix**: Validate and coerce array fields to lists before form creation

**Pitfall #4**: Using `Dict[str, List[str]]` type hints for IWS params
- **Fix**: IWS provides `Dict[str, str]` (values already extracted), not lists

**Pitfall #5**: Forgetting to restart IWS after adding static file directories
- **Fix**: Always restart IWS after changing `Resources/` structure

#### 6. Comparison: Flask vs IWS Query Parameters

| Aspect | Flask | IWS |
|--------|-------|-----|
| Query string access | `request.args` | `action.props["url_query_args"]` |
| Type | `MultiDict` | `indigo.Dict` (behaves like `dict`) |
| Value format | Single value as string | Single value as string |
| Multiple values | `getlist('key')` returns list | First value only (no multiple values) |
| Parsing | Automatic | Automatic |
| Empty params | Returns `None` | Returns empty dict `{}` |

**Key Takeaway**: IWS simplifies query parameter handling by pre-parsing and extracting single values automatically.
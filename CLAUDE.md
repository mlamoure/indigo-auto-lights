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
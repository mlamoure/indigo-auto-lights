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

**Web Configuration Interface**:
- `config_web_editor/` - Flask-based web UI for zone configuration
- Runs as embedded web server within the plugin
- Uses Indigo API for device/variable access
- Configuration stored as JSON with schema validation

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
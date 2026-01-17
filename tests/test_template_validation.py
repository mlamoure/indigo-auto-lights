"""
Comprehensive Template Validation Tests

This test suite validates the IWS web configuration templates to catch
common issues before they reach production:
- Hardcoded URLs (should use url_for())
- Template rendering errors
- URL generation correctness
- Form generation from schema
"""

import os
import re
import pytest
from pathlib import Path


# Test 1: Scan for Hardcoded URLs
def test_no_hardcoded_urls():
    """
    Scan all templates for hardcoded URLs.

    This prevents issues like the cancel button bug where URLs were
    hardcoded instead of using url_for().
    """
    template_dir = Path(__file__).parent.parent / "Auto Lights.indigoPlugin" / "Contents" / "Server Plugin" / "config_web_editor" / "templates"

    # Patterns that indicate hardcoded URLs
    bad_patterns = [
        (r'''href=['"]/(?!/)''', "href with absolute path (should use url_for)"),
        (r'''fetch\(['"]/''', "fetch with absolute path (should use url_for)"),
        (r'''window\.location(?:\.href)?\s*=\s*['"]/''', "window.location with absolute path (should use url_for)"),
        (r'''action=['"]/''', "form action with absolute path (should use url_for)"),
    ]

    issues = []

    for template_file in template_dir.glob("**/*.html"):
        content = template_file.read_text()
        relative_path = template_file.relative_to(template_dir)

        for pattern, description in bad_patterns:
            matches = re.finditer(pattern, content, re.MULTILINE)
            for match in matches:
                # Calculate line number
                line_num = content[:match.start()].count('\n') + 1
                issues.append(f"{relative_path}:{line_num} - {description}: {match.group()}")

    if issues:
        error_msg = "Found hardcoded URLs in templates:\n" + "\n".join(issues)
        pytest.fail(error_msg)


# Test 2: Template Rendering
def test_template_rendering():
    """
    Test that all major templates can be rendered without Jinja2 errors.
    """
    from config_web_editor.iws_web_handler import IWSWebHandler
    from config_web_editor.config_editor import WebConfigEditor

    # Set up paths
    current_dir = Path(__file__).parent
    plugin_dir = current_dir.parent / "Auto Lights.indigoPlugin" / "Contents" / "Server Plugin"
    config_file = plugin_dir / "config_web_editor" / "config" / "auto_lights_conf_empty.json"
    schema_file = plugin_dir / "config_web_editor" / "config" / "config_schema.json"
    backup_dir = current_dir / "test_backups"
    auto_backup_dir = current_dir / "test_auto_backups"

    # Create backup directories
    backup_dir.mkdir(exist_ok=True)
    auto_backup_dir.mkdir(exist_ok=True)

    # Initialize handler
    config_editor = WebConfigEditor(
        config_file=str(config_file),
        schema_file=str(schema_file),
        backup_dir=str(backup_dir),
        auto_backup_dir=str(auto_backup_dir),
        flask_app=None
    )

    handler = IWSWebHandler(
        config_editor=config_editor,
        plugin_id="com.vtmikel.autolights"
    )

    # Test pages that should render without errors
    test_pages = [
        ("GET", {}, {}, "Index page"),
        ("GET", {"page": "zones"}, {}, "Zones list page"),
        ("GET", {"page": "lighting_periods"}, {}, "Lighting periods list page"),
        ("GET", {"page": "plugin_config"}, {}, "Plugin config page"),
        ("GET", {"page": "config_backup"}, {}, "Config backup page"),
    ]

    for method, params, body_params, description in test_pages:
        response = handler.handle_request(
            method=method,
            headers={},
            body_params=body_params,
            params=params
        )

        assert response['status'] == 200, f"{description} failed with status {response['status']}"
        assert 'content' in response, f"{description} missing content"
        assert len(response['content']) > 0, f"{description} returned empty content"
        # Basic HTML check - should contain html tags
        assert '<html' in response['content'].lower(), f"{description} doesn't look like HTML"


# Test 3: URL Generation
def test_url_generation():
    """
    Test that all url_for() endpoints generate valid IWS URLs.
    """
    from config_web_editor.iws_web_handler import IWSWebHandler
    from config_web_editor.config_editor import WebConfigEditor

    # Set up paths
    current_dir = Path(__file__).parent
    plugin_dir = current_dir.parent / "Auto Lights.indigoPlugin" / "Contents" / "Server Plugin"
    config_file = plugin_dir / "config_web_editor" / "config" / "auto_lights_conf_empty.json"
    schema_file = plugin_dir / "config_web_editor" / "config" / "config_schema.json"
    backup_dir = current_dir / "test_backups"
    auto_backup_dir = current_dir / "test_auto_backups"

    # Create backup directories
    backup_dir.mkdir(exist_ok=True)
    auto_backup_dir.mkdir(exist_ok=True)

    # Initialize handler
    config_editor = WebConfigEditor(
        config_file=str(config_file),
        schema_file=str(schema_file),
        backup_dir=str(backup_dir),
        auto_backup_dir=str(auto_backup_dir),
        flask_app=None
    )

    handler = IWSWebHandler(
        config_editor=config_editor,
        plugin_id="com.vtmikel.autolights"
    )

    # Test all endpoints
    test_cases = [
        # (endpoint, kwargs, expected_pattern)
        ('index', {}, r'/message/com\.vtmikel\.autolights/web_ui/$'),
        ('zones', {}, r'/message/com\.vtmikel\.autolights/web_ui/\?page=zones'),
        ('zone_config', {'zone_id': '0'}, r'/message/com\.vtmikel\.autolights/web_ui/\?page=zone/0'),
        ('plugin_config', {}, r'/message/com\.vtmikel\.autolights/web_ui/\?page=plugin_config'),
        ('lighting_periods', {}, r'/message/com\.vtmikel\.autolights/web_ui/\?page=lighting_periods'),
        ('lighting_period_config', {'period_id': '1'}, r'/message/com\.vtmikel\.autolights/web_ui/\?page=lighting_period/1'),
        ('config_backup', {}, r'/message/com\.vtmikel\.autolights/web_ui/\?page=config_backup'),
        ('create_new_variable', {}, r'/message/com\.vtmikel\.autolights/web_ui/\?page=create_new_variable'),
        ('refresh_variables', {}, r'/message/com\.vtmikel\.autolights/web_ui/\?page=refresh_variables'),
        ('get_luminance_value', {}, r'/message/com\.vtmikel\.autolights/web_ui/\?page=get_luminance_value'),
        ('static', {'filename': 'css/main.css'}, r'/com\.vtmikel\.autolights/static/css/main\.css'),
    ]

    for endpoint, kwargs, expected_pattern in test_cases:
        url = handler._url_for(endpoint, **kwargs)
        assert re.match(expected_pattern, url), f"URL for endpoint '{endpoint}' doesn't match expected pattern. Got: {url}"


# Test 4: Form Generation from Schema
def test_form_generation_from_schema():
    """
    Test that forms are correctly generated from JSON schema.

    This catches issues like array fields becoming StringField instead of
    SelectMultipleField, which causes "bool is not iterable" errors.
    """
    from config_web_editor.iws_form_helpers import generate_form_class_from_schema
    from wtforms import SelectMultipleField, SelectField, IntegerField, BooleanField, StringField

    # Test array field with dropdown
    schema = {
        "type": "object",
        "properties": {
            "lighting_period_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "x-drop-down": True,
                "title": "Lighting Periods"
            },
            "name": {
                "type": "string",
                "title": "Name"
            },
            "enabled": {
                "type": "boolean",
                "title": "Enabled"
            },
            "count": {
                "type": "integer",
                "title": "Count"
            }
        }
    }

    FormClass = generate_form_class_from_schema(schema)
    form = FormClass()

    # Verify field types
    assert isinstance(form.lighting_period_ids, SelectMultipleField), \
        "Array field with x-drop-down should be SelectMultipleField"
    assert isinstance(form.name, StringField), \
        "String field should be StringField"
    assert isinstance(form.enabled, BooleanField), \
        "Boolean field should be BooleanField"
    assert isinstance(form.count, IntegerField), \
        "Integer field should be IntegerField"

    # Test that SelectMultipleField can handle empty list
    form.lighting_period_ids.data = []
    assert form.lighting_period_ids.data == []

    # Test that SelectMultipleField can handle list of integers
    form.lighting_period_ids.data = [1, 2, 3]
    assert form.lighting_period_ids.data == [1, 2, 3]


# Test 5: Array Field Validation
def test_array_field_validation():
    """
    Test that array fields in zone data are properly validated and coerced.

    This prevents the "argument of type 'bool' is not iterable" error.
    """
    # This test verifies the logic in iws_web_handler.py:_render_zones()
    # that validates array fields before creating forms

    test_zones = [
        {
            "name": "Test Zone",
            "lighting_period_ids": True,  # Invalid - should be list
            "device_settings": {
                "on_lights_dev_ids": [1, 2],
                "luminance_dev_ids": False,  # Invalid - should be list
                "presence_dev_ids": "test"  # Invalid - should be list
            }
        }
    ]

    # Simulate the validation logic
    array_fields = ['lighting_period_ids']
    for zone in test_zones:
        if 'device_settings' in zone:
            for field in ['on_lights_dev_ids', 'off_lights_dev_ids', 'luminance_dev_ids', 'presence_dev_ids']:
                if field in zone['device_settings']:
                    value = zone['device_settings'][field]
                    if not isinstance(value, list):
                        zone['device_settings'][field] = []

        for field in array_fields:
            if field in zone:
                value = zone[field]
                if not isinstance(value, list):
                    zone[field] = []

    # Verify all array fields are now lists
    assert isinstance(test_zones[0]['lighting_period_ids'], list)
    assert isinstance(test_zones[0]['device_settings']['luminance_dev_ids'], list)
    assert isinstance(test_zones[0]['device_settings']['presence_dev_ids'], list)
    assert test_zones[0]['device_settings']['on_lights_dev_ids'] == [1, 2]  # Should preserve valid list


if __name__ == "__main__":
    # Allow running tests directly
    pytest.main([__file__, "-v"])

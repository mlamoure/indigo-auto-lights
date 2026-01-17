"""
Test script for IWS Web Handler

This script tests the IWSWebHandler independently to verify it works correctly
before deploying to Indigo.
"""

import sys
import os
from urllib.parse import parse_qs, unquote_plus

# Add parent directory to path to import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'Auto Lights.indigoPlugin', 'Contents', 'Server Plugin'))


def parse_form_body_to_dict(body: str) -> dict:
    """
    Parse URL-encoded form body to dict (simulates what IWS does).

    Args:
        body: URL-encoded form data string

    Returns:
        Dict with form data (lists for multi-value fields)
    """
    parsed = parse_qs(body, keep_blank_values=True)
    result = {}
    for key, values in parsed.items():
        # IWS returns single value as string, multiple values as list
        if len(values) == 1:
            result[key] = unquote_plus(values[0])
        else:
            result[key] = [unquote_plus(v) for v in values]
    return result


def test_iws_handler():
    """Test basic IWS handler functionality."""
    from config_web_editor.iws_web_handler import IWSWebHandler
    from config_web_editor.config_editor import WebConfigEditor

    # Set up paths
    current_dir = os.path.dirname(__file__)
    plugin_dir = os.path.join(current_dir, '..', 'Auto Lights.indigoPlugin', 'Contents', 'Server Plugin')
    config_file = os.path.join(plugin_dir, 'config_web_editor', 'config', 'auto_lights_conf_empty.json')
    schema_file = os.path.join(plugin_dir, 'config_web_editor', 'config', 'config_schema.json')
    backup_dir = os.path.join(current_dir, 'test_backups')
    auto_backup_dir = os.path.join(current_dir, 'test_auto_backups')

    # Create backup directories
    os.makedirs(backup_dir, exist_ok=True)
    os.makedirs(auto_backup_dir, exist_ok=True)

    try:
        # Initialize config editor
        print("Initializing WebConfigEditor...")
        config_editor = WebConfigEditor(
            config_file=config_file,
            schema_file=schema_file,
            backup_dir=backup_dir,
            auto_backup_dir=auto_backup_dir,
            flask_app=None
        )

        # Initialize IWS handler
        print("Initializing IWSWebHandler...")
        handler = IWSWebHandler(
            config_editor=config_editor,
            plugin_id="com.vtmikel.autolights"
        )

        # Test index page rendering
        print("\n=== Testing Index Page ===")
        response = handler.handle_request(
            method="GET",
            headers={},
            body_params={},
            params={}
        )

        print(f"Status: {response['status']}")
        print(f"Headers: {response['headers']}")
        print(f"Content length: {len(response['content'])}")

        assert response['status'] == 200, f"Index page should return 200, got {response['status']}"
        assert len(response['content']) > 0, "Index page should have content"
        print("✓ Index page rendered successfully")
        # Print first 500 chars of content
        print("\nFirst 500 chars of content:")
        print(response['content'][:500])

        # Note: Static files are served automatically by IWS from Resources/static/
        # No plugin code needed for static file serving

        # Test URL generation
        print("\n=== Testing URL Generation ===")
        test_urls = [
            ('index', {}),
            ('zones', {}),
            ('zone_config', {'zone_id': '0'}),
            ('static', {'filename': 'css/main.css'}),
        ]

        for endpoint, kwargs in test_urls:
            url = handler._url_for(endpoint, **kwargs)
            print(f"  {endpoint}: {url}")

        print("\n✓ All basic tests passed!")

    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        raise


# Test removed: IWS implementation uses POST-re-render pattern instead of redirects
# The _redirect() method tested here was never implemented in the IWS version


def test_lighting_period_post_with_none_values():
    """
    Test that creating a lighting period with minimal form data (which produces None values)
    properly normalizes to schema defaults before saving.

    This prevents the "incorrect value returned from plugin" error that occurs when
    WTForms returns None for empty IntegerField values with Optional validator.
    """
    import json
    import tempfile
    import shutil
    from config_web_editor.iws_web_handler import IWSWebHandler
    from config_web_editor.config_editor import WebConfigEditor

    # Set up paths with temporary config file
    current_dir = os.path.dirname(__file__)
    plugin_dir = os.path.join(current_dir, '..', 'Auto Lights.indigoPlugin', 'Contents', 'Server Plugin')
    schema_file = os.path.join(plugin_dir, 'config_web_editor', 'config', 'config_schema.json')
    backup_dir = os.path.join(current_dir, 'test_backups')
    auto_backup_dir = os.path.join(current_dir, 'test_auto_backups')

    # Create temporary config file for this test
    temp_config_dir = tempfile.mkdtemp()
    temp_config_file = os.path.join(temp_config_dir, 'test_config.json')

    # Initialize with empty config structure
    initial_config = {
        "plugin_config": {
            "default_lock_duration": 0,
            "default_lock_extension_duration": 0,
            "global_behavior_variables": []
        },
        "zones": [],
        "lighting_periods": []
    }

    with open(temp_config_file, 'w') as f:
        json.dump(initial_config, f, indent=2)

    # Create backup directories
    os.makedirs(backup_dir, exist_ok=True)
    os.makedirs(auto_backup_dir, exist_ok=True)

    try:
        print("\n=== Testing Lighting Period POST with None Values ===")

        # Initialize handler
        config_editor = WebConfigEditor(
            config_file=temp_config_file,
            schema_file=schema_file,
            backup_dir=backup_dir,
            auto_backup_dir=auto_backup_dir,
            flask_app=None
        )

        handler = IWSWebHandler(
            config_editor=config_editor,
            plugin_id="com.vtmikel.autolights"
        )

        # Simulate POST with minimal form data (only required fields)
        # This will cause WTForms to return None for optional IntegerFields
        # Note: Empty string values for integer fields become None with Optional validator
        post_body = "name=Test+Period&mode=On+and+Off&from_time_hour=&from_time_minute=&to_time_hour=&to_time_minute=&lock_duration=&limit_brightness="

        print(f"Simulating POST with body: {post_body}")

        # Parse body to dict (simulating what IWS does)
        body_params = parse_form_body_to_dict(post_body)
        print(f"Parsed body_params: {body_params}")

        # Call the POST handler with pre-parsed body_params
        response = handler.handle_request(
            method="POST",
            headers={},
            body_params=body_params,
            params={"page": "lighting_period/new"}
        )

        print(f"Response status: {response['status']}")
        print(f"Response headers: {response['headers']}")

        # Note: IWS uses POST-re-render pattern, not POST-redirect-GET
        # So we expect 200 (page re-render) on success, not 302
        assert response['status'] == 200, f"Expected 200 (re-render), got {response['status']}"
        print("✓ Response is successful (re-rendered page)")

        # Load the saved config
        with open(temp_config_file, 'r') as f:
            saved_config = json.load(f)

        periods = saved_config.get('lighting_periods', [])
        assert len(periods) == 1, f"Expected 1 lighting period, found {len(periods)}"
        print(f"✓ Config contains {len(periods)} lighting period")

        period = periods[0]
        print(f"\nSaved lighting period data:")
        for key, value in period.items():
            print(f"  {key}: {value} (type: {type(value).__name__})")

        # Verify all fields have valid values (no None)
        assert period.get('name') is not None, "name should not be None"
        assert period.get('mode') is not None, "mode should not be None"
        assert period.get('from_time_hour') is not None, "from_time_hour should not be None"
        assert period.get('from_time_minute') is not None, "from_time_minute should not be None"
        assert period.get('to_time_hour') is not None, "to_time_hour should not be None"
        assert period.get('to_time_minute') is not None, "to_time_minute should not be None"
        assert period.get('lock_duration') is not None, "lock_duration should not be None"
        assert period.get('limit_brightness') is not None, "limit_brightness should not be None"
        print("✓ All fields have non-None values")

        # Verify schema defaults were applied
        assert period.get('from_time_hour') == 0, f"Expected from_time_hour=0, got {period.get('from_time_hour')}"
        assert period.get('from_time_minute') == 0, f"Expected from_time_minute=0, got {period.get('from_time_minute')}"
        assert period.get('to_time_hour') == 23, f"Expected to_time_hour=23, got {period.get('to_time_hour')}"
        assert period.get('to_time_minute') == 45, f"Expected to_time_minute=45, got {period.get('to_time_minute')}"
        assert period.get('lock_duration') == -1, f"Expected lock_duration=-1, got {period.get('lock_duration')}"
        assert period.get('limit_brightness') == -1, f"Expected limit_brightness=-1, got {period.get('limit_brightness')}"
        print("✓ Schema defaults were correctly applied")

        # Test that LightingPeriod can be instantiated from this data (simulates config reload)
        sys.path.insert(0, os.path.join(plugin_dir, 'auto_lights'))
        from auto_lights.lighting_period import LightingPeriod

        try:
            lighting_period_obj = LightingPeriod.from_config_dict(period)
            print(f"✓ LightingPeriod instantiated successfully: {lighting_period_obj.name}")
        except Exception as e:
            raise AssertionError(f"Failed to instantiate LightingPeriod from saved data: {e}")

        print("\n✓ All lighting period POST tests passed!")

    except Exception as e:
        print(f"\n✗ Lighting period POST test failed: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        # Clean up temporary config directory
        if os.path.exists(temp_config_dir):
            shutil.rmtree(temp_config_dir)


def test_all_page_routes():
    """Test that all major page routes work correctly."""
    from config_web_editor.iws_web_handler import IWSWebHandler
    from config_web_editor.config_editor import WebConfigEditor

    # Set up paths
    current_dir = os.path.dirname(__file__)
    plugin_dir = os.path.join(current_dir, '..', 'Auto Lights.indigoPlugin', 'Contents', 'Server Plugin')
    config_file = os.path.join(plugin_dir, 'config_web_editor', 'config', 'auto_lights_conf_empty.json')
    schema_file = os.path.join(plugin_dir, 'config_web_editor', 'config', 'config_schema.json')
    backup_dir = os.path.join(current_dir, 'test_backups')
    auto_backup_dir = os.path.join(current_dir, 'test_auto_backups')

    # Create backup directories
    os.makedirs(backup_dir, exist_ok=True)
    os.makedirs(auto_backup_dir, exist_ok=True)

    try:
        # Initialize handler
        config_editor = WebConfigEditor(
            config_file=config_file,
            schema_file=schema_file,
            backup_dir=backup_dir,
            auto_backup_dir=auto_backup_dir,
            flask_app=None
        )

        handler = IWSWebHandler(
            config_editor=config_editor,
            plugin_id="com.vtmikel.autolights"
        )

        # Test all major routes
        test_routes = [
            ("", "Index/Home"),
            ("index", "Index (explicit)"),
            ("zones", "Zones list"),
            ("zone/new", "New zone"),
            ("plugin_config", "Plugin configuration"),
            ("lighting_periods", "Lighting periods list"),
            ("lighting_period/new", "New lighting period"),
            ("config_backup", "Config backup"),
        ]

        print("\n=== Testing All Page Routes ===")
        for page, description in test_routes:
            params = {"page": page} if page else {}
            response = handler.handle_request(
                method="GET",
                headers={},
                body_params={},
                params=params
            )

            assert response['status'] == 200, f"{description} returned status {response['status']}"
            assert len(response['content']) > 0, f"{description} returned empty content"
            print(f"✓ {description}: OK")

        print("\n✓ All page routes test passed!")

    except Exception as e:
        print(f"\n✗ Page routes test failed: {e}")
        import traceback
        traceback.print_exc()
        raise


def test_zone_post_operations():
    """Test zone save and delete POST operations."""
    import json
    import tempfile
    import shutil
    from config_web_editor.iws_web_handler import IWSWebHandler
    from config_web_editor.config_editor import WebConfigEditor

    # Set up paths with temporary config file
    current_dir = os.path.dirname(__file__)
    plugin_dir = os.path.join(current_dir, '..', 'Auto Lights.indigoPlugin', 'Contents', 'Server Plugin')
    schema_file = os.path.join(plugin_dir, 'config_web_editor', 'config', 'config_schema.json')
    backup_dir = os.path.join(current_dir, 'test_backups')
    auto_backup_dir = os.path.join(current_dir, 'test_auto_backups')

    # Create temporary config directory
    temp_config_dir = tempfile.mkdtemp()
    temp_config_file = os.path.join(temp_config_dir, 'test_config.json')

    # Initialize with empty config
    initial_config = {
        "plugin_config": {
            "default_lock_duration": 0,
            "default_lock_extension_duration": 0,
            "global_behavior_variables": []
        },
        "zones": [],
        "lighting_periods": []
    }

    with open(temp_config_file, 'w') as f:
        json.dump(initial_config, f, indent=2)

    # Create backup directories
    os.makedirs(backup_dir, exist_ok=True)
    os.makedirs(auto_backup_dir, exist_ok=True)

    try:
        print("\n=== Testing Zone POST Operations ===")

        # Initialize handler
        config_editor = WebConfigEditor(
            config_file=temp_config_file,
            schema_file=schema_file,
            backup_dir=backup_dir,
            auto_backup_dir=auto_backup_dir,
            flask_app=None
        )

        handler = IWSWebHandler(
            config_editor=config_editor,
            plugin_id="com.vtmikel.autolights"
        )

        # Test 1: Create new zone
        print("\nTest 1: Create new zone via POST")
        post_body = "name=Test+Zone&enabled=on"
        body_params = parse_form_body_to_dict(post_body)

        response = handler.handle_request(
            method="POST",
            headers={},
            body_params=body_params,
            params={"page": "zone/new"}
        )

        assert response['status'] == 200, f"Expected 200, got {response['status']}"
        print("✓ New zone POST returned 200")

        # Verify zone was created
        with open(temp_config_file, 'r') as f:
            saved_config = json.load(f)

        zones = saved_config.get('zones', [])
        assert len(zones) == 1, f"Expected 1 zone, found {len(zones)}"
        assert zones[0].get('name') == 'Test Zone', f"Expected 'Test Zone', got {zones[0].get('name')}"
        print("✓ Zone created successfully in config")

        # Test 2: Update existing zone
        print("\nTest 2: Update existing zone via POST")
        post_body = "name=Updated+Zone&enabled=on"
        body_params = parse_form_body_to_dict(post_body)

        response = handler.handle_request(
            method="POST",
            headers={},
            body_params=body_params,
            params={"page": "zone/0"}
        )

        assert response['status'] == 200, f"Expected 200, got {response['status']}"
        print("✓ Zone update POST returned 200")

        # Verify zone was updated
        with open(temp_config_file, 'r') as f:
            saved_config = json.load(f)

        zones = saved_config.get('zones', [])
        assert zones[0].get('name') == 'Updated Zone', f"Expected 'Updated Zone', got {zones[0].get('name')}"
        print("✓ Zone updated successfully")

        # Test 3: Delete zone
        print("\nTest 3: Delete zone via POST")
        response = handler.handle_request(
            method="POST",
            headers={},
            body_params={},
            params={"page": "zone/delete/0"}
        )

        assert response['status'] == 200, f"Expected 200, got {response['status']}"
        print("✓ Zone delete POST returned 200")

        # Verify zone was deleted
        with open(temp_config_file, 'r') as f:
            saved_config = json.load(f)

        zones = saved_config.get('zones', [])
        assert len(zones) == 0, f"Expected 0 zones after delete, found {len(zones)}"
        print("✓ Zone deleted successfully")

        print("\n✓ All zone POST operation tests passed!")

    except Exception as e:
        print(f"\n✗ Zone POST operation test failed: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        # Clean up temporary config directory
        if os.path.exists(temp_config_dir):
            shutil.rmtree(temp_config_dir)


if __name__ == "__main__":
    try:
        test_iws_handler()
        test_all_page_routes()
        test_lighting_period_post_with_none_values()
        test_zone_post_operations()
        print("\n=== All tests passed! ===")
        sys.exit(0)
    except Exception:
        print("\n=== Tests failed! ===")
        sys.exit(1)

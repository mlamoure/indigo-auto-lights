"""
Test script for IWS Web Handler

This script tests the IWSWebHandler independently to verify it works correctly
before deploying to Indigo.
"""

import sys
import os

# Add parent directory to path to import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'Auto Lights.indigoPlugin', 'Contents', 'Server Plugin'))

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
            body="",
            query_string=""
        )

        print(f"Status: {response['status']}")
        print(f"Headers: {response['headers']}")
        print(f"Content length: {len(response['content'])}")

        if response['status'] == 200:
            print("✓ Index page rendered successfully")
            # Print first 500 chars of content
            print("\nFirst 500 chars of content:")
            print(response['content'][:500])
        else:
            print(f"✗ Error: Status {response['status']}")
            print(response['content'])

        # Test static file serving
        print("\n=== Testing Static CSS File ===")
        response = handler.serve_static_file(query_string="file=css/main.css")

        print(f"Status: {response['status']}")
        print(f"Headers: {response['headers']}")
        print(f"Content length: {len(response['content'])}")

        if response['status'] == 200:
            print("✓ CSS file served successfully")
        else:
            print(f"✗ Error: Status {response['status']}")

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
        return True

    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_iws_handler()
    sys.exit(0 if success else 1)

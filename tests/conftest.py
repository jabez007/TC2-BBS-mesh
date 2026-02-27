import os
import shutil
import pytest

def pytest_configure(config):
    """
    Ensure config.ini exists before running tests.
    If missing, copy it from example_config.ini.
    """
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    config_path = os.path.join(project_root, "config.ini")
    example_path = os.path.join(project_root, "example_config.ini")

    if not os.path.exists(config_path):
        if os.path.exists(example_path):
            print(f"\nConfig file missing. Copying {example_path} to {config_path}...")
            shutil.copy(example_path, config_path)
        else:
            pytest.exit(f"Critical Error: {example_path} not found. Cannot initialize test environment.")

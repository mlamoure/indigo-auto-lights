import glob
import json
import logging
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Union

from flask import Flask

from .tools.indigo_api_tools import (
    indigo_get_all_house_devices,
    indigo_get_all_house_variables,
)

logger = logging.getLogger(__name__)


class WebConfigEditor:
    def __init__(
        self,
        config_file: Union[str, Path],
        schema_file: Union[str, Path],
        backup_dir: Union[str, Path],
        auto_backup_dir: Union[str, Path],
        flask_app: Optional[Flask] = None,
    ) -> None:
        """
        Initialize the configuration editor.

        :param config_file: Path to the JSON config file.
        :param schema_file: Path to the JSON schema file.
        :param backup_dir: Directory for manual backups.
        :param auto_backup_dir: Directory for automatic backups.
        :param flask_app: Optional Flask app for logging in background tasks.
        """
        self.config_file = Path(config_file)
        self.schema_file = Path(schema_file)
        self.backup_dir = Path(backup_dir)
        self.auto_backup_dir = Path(auto_backup_dir)
        self.app = flask_app

        self.config_schema: Dict[str, Any] = self.load_schema()
        self._cache_lock = threading.RLock()
        self._indigo_devices_cache: Dict[str, Any] = {"data": None}
        self._indigo_variables_cache: Dict[str, Any] = {"data": None}

    def load_schema(self) -> Dict[str, Any]:
        """
        Load and return the JSON schema as a dict.
        """
        with self.schema_file.open() as f:
            return json.load(f)

    def load_config(self):
        try:
            with open(self.config_file) as f:
                return json.load(f)
        except Exception:
            return {"plugin_config": {}, "zones": []}

    def save_config(self, config_data: Dict[str, Any]) -> None:
        """
        Save the configuration JSON atomically and prune old backups.
        """
        # Ensure auto backup directory exists
        self.auto_backup_dir.mkdir(parents=True, exist_ok=True)

        # Automatic backup
        if self.config_file.exists():
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            backup = self.auto_backup_dir / f"auto_backup_{timestamp}.json"
            shutil.copy2(self.config_file, backup)
            self._prune_backups(
                str(self.auto_backup_dir), keep=20, prefix="auto_backup_"
            )

        # Write new config
        with self.config_file.open("w") as f:
            json.dump(config_data, f, indent=2)

        # Notify plugin to reload config immediately if callback is registered
        try:
            cb = None
            if self.app:
                cb = self.app.config.get("reload_config_cb")
            if callable(cb):
                cb()
        except Exception as e:
            logger.error(f"Error running reload_config_cb: {e}")

    def create_manual_backup(self) -> None:
        """
        Manually back up the config and prune old backups.
        """
        # Ensure manual backup directory exists
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        if self.config_file.exists():
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            backup = self.backup_dir / f"manual_backup_{timestamp}.json"
            shutil.copy2(self.config_file, backup)
            self._prune_backups(str(self.backup_dir), keep=20, prefix="manual_backup_")

    def list_manual_backups(self):
        return [
            os.path.basename(p)
            for p in glob.glob(os.path.join(self.backup_dir, "manual_backup_*.json"))
        ]

    def list_auto_backups(self):
        return sorted(
            glob.glob(os.path.join(self.auto_backup_dir, "auto_backup_*.json")),
            reverse=True,
        )

    def restore_backup(self, backup_type, backup_file):
        if backup_type == "manual":
            backup_path = os.path.join(self.backup_dir, backup_file)
        else:
            backup_path = os.path.join(self.auto_backup_dir, backup_file)
        if os.path.exists(backup_path):
            shutil.copy2(backup_path, self.config_file)
            return True
        return False

    def delete_backup(self, backup_type: str, backup_file: str) -> bool:
        """
        Delete a manual or automatic backup.
        """
        if backup_type == "manual":
            backup_path = self.backup_dir / backup_file
        else:
            backup_path = self.auto_backup_dir / backup_file
        if backup_path.exists():
            backup_path.unlink()
            return True
        return False

    def _prune_backups(
        self, directory: Union[str, Path], keep: int = 20, prefix: str = "backup_"
    ) -> None:
        """
        Remove oldest backup files in the given directory, keeping only the newest `keep` files
        with names starting with `prefix`.
        """
        dir_path = Path(directory)
        backups = sorted(dir_path.glob(f"{prefix}*.json"))
        for old in backups[:-keep]:
            try:
                old.unlink()
            except Exception:
                logger.warning("Could not remove old backup %s", old)

    def _refresh_indigo_caches(self, interval_seconds: int) -> None:
        """
        Background worker to refresh Indigo device/variable caches every interval_seconds seconds.
        """
        while True:
            try:
                self._refresh_indigo_once()
                msg = f"[{datetime.now():%Y-%m-%d %H:%M}] Indigo caches refreshed"
                if self.app:
                    with self.app.app_context():
                        self.app.logger.info(msg)
                else:
                    logger.info(msg)
            except Exception as e:
                err = f"Error refreshing caches: {e}"
                if self.app:
                    with self.app.app_context():
                        self.app.logger.error(err)
                else:
                    logger.error(err)
            time.sleep(interval_seconds)

    def start_cache_refresher(self, interval_seconds: int = 900) -> threading.Thread:
        """
        Launch background thread refreshing Indigo caches every interval_seconds seconds.
        """
        thread = threading.Thread(
            target=self._refresh_indigo_caches,
            args=(interval_seconds,),
            daemon=True,
        )
        thread.start()
        return thread

    def get_cached_indigo_devices(self):
        with self._cache_lock:
            if self._indigo_devices_cache["data"] is None:
                self._refresh_indigo_once()
            return self._indigo_devices_cache["data"]

    def get_cached_indigo_variables(self):
        with self._cache_lock:
            if self._indigo_variables_cache["data"] is None:
                self._refresh_indigo_once()
            return self._indigo_variables_cache["data"]

    def _refresh_indigo_once(self) -> None:
        """
        Fetch Indigo devices and variables once and store in cache.
        """
        new_devices = indigo_get_all_house_devices()
        new_variables = indigo_get_all_house_variables()
        with self._cache_lock:
            self._indigo_devices_cache["data"] = new_devices
            self._indigo_variables_cache["data"] = new_variables

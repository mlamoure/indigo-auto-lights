import glob
import json
import os
import shutil
import threading
import time
from collections import OrderedDict
from datetime import datetime

from flask import current_app

from .tools.indigo_api_tools import indigo_get_all_house_devices, indigo_get_all_house_variables


class WebConfigEditor:
    def __init__(self, config_file, schema_file, backup_dir, auto_backup_dir):
        self.config_file = config_file
        self.schema_file = schema_file
        self.backup_dir = backup_dir
        self.auto_backup_dir = auto_backup_dir
        self.config_schema = self.load_schema()
        self._cache_lock = threading.Lock()
        self._indigo_devices_cache = {"data": None}
        self._indigo_variables_cache = {"data": None}

    def load_schema(self):
        with open(self.schema_file) as f:
            return json.load(f, object_pairs_hook=OrderedDict)

    def load_config(self):
        try:
            with open(self.config_file) as f:
                return json.load(f)
        except Exception:
            return {"plugin_config": {}, "zones": []}

    def save_config(self, config_data):
        if os.path.exists(self.config_file):
            os.makedirs(self.backup_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            backup_file = os.path.join(self.backup_dir, f"manual_backup_{timestamp}.json")
            shutil.copy2(self.config_file, backup_file)
            backups = sorted(glob.glob(os.path.join(self.backup_dir, "manual_backup_*.json")))
            while len(backups) > 20:
                os.remove(backups[0])
                backups.pop(0)
        with open(self.config_file, "w") as f:
            json.dump(config_data, f, indent=2)

    def refresh_indigo_caches(self):
        while True:
            try:
                new_devices = indigo_get_all_house_devices()
                new_variables = indigo_get_all_house_variables()
                with self._cache_lock:
                    self._indigo_devices_cache["data"] = new_devices
                    self._indigo_variables_cache["data"] = new_variables
                current_app.logger.info(f"[{datetime.now()}] Indigo caches refreshed")
            except Exception as e:
                current_app.logger.error(f"Error refreshing caches: {e}")
            time.sleep(900)  # 15 minutes

    def start_cache_refresher(self):
        thread = threading.Thread(target=self.refresh_indigo_caches, daemon=True)
        thread.start()

    def get_cached_indigo_devices(self):
        with self._cache_lock:
            if self._indigo_devices_cache["data"] is None:
                self._indigo_devices_cache["data"] = indigo_get_all_house_devices()
            return self._indigo_devices_cache["data"]

    def get_cached_indigo_variables(self):
        with self._cache_lock:
            if self._indigo_variables_cache["data"] is None:
                self._indigo_variables_cache["data"] = indigo_get_all_house_variables()
            return self._indigo_variables_cache["data"]

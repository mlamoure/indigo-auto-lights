import json
import os
import glob
import shutil
from datetime import datetime

class AutoLightsWebConfig:
    """
    Encapsulates all configuration file operations.
    Provides methods to load, save, and back up the configuration file.
    """
    def __init__(self, config_file_path: str):
        self.config_file_path = config_file_path
        self.config_dir = os.path.dirname(os.path.abspath(self.config_file_path))
        self.manual_backup_dir = os.path.join(self.config_dir, "backups")
        self.auto_backup_dir = os.path.join(self.config_dir, "auto_backups")
        os.makedirs(self.manual_backup_dir, exist_ok=True)
        os.makedirs(self.auto_backup_dir, exist_ok=True)

        if not os.path.exists(self.config_file_path):
            empty_config_file = os.path.join(
                os.path.dirname(self.config_file_path), "auto_lights_empty_conf.json"
            )
            if os.path.exists(empty_config_file):
                shutil.copyfile(empty_config_file, self.config_file_path)
            else:
                default_data = {"plugin_config": {}, "zones": [], "lighting_periods": []}
                self.save_config(default_data)

    def load_config(self) -> dict:
        try:
            with open(self.config_file_path, "r") as f:
                return json.load(f)
        except Exception:
            return {"plugin_config": {}, "zones": [], "lighting_periods": []}

    def save_config(self, config_data: dict) -> None:
        if os.path.exists(self.config_file_path):
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            backup_file = os.path.join(self.auto_backup_dir, f"auto_backup_{timestamp}.json")
            shutil.copy2(self.config_file_path, backup_file)
            backups = sorted(glob.glob(os.path.join(self.auto_backup_dir, "auto_backup_*.json")))
            while len(backups) > 20:
                os.remove(backups[0])
                backups.pop(0)
        with open(self.config_file_path, "w") as f:
            json.dump(config_data, f, indent=2)

    def create_manual_backup(self) -> None:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        dest = os.path.join(self.manual_backup_dir, f"manual_backup_{timestamp}.json")
        shutil.copy2(self.config_file_path, dest)

    def restore_backup(self, backup_file: str) -> None:
        for backup_dir in [self.manual_backup_dir, self.auto_backup_dir]:
            candidate = os.path.join(backup_dir, backup_file)
            if os.path.exists(candidate):
                shutil.copy2(candidate, self.config_file_path)
                break

    def delete_backup(self, backup_file: str, backup_type: str) -> None:
        backup_dir = self.manual_backup_dir if backup_type == "manual" else self.auto_backup_dir
        path_to_delete = os.path.join(backup_dir, backup_file)
        if os.path.exists(path_to_delete):
            os.remove(path_to_delete)

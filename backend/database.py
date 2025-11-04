"""
Database abstraction layer for the press projector system.
Provides abstract interface and JSON file-based implementation.
"""

from abc import ABC, abstractmethod
import json
import os
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging


class DB_interface(ABC):
    """Abstract database interface for storing system data."""
    
    @abstractmethod
    def save_press_calibration(self, press_id: str, calibration_data: Dict[str, Any]) -> bool:
        """Save calibration data for a specific press."""
        pass
    
    @abstractmethod
    def load_press_calibration(self, press_id: str) -> Optional[Dict[str, Any]]:
        """Load calibration data for a specific press."""
        pass
    
    @abstractmethod
    def list_presses(self) -> List[str]:
        """List all configured press IDs."""
        pass
    
    @abstractmethod
    def delete_press(self, press_id: str) -> bool:
        """Delete a press and its calibration."""
        pass
    
    @abstractmethod
    def save_job(self, job_id: str, job_data: Dict[str, Any]) -> bool:
        """Save job data."""
        pass
    
    @abstractmethod
    def load_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Load job data."""
        pass
    
    @abstractmethod
    def list_jobs(self) -> List[str]:
        """List all job IDs."""
        pass
    
    @abstractmethod
    def save_configuration(self, config_name: str, config_data: Dict[str, Any]) -> bool:
        """Save layout configuration."""
        pass
    
    @abstractmethod
    def load_configuration(self, config_name: str) -> Optional[Dict[str, Any]]:
        """Load layout configuration."""
        pass
    
    @abstractmethod
    def list_configurations(self) -> List[str]:
        """List all configuration names."""
        pass
    
    @abstractmethod
    def delete_job(self, job_id: str) -> bool:
        """Delete a job."""
        pass
    
    @abstractmethod
    def delete_configuration(self, config_name: str) -> bool:
        """Delete a configuration."""
        pass


class FileBasedDB(DB_interface):
    """JSON file-based database implementation."""
    
    def __init__(self, base_path: str = "config"):
        self.base_path = base_path
        self.presses_dir = os.path.join(base_path, "presses")
        self.jobs_dir = os.path.join(base_path, "jobs")
        self.configs_dir = os.path.join(base_path, "configurations")
        self.last_scene_file = os.path.join(base_path, "last_scene.json")
        
        # Create directories if they don't exist
        os.makedirs(self.presses_dir, exist_ok=True)
        os.makedirs(self.jobs_dir, exist_ok=True)
        os.makedirs(self.configs_dir, exist_ok=True)
    
    def _save_json(self, filepath: str, data: Dict[str, Any]) -> bool:
        """Save data to JSON file."""
        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            logging.getLogger(__name__).exception("Error saving to %s", filepath)
            return False
    
    def _load_json(self, filepath: str) -> Optional[Dict[str, Any]]:
        """Load data from JSON file."""
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    return json.load(f)
            return None
        except Exception as e:
            logging.getLogger(__name__).exception("Error loading from %s", filepath)
            return None
    
    def save_press_calibration(self, press_id: str, calibration_data: Dict[str, Any]) -> bool:
        """Save calibration data for a specific press."""
        calibration_data['press_id'] = press_id
        calibration_data['timestamp'] = datetime.now().isoformat()
        calibration_file = os.path.join(self.presses_dir, f"{press_id}.json")
        return self._save_json(calibration_file, calibration_data)
    
    def load_press_calibration(self, press_id: str) -> Optional[Dict[str, Any]]:
        """Load calibration data for a specific press."""
        calibration_file = os.path.join(self.presses_dir, f"{press_id}.json")
        return self._load_json(calibration_file)
    
    def list_presses(self) -> List[str]:
        """List all configured press IDs."""
        try:
            if not os.path.exists(self.presses_dir):
                return []
            files = [f for f in os.listdir(self.presses_dir) if f.endswith('.json')]
            return [f[:-5] for f in files]  # Remove .json extension
        except Exception as e:
            logging.getLogger(__name__).exception("Error listing presses")
            return []
    
    def delete_press(self, press_id: str) -> bool:
        """Delete a press and its calibration."""
        try:
            calibration_file = os.path.join(self.presses_dir, f"{press_id}.json")
            if os.path.exists(calibration_file):
                os.remove(calibration_file)
                return True
            return False
        except Exception as e:
            logging.getLogger(__name__).exception("Error deleting press %s", press_id)
            return False
    
    def save_job(self, job_id: str, job_data: Dict[str, Any]) -> bool:
        """Save job data."""
        job_data['job_id'] = job_id
        job_data['timestamp'] = datetime.now().isoformat()
        job_file = os.path.join(self.jobs_dir, f"{job_id}.json")
        return self._save_json(job_file, job_data)
    
    def load_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Load job data."""
        job_file = os.path.join(self.jobs_dir, f"{job_id}.json")
        return self._load_json(job_file)
    
    def list_jobs(self) -> List[str]:
        """List all job IDs."""
        try:
            files = [f for f in os.listdir(self.jobs_dir) if f.endswith('.json')]
            return [f[:-5] for f in files]  # Remove .json extension
        except Exception as e:
            print(f"Error listing jobs: {e}")
            return []
    
    def save_configuration(self, config_name: str, config_data: Dict[str, Any]) -> bool:
        """Save layout configuration."""
        config_data['config_name'] = config_name
        config_data['timestamp'] = datetime.now().isoformat()
        config_file = os.path.join(self.configs_dir, f"{config_name}.json")
        return self._save_json(config_file, config_data)
    
    def load_configuration(self, config_name: str) -> Optional[Dict[str, Any]]:
        """Load layout configuration."""
        config_file = os.path.join(self.configs_dir, f"{config_name}.json")
        return self._load_json(config_file)
    
    def list_configurations(self) -> List[str]:
        """List all configuration names."""
        try:
            files = [f for f in os.listdir(self.configs_dir) if f.endswith('.json')]
            return [f[:-5] for f in files]  # Remove .json extension
        except Exception as e:
            logging.getLogger(__name__).exception("Error listing configurations")
            return []
    
    def delete_job(self, job_id: str) -> bool:
        """Delete a job."""
        try:
            job_file = os.path.join(self.jobs_dir, f"{job_id}.json")
            if os.path.exists(job_file):
                os.remove(job_file)
                return True
            return False
        except Exception as e:
            logging.getLogger(__name__).exception("Error deleting job %s", job_id)
            return False
    
    def delete_configuration(self, config_name: str) -> bool:
        """Delete a configuration."""
        try:
            config_file = os.path.join(self.configs_dir, f"{config_name}.json")
            if os.path.exists(config_file):
                os.remove(config_file)
                return True
            return False
        except Exception as e:
            logging.getLogger(__name__).exception("Error deleting configuration %s", config_name)
            return False

    # ===== Last scene helpers =====
    def set_last_scene(self, name: str) -> bool:
        """Persist the last loaded scene name."""
        try:
            data = {"name": name}
            with open(self.last_scene_file, 'w') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            logging.getLogger(__name__).exception("Error saving last scene name")
            return False

    def get_last_scene(self) -> Optional[str]:
        """Return the last loaded scene name if available."""
        try:
            if os.path.exists(self.last_scene_file):
                with open(self.last_scene_file, 'r') as f:
                    data = json.load(f)
                    name = data.get('name')
                    if isinstance(name, str) and name:
                        return name
            return None
        except Exception as e:
            logging.getLogger(__name__).exception("Error loading last scene name")
            return None


# Example usage and testing
if __name__ == "__main__":
    pass

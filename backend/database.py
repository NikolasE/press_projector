"""
Database abstraction layer for the press projector system.
Provides abstract interface and JSON file-based implementation.
"""

from abc import ABC, abstractmethod
import json
import os
from typing import Dict, List, Optional, Any
from datetime import datetime


class DB_interface(ABC):
    """Abstract database interface for storing system data."""
    
    @abstractmethod
    def save_calibration(self, calibration_data: Dict[str, Any]) -> bool:
        """Save calibration data."""
        pass
    
    @abstractmethod
    def load_calibration(self) -> Optional[Dict[str, Any]]:
        """Load calibration data."""
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
        self.calibration_file = os.path.join(base_path, "calibration.json")
        self.jobs_dir = os.path.join(base_path, "jobs")
        self.configs_dir = os.path.join(base_path, "configurations")
        
        # Create directories if they don't exist
        os.makedirs(self.jobs_dir, exist_ok=True)
        os.makedirs(self.configs_dir, exist_ok=True)
    
    def _save_json(self, filepath: str, data: Dict[str, Any]) -> bool:
        """Save data to JSON file."""
        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving to {filepath}: {e}")
            return False
    
    def _load_json(self, filepath: str) -> Optional[Dict[str, Any]]:
        """Load data from JSON file."""
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    return json.load(f)
            return None
        except Exception as e:
            print(f"Error loading from {filepath}: {e}")
            return None
    
    def save_calibration(self, calibration_data: Dict[str, Any]) -> bool:
        """Save calibration data."""
        calibration_data['timestamp'] = datetime.now().isoformat()
        return self._save_json(self.calibration_file, calibration_data)
    
    def load_calibration(self) -> Optional[Dict[str, Any]]:
        """Load calibration data."""
        return self._load_json(self.calibration_file)
    
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
            print(f"Error listing configurations: {e}")
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
            print(f"Error deleting job {job_id}: {e}")
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
            print(f"Error deleting configuration {config_name}: {e}")
            return False


# Example usage and testing
if __name__ == "__main__":
    db = FileBasedDB()
    
    # Test calibration
    calibration_data = {
        "source_points": [[100, 100], [500, 100], [500, 400], [100, 400]],
        "destination_points": [[0, 0], [300, 0], [300, 200], [0, 200]],
        "press_width_mm": 300,
        "press_height_mm": 200,
        "transformation_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    }
    
    print("Saving calibration:", db.save_calibration(calibration_data))
    print("Loading calibration:", db.load_calibration())
    
    # Test job
    job_data = {
        "design_file": "test_design.png",
        "position": {"x": 50, "y": 50},
        "temperature": 180,
        "duration": 60
    }
    
    print("Saving job:", db.save_job("test_job", job_data))
    print("Loading job:", db.load_job("test_job"))
    print("Listing jobs:", db.list_jobs())

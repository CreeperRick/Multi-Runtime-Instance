import os
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

class InstanceBootstrapper:
    """Handles instance discovery, repair, and initialization."""
    
    def __init__(self, instances_dir: str = "instances"):
        self.instances_dir = Path(instances_dir)
        self.global_dirs = ["uploads", "logs", "history", "temp"]
        
    def bootstrap(self) -> Dict[str, any]:
        """Main bootstrap routine. Returns instance registry."""
        self._create_global_directories()
        self._ensure_instances_dir()
        instances = self._discover_instances()
        instances = self._repair_all_instances(instances)
        
        if not instances:
            instances = self._create_default_instance()
            
        return {
            "instances": instances,
            "last_active": self._get_last_active_instance(instances)
        }
    
    def _create_global_directories(self):
        for dir_name in self.global_dirs:
            Path(dir_name).mkdir(exist_ok=True)
    
    def _ensure_instances_dir(self):
        self.instances_dir.mkdir(exist_ok=True)
    
    def _discover_instances(self) -> Dict[str, dict]:
        """Scan instances directory and return dict of instance_id -> metadata."""
        instances = {}
        for item in self.instances_dir.iterdir():
            if item.is_dir():
                # Check if it's a valid instance (has settings.json or metadata.json)
                settings_file = item / "settings.json"
                metadata_file = item / "metadata.json"
                if settings_file.exists() or metadata_file.exists():
                    instance_id = self._get_or_create_instance_id(item)
                    metadata = self._load_metadata(item, instance_id)
                    instances[instance_id] = metadata
                else:
                    # Not a valid instance, skip but log
                    print(f"Ignoring invalid instance folder: {item.name}")
        return instances
    
    def _get_or_create_instance_id(self, instance_path: Path) -> str:
        """Extract instance ID from metadata, or create new one."""
        metadata_path = instance_path / "metadata.json"
        if metadata_path.exists():
            try:
                with open(metadata_path, 'r') as f:
                    data = json.load(f)
                    return data.get("instance_id", str(uuid.uuid4()))
            except:
                pass
        return str(uuid.uuid4())
    
    def _load_metadata(self, instance_path: Path, instance_id: str) -> dict:
        """Load metadata from file, or create default."""
        metadata_path = instance_path / "metadata.json"
        default_metadata = {
            "instance_id": instance_id,
            "name": instance_path.name,
            "creation_date": datetime.now().isoformat(),
            "last_used": None,
            "description": "",
            "tags": [],
            "detected_runtime": self._detect_runtime(instance_path),
            "total_files": 0,
            "total_executions": 0
        }
        
        if metadata_path.exists():
            try:
                with open(metadata_path, 'r') as f:
                    data = json.load(f)
                    # Merge with defaults to ensure all fields exist
                    for key, value in default_metadata.items():
                        if key not in data:
                            data[key] = value
                    return data
            except Exception as e:
                print(f"Error loading metadata for {instance_path.name}: {e}")
                
        # Save default metadata
        with open(metadata_path, 'w') as f:
            json.dump(default_metadata, f, indent=2)
        return default_metadata
    
    def _detect_runtime(self, instance_path: Path) -> str:
        """Detect runtime based on main.py / main.js presence."""
        has_py = (instance_path / "main.py").exists()
        has_js = (instance_path / "main.js").exists()
        
        if has_py and has_js:
            return "hybrid"
        elif has_py:
            return "python"
        elif has_js:
            return "javascript"
        else:
            return "none"
    
    def _repair_all_instances(self, instances: Dict[str, dict]) -> Dict[str, dict]:
        """Ensure each instance has required subfolders and files."""
        for instance_id, metadata in instances.items():
            instance_path = self.instances_dir / metadata["name"]
            self._repair_instance(instance_path, metadata)
            # Reload metadata after repair (detected_runtime might have changed)
            metadata["detected_runtime"] = self._detect_runtime(instance_path)
            metadata["total_files"] = self._count_files(instance_path / "files")
            self._save_metadata(instance_path, metadata)
        return instances
    
    def _repair_instance(self, instance_path: Path, metadata: dict):
        """Create missing subfolders and regenerate settings if needed."""
        subdirs = ["files", "logs", "history"]
        for subdir in subdirs:
            (instance_path / subdir).mkdir(exist_ok=True)
        
        # Ensure settings.json exists
        settings_path = instance_path / "settings.json"
        if not settings_path.exists():
            default_settings = {
                "runtime_override": None,  # None means auto-detect
                "execution_timeout": 30,
                "auto_save_logs": True
            }
            with open(settings_path, 'w') as f:
                json.dump(default_settings, f, indent=2)
        
        # Ensure metadata.json exists and has required fields
        self._save_metadata(instance_path, metadata)
    
    def _save_metadata(self, instance_path: Path, metadata: dict):
        metadata_path = instance_path / "metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
    
    def _count_files(self, files_dir: Path) -> int:
        if not files_dir.exists():
            return 0
        return sum(1 for _ in files_dir.iterdir() if _.is_file())
    
    def _create_default_instance(self) -> Dict[str, dict]:
        """Create Default instance with sample main.py and main.js."""
        default_path = self.instances_dir / "Default"
        default_path.mkdir(exist_ok=True)
        
        # Create sample main.py
        sample_py = default_path / "main.py"
        if not sample_py.exists():
            sample_py.write_text('''print("Hello from Python instance!")
print("You can run any Python code here.")
import sys
print(f"Python version: {sys.version}")
''')
        
        # Create sample main.js
        sample_js = default_path / "main.js"
        if not sample_js.exists():
            sample_js.write_text('''console.log("Hello from JavaScript instance!");
console.log("You can run any Node.js code here.");
console.log(`Node version: ${process.version}`);
''')
        
        instance_id = str(uuid.uuid4())
        metadata = {
            "instance_id": instance_id,
            "name": "Default",
            "creation_date": datetime.now().isoformat(),
            "last_used": None,
            "description": "Default instance with Python and JavaScript support",
            "tags": ["default", "sample"],
            "detected_runtime": "hybrid",
            "total_files": 0,
            "total_executions": 0
        }
        
        self._repair_instance(default_path, metadata)
        self._save_metadata(default_path, metadata)
        
        return {instance_id: metadata}
    
    def _get_last_active_instance(self, instances: Dict[str, dict]) -> Optional[str]:
        """Read last active instance from file, or return first instance."""
        last_file = Path("last_instance.txt")
        if last_file.exists():
            try:
                last_id = last_file.read_text().strip()
                if last_id in instances:
                    return last_id
            except:
                pass
        # Return first instance ID if any
        if instances:
            return next(iter(instances.keys()))
        return None
    
    def save_last_active(self, instance_id: str):
        Path("last_instance.txt").write_text(instance_id)

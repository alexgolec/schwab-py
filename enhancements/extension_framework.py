"""
Modular Extension Framework for Schwab Trading Service

This module provides a comprehensive extension system that enables third-party plugins
and custom strategies while maintaining system stability and security.

Extension Types Supported:
- Custom signal processors (extending Agent 8)
- Alternative authentication methods (extending Agent 2)
- Custom order types (extending Agent 3)
- Data source connectors (extending Agent 5)
- Risk management modules
- Notification systems

Author: Agent 10 - Extensibility Architect
"""

import asyncio
import importlib
import importlib.util
import inspect
import json
import logging
import os
import sys
import threading
import time
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Type, Union
from weakref import WeakValueDictionary

import yaml


# Configure logging
logger = logging.getLogger(__name__)


class ExtensionType(Enum):
    """Supported extension types"""
    SIGNAL_PROCESSOR = "signal_processor"
    AUTHENTICATION = "authentication"
    ORDER_TYPE = "order_type"
    DATA_SOURCE = "data_source"
    RISK_MANAGEMENT = "risk_management"
    NOTIFICATION = "notification"
    CUSTOM = "custom"


class ExtensionStatus(Enum):
    """Extension lifecycle status"""
    UNLOADED = "unloaded"
    LOADING = "loading"
    LOADED = "loaded"
    ACTIVE = "active"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass
class ExtensionMetadata:
    """Metadata for an extension"""
    name: str
    version: str
    author: str
    description: str
    extension_type: ExtensionType
    dependencies: List[str] = field(default_factory=list)
    required_permissions: List[str] = field(default_factory=list)
    api_version: str = "1.0.0"
    min_system_version: str = "1.0.0"
    max_system_version: str = "*"
    tags: List[str] = field(default_factory=list)
    homepage: Optional[str] = None
    repository: Optional[str] = None
    license: Optional[str] = None


@dataclass
class ExtensionContext:
    """Context provided to extensions"""
    extension_id: str
    metadata: ExtensionMetadata
    config: Dict[str, Any]
    logger: logging.Logger
    api_client: Any  # Schwab client instance
    event_bus: 'EventBus'
    storage: 'ExtensionStorage'
    permissions: Set[str]


class ExtensionError(Exception):
    """Base exception for extension-related errors"""
    pass


class ExtensionLoadError(ExtensionError):
    """Error loading an extension"""
    pass


class ExtensionSecurityError(ExtensionError):
    """Security violation in extension"""
    pass


class ExtensionDependencyError(ExtensionError):
    """Extension dependency error"""
    pass


class ExtensionAPI:
    """Stable API interface for extensions"""
    
    def __init__(self, context: ExtensionContext):
        self.context = context
        self._validate_permissions()
    
    def _validate_permissions(self):
        """Validate extension has required permissions"""
        required = set(self.context.metadata.required_permissions)
        granted = self.context.permissions
        missing = required - granted
        if missing:
            raise ExtensionSecurityError(f"Missing permissions: {missing}")
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """Get configuration value"""
        return self.context.config.get(key, default)
    
    def set_config(self, key: str, value: Any) -> None:
        """Set configuration value"""
        self.context.config[key] = value
    
    def log(self, level: str, message: str) -> None:
        """Log message with extension context"""
        log_func = getattr(self.context.logger, level.lower())
        log_func(f"[{self.context.extension_id}] {message}")
    
    def publish_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Publish event to system event bus"""
        self.context.event_bus.publish(event_type, {
            'extension_id': self.context.extension_id,
            'data': data
        })
    
    def get_storage(self, namespace: str) -> 'ExtensionStorage':
        """Get namespaced storage for extension"""
        return self.context.storage.get_namespace(namespace)
    
    def get_api_client(self) -> Any:
        """Get Schwab API client instance"""
        return self.context.api_client


class ExtensionStorage:
    """Persistent storage for extensions"""
    
    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.base_path.mkdir(parents=True, exist_ok=True)
    
    def get_namespace(self, namespace: str) -> 'ExtensionStorage':
        """Get namespaced storage"""
        namespace_path = self.base_path / namespace
        namespace_path.mkdir(exist_ok=True)
        return ExtensionStorage(namespace_path)
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get stored value"""
        file_path = self.base_path / f"{key}.json"
        if file_path.exists():
            try:
                with open(file_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load storage key {key}: {e}")
        return default
    
    def set(self, key: str, value: Any) -> None:
        """Set stored value"""
        file_path = self.base_path / f"{key}.json"
        try:
            with open(file_path, 'w') as f:
                json.dump(value, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save storage key {key}: {e}")
    
    def delete(self, key: str) -> None:
        """Delete stored value"""
        file_path = self.base_path / f"{key}.json"
        if file_path.exists():
            file_path.unlink()


class EventBus:
    """System-wide event bus for extensions"""
    
    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = {}
        self._lock = threading.RLock()
    
    def subscribe(self, event_type: str, handler: Callable) -> None:
        """Subscribe to event type"""
        with self._lock:
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            self._handlers[event_type].append(handler)
    
    def unsubscribe(self, event_type: str, handler: Callable) -> None:
        """Unsubscribe from event type"""
        with self._lock:
            if event_type in self._handlers:
                try:
                    self._handlers[event_type].remove(handler)
                except ValueError:
                    pass
    
    def publish(self, event_type: str, data: Dict[str, Any]) -> None:
        """Publish event to all subscribers"""
        with self._lock:
            handlers = self._handlers.get(event_type, [])
        
        for handler in handlers:
            try:
                handler(event_type, data)
            except Exception as e:
                logger.error(f"Error in event handler {handler}: {e}")


class ExtensionBase(ABC):
    """Base class for all extensions"""
    
    def __init__(self, api: ExtensionAPI):
        self.api = api
        self._active = False
    
    @abstractmethod
    def initialize(self) -> None:
        """Initialize the extension"""
        pass
    
    @abstractmethod
    def activate(self) -> None:
        """Activate the extension"""
        pass
    
    @abstractmethod
    def deactivate(self) -> None:
        """Deactivate the extension"""
        pass
    
    @abstractmethod
    def cleanup(self) -> None:
        """Clean up resources"""
        pass
    
    @property
    def is_active(self) -> bool:
        """Check if extension is active"""
        return self._active


class ExtensionManager:
    """Manages extension lifecycle and registration"""
    
    def __init__(self, extensions_path: Path, api_client: Any):
        self.extensions_path = Path(extensions_path)
        self.api_client = api_client
        self.event_bus = EventBus()
        self.storage = ExtensionStorage(self.extensions_path / "storage")
        
        # Extension registry
        self._extensions: Dict[str, 'ExtensionInstance'] = {}
        self._extension_classes: Dict[str, Type[ExtensionBase]] = {}
        self._metadata_cache: Dict[str, ExtensionMetadata] = {}
        
        # Security and validation
        self._allowed_permissions = {
            'read_market_data',
            'write_orders',
            'read_account',
            'write_config',
            'publish_events',
            'access_storage'
        }
        
        # Load extensions on startup
        self._load_extensions()
    
    def _load_extensions(self) -> None:
        """Load all available extensions"""
        if not self.extensions_path.exists():
            return
        
        for ext_dir in self.extensions_path.iterdir():
            if ext_dir.is_dir() and (ext_dir / "extension.yaml").exists():
                try:
                    self.load_extension(ext_dir.name)
                except Exception as e:
                    logger.error(f"Failed to load extension {ext_dir.name}: {e}")
    
    def load_extension(self, extension_id: str) -> 'ExtensionInstance':
        """Load an extension by ID"""
        ext_path = self.extensions_path / extension_id
        
        if not ext_path.exists():
            raise ExtensionLoadError(f"Extension {extension_id} not found")
        
        # Load metadata
        metadata = self._load_metadata(ext_path)
        
        # Validate dependencies
        self._validate_dependencies(metadata)
        
        # Load extension module
        extension_class = self._load_extension_module(ext_path, metadata)
        
        # Create extension instance
        instance = ExtensionInstance(
            extension_id=extension_id,
            metadata=metadata,
            extension_class=extension_class,
            manager=self
        )
        
        self._extensions[extension_id] = instance
        self._extension_classes[extension_id] = extension_class
        self._metadata_cache[extension_id] = metadata
        
        logger.info(f"Loaded extension: {extension_id} v{metadata.version}")
        return instance
    
    def _load_metadata(self, ext_path: Path) -> ExtensionMetadata:
        """Load extension metadata from YAML"""
        metadata_file = ext_path / "extension.yaml"
        
        if not metadata_file.exists():
            raise ExtensionLoadError("Missing extension.yaml")
        
        try:
            with open(metadata_file, 'r') as f:
                data = yaml.safe_load(f)
        except Exception as e:
            raise ExtensionLoadError(f"Invalid extension.yaml: {e}")
        
        # Validate required fields
        required_fields = ['name', 'version', 'author', 'description', 'type']
        for field in required_fields:
            if field not in data:
                raise ExtensionLoadError(f"Missing required field: {field}")
        
        # Create metadata object
        return ExtensionMetadata(
            name=data['name'],
            version=data['version'],
            author=data['author'],
            description=data['description'],
            extension_type=ExtensionType(data['type']),
            dependencies=data.get('dependencies', []),
            required_permissions=data.get('required_permissions', []),
            api_version=data.get('api_version', '1.0.0'),
            min_system_version=data.get('min_system_version', '1.0.0'),
            max_system_version=data.get('max_system_version', '*'),
            tags=data.get('tags', []),
            homepage=data.get('homepage'),
            repository=data.get('repository'),
            license=data.get('license')
        )
    
    def _validate_dependencies(self, metadata: ExtensionMetadata) -> None:
        """Validate extension dependencies"""
        for dep in metadata.dependencies:
            if dep not in self._extensions:
                raise ExtensionDependencyError(f"Missing dependency: {dep}")
    
    def _load_extension_module(self, ext_path: Path, metadata: ExtensionMetadata) -> Type[ExtensionBase]:
        """Load extension Python module"""
        # Look for main module file
        main_files = ['main.py', 'extension.py', f"{ext_path.name}.py"]
        main_file = None
        
        for file_name in main_files:
            file_path = ext_path / file_name
            if file_path.exists():
                main_file = file_path
                break
        
        if not main_file:
            raise ExtensionLoadError("No main module file found")
        
        # Load module
        spec = importlib.util.spec_from_file_location(
            f"extension_{metadata.name}",
            main_file
        )
        module = importlib.util.module_from_spec(spec)
        
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            raise ExtensionLoadError(f"Failed to load module: {e}")
        
        # Find extension class
        extension_class = None
        for name, obj in inspect.getmembers(module):
            # Check if it's a class that has the required methods of ExtensionBase
            if (inspect.isclass(obj) and 
                hasattr(obj, 'initialize') and 
                hasattr(obj, 'activate') and 
                hasattr(obj, 'deactivate') and 
                hasattr(obj, 'cleanup') and
                name != 'ExtensionBase' and
                name != 'ExtensionAPI'):
                extension_class = obj
                break
        
        if not extension_class:
            # Debug: print all classes in module
            classes = [name for name, obj in inspect.getmembers(module) if inspect.isclass(obj)]
            logger.error(f"No extension class found in module. Available classes: {classes}")
            raise ExtensionLoadError(f"No extension class found. Available classes: {classes}")
        
        return extension_class
    
    def unload_extension(self, extension_id: str) -> None:
        """Unload an extension"""
        if extension_id not in self._extensions:
            return
        
        instance = self._extensions[extension_id]
        instance.deactivate()
        instance.cleanup()
        
        del self._extensions[extension_id]
        del self._extension_classes[extension_id]
        del self._metadata_cache[extension_id]
        
        logger.info(f"Unloaded extension: {extension_id}")
    
    def reload_extension(self, extension_id: str) -> 'ExtensionInstance':
        """Reload an extension"""
        self.unload_extension(extension_id)
        return self.load_extension(extension_id)
    
    def get_extension(self, extension_id: str) -> Optional['ExtensionInstance']:
        """Get extension instance"""
        return self._extensions.get(extension_id)
    
    def list_extensions(self) -> List[Dict[str, Any]]:
        """List all extensions with status"""
        extensions = []
        for ext_id, instance in self._extensions.items():
            extensions.append({
                'id': ext_id,
                'name': instance.metadata.name,
                'version': instance.metadata.version,
                'type': instance.metadata.extension_type.value,
                'status': instance.status.value,
                'active': instance.is_active
            })
        return extensions
    
    def activate_extension(self, extension_id: str) -> None:
        """Activate an extension"""
        instance = self.get_extension(extension_id)
        if instance:
            instance.activate()
    
    def deactivate_extension(self, extension_id: str) -> None:
        """Deactivate an extension"""
        instance = self.get_extension(extension_id)
        if instance:
            instance.deactivate()


class ExtensionInstance:
    """Represents a loaded extension instance"""
    
    def __init__(self, extension_id: str, metadata: ExtensionMetadata, 
                 extension_class: Type[ExtensionBase], manager: ExtensionManager):
        self.extension_id = extension_id
        self.metadata = metadata
        self.extension_class = extension_class
        self.manager = manager
        
        self.status = ExtensionStatus.UNLOADED
        self._instance: Optional[ExtensionBase] = None
        self._context: Optional[ExtensionContext] = None
        self._logger: Optional[logging.Logger] = None
        
        # Initialize
        self._create_logger()
        self._create_context()
        self._create_instance()
    
    def _create_logger(self) -> None:
        """Create logger for extension"""
        self._logger = logging.getLogger(f"extension.{self.extension_id}")
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        self._logger.addHandler(handler)
        self._logger.setLevel(logging.INFO)
    
    def _create_context(self) -> None:
        """Create extension context"""
        # Validate permissions
        permissions = set()
        for perm in self.metadata.required_permissions:
            if perm in self.manager._allowed_permissions:
                permissions.add(perm)
            else:
                raise ExtensionSecurityError(f"Invalid permission: {perm}")
        
        self._context = ExtensionContext(
            extension_id=self.extension_id,
            metadata=self.metadata,
            config={},  # TODO: Load from config file
            logger=self._logger,
            api_client=self.manager.api_client,
            event_bus=self.manager.event_bus,
            storage=self.manager.storage.get_namespace(self.extension_id),
            permissions=permissions
        )
    
    def _create_instance(self) -> None:
        """Create extension instance"""
        try:
            api = ExtensionAPI(self._context)
            self._instance = self.extension_class(api)
            self.status = ExtensionStatus.LOADED
        except Exception as e:
            self.status = ExtensionStatus.ERROR
            logger.error(f"Failed to create extension instance: {e}")
            raise
    
    def initialize(self) -> None:
        """Initialize the extension"""
        if self.status != ExtensionStatus.LOADED:
            return
        
        try:
            self._instance.initialize()
            self.status = ExtensionStatus.ACTIVE
            # After initialization, also call activate
            if self._instance:
                self._instance.activate()
        except Exception as e:
            self.status = ExtensionStatus.ERROR
            logger.error(f"Failed to initialize extension: {e}")
            raise
    
    def activate(self) -> None:
        """Activate the extension"""
        if self.status == ExtensionStatus.LOADED:
            self.initialize()
            # After initialization, also call activate
            if self._instance:
                self._instance.activate()
        elif self.status == ExtensionStatus.ACTIVE:
            self._instance.activate()
    
    def deactivate(self) -> None:
        """Deactivate the extension"""
        if self._instance and self._instance.is_active:
            self._instance.deactivate()
    
    def cleanup(self) -> None:
        """Clean up extension resources"""
        if self._instance:
            try:
                self._instance.cleanup()
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")
    
    @property
    def is_active(self) -> bool:
        """Check if extension is active"""
        return (self._instance and 
                self.status == ExtensionStatus.ACTIVE and 
                self._instance.is_active)


# Decorators for extension registration
def extension(extension_type: ExtensionType, **metadata):
    """Decorator to register an extension"""
    def decorator(cls):
        if not issubclass(cls, ExtensionBase):
            raise ValueError("Extension must inherit from ExtensionBase")
        
        # Store metadata on class
        cls._extension_metadata = {
            'type': extension_type,
            **metadata
        }
        
        return cls
    return decorator


def requires_permission(permission: str):
    """Decorator to require a permission for a method"""
    def decorator(func):
        if not hasattr(func, '_required_permissions'):
            func._required_permissions = []
        func._required_permissions.append(permission)
        return func
    return decorator


# Extension marketplace integration
class ExtensionMarketplace:
    """Integration with extension marketplace"""
    
    def __init__(self, marketplace_url: str = "https://extensions.schwab-py.com"):
        self.marketplace_url = marketplace_url
    
    def search_extensions(self, query: str = "", 
                         extension_type: Optional[ExtensionType] = None,
                         tags: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Search for extensions in marketplace"""
        # TODO: Implement marketplace API integration
        return []
    
    def get_extension_info(self, extension_id: str) -> Optional[Dict[str, Any]]:
        """Get extension information from marketplace"""
        # TODO: Implement marketplace API integration
        return None
    
    def download_extension(self, extension_id: str, target_path: Path) -> bool:
        """Download extension from marketplace"""
        # TODO: Implement marketplace API integration
        return False


# Main extension framework interface
class ExtensionFramework:
    """Main interface for the extension framework"""
    
    def __init__(self, extensions_path: str = "extensions", 
                 api_client: Optional[Any] = None):
        self.extensions_path = Path(extensions_path)
        self.api_client = api_client
        self.manager = ExtensionManager(self.extensions_path, self.api_client)
        self.marketplace = ExtensionMarketplace()
    
    def load_extension(self, extension_id: str) -> ExtensionInstance:
        """Load an extension"""
        return self.manager.load_extension(extension_id)
    
    def unload_extension(self, extension_id: str) -> None:
        """Unload an extension"""
        self.manager.unload_extension(extension_id)
    
    def reload_extension(self, extension_id: str) -> ExtensionInstance:
        """Reload an extension"""
        return self.manager.reload_extension(extension_id)
    
    def activate_extension(self, extension_id: str) -> None:
        """Activate an extension"""
        self.manager.activate_extension(extension_id)
    
    def deactivate_extension(self, extension_id: str) -> None:
        """Deactivate an extension"""
        self.manager.deactivate_extension(extension_id)
    
    def list_extensions(self) -> List[Dict[str, Any]]:
        """List all extensions"""
        return self.manager.list_extensions()
    
    def get_extension(self, extension_id: str) -> Optional[ExtensionInstance]:
        """Get extension instance"""
        return self.manager.get_extension(extension_id)
    
    def search_marketplace(self, query: str = "", 
                          extension_type: Optional[ExtensionType] = None,
                          tags: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Search marketplace for extensions"""
        return self.marketplace.search_extensions(query, extension_type, tags)
    
    def install_from_marketplace(self, extension_id: str) -> bool:
        """Install extension from marketplace"""
        ext_path = self.extensions_path / extension_id
        if self.marketplace.download_extension(extension_id, ext_path):
            try:
                self.load_extension(extension_id)
                return True
            except Exception as e:
                logger.error(f"Failed to load installed extension: {e}")
                return False
        return False


# Global extension framework instance
_extension_framework: Optional[ExtensionFramework] = None


def get_extension_framework() -> ExtensionFramework:
    """Get global extension framework instance"""
    global _extension_framework
    if _extension_framework is None:
        _extension_framework = ExtensionFramework()
    return _extension_framework


def initialize_extension_framework(extensions_path: str = "extensions", 
                                 api_client: Optional[Any] = None) -> ExtensionFramework:
    """Initialize the extension framework"""
    global _extension_framework
    _extension_framework = ExtensionFramework(extensions_path, api_client)
    return _extension_framework 
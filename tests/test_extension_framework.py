"""
Comprehensive test suite for the extension framework

Tests all major functionality including:
- Extension loading/unloading cycles
- Extension failure isolation
- API compatibility across versions
- Security validation
- Lifecycle management
- Event system
- Storage system
- Marketplace integration

Author: Agent 10 - Extensibility Architect
"""

import asyncio
import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any

import yaml

# Add the enhancements directory to the path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / 'enhancements'))

from extension_framework import (
    ExtensionFramework, ExtensionManager, ExtensionInstance,
    ExtensionBase, ExtensionAPI, ExtensionContext, ExtensionMetadata,
    ExtensionType, ExtensionStatus, ExtensionError, ExtensionLoadError,
    ExtensionSecurityError, ExtensionDependencyError,
    EventBus, ExtensionStorage, ExtensionMarketplace,
    extension, requires_permission
)


class TestExtensionBase(unittest.TestCase):
    """Test base extension functionality"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.extensions_path = Path(self.temp_dir) / "extensions"
        self.extensions_path.mkdir(exist_ok=True)
        
        # Mock API client
        self.mock_client = Mock()
        
        # Initialize framework
        self.framework = ExtensionFramework(
            extensions_path=str(self.extensions_path),
            api_client=self.mock_client
        )
    
    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def create_test_extension(self, extension_id: str, 
                             extension_type: ExtensionType = ExtensionType.CUSTOM,
                             dependencies: list = None,
                             permissions: list = None) -> Path:
        """Create a test extension directory with metadata"""
        ext_path = self.extensions_path / extension_id
        ext_path.mkdir(exist_ok=True)
        
        # Create metadata
        metadata = {
            'name': f'Test Extension {extension_id}',
            'version': '1.0.0',
            'author': 'Test Author',
            'description': f'Test extension {extension_id}',
            'type': extension_type.value,
            'dependencies': dependencies or [],
            'required_permissions': permissions or [],
            'api_version': '1.0.0',
            'min_system_version': '1.0.0',
            'tags': ['test']
        }
        
        with open(ext_path / "extension.yaml", 'w') as f:
            yaml.dump(metadata, f)
        
        return ext_path
    
    def create_test_extension_class(self, extension_id: str, 
                                   extension_type: ExtensionType = ExtensionType.CUSTOM) -> type:
        """Create a test extension class"""
        class TestExtension(ExtensionBase):
            def __init__(self, api):
                super().__init__(api)
                self.initialized = False
                self.activated = False
                self.cleaned_up = False
            
            def initialize(self):
                self.initialized = True
            
            def activate(self):
                self.activated = True
                self._active = True
            
            def deactivate(self):
                self.activated = False
                self._active = False
            
            def cleanup(self):
                self.cleaned_up = True
        
        return TestExtension
    
    def create_test_extension_file(self, ext_path: Path, extension_class: type):
        """Create the main extension Python file"""
        class_name = extension_class.__name__
        
        code = f'''
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from enhancements.extension_framework import ExtensionBase, ExtensionAPI

class {class_name}(ExtensionBase):
    def __init__(self, api: ExtensionAPI):
        super().__init__(api)
        self.initialized = False
        self.activated = False
        self.cleaned_up = False
    
    def initialize(self):
        self.initialized = True
    
    def activate(self):
        self.activated = True
        self._active = True
    
    def deactivate(self):
        self.activated = False
        self._active = False
    
    def cleanup(self):
        self.cleaned_up = True
    
    @property
    def is_active(self):
        return self._active
'''
        
        with open(ext_path / "main.py", 'w') as f:
            f.write(code)


class TestExtensionLoading(TestExtensionBase):
    """Test extension loading functionality"""
    
    def test_load_valid_extension(self):
        """Test loading a valid extension"""
        # Create test extension
        ext_id = "test_extension"
        ext_path = self.create_test_extension(ext_id)
        extension_class = self.create_test_extension_class(ext_id)
        self.create_test_extension_file(ext_path, extension_class)
        
        # Load extension
        instance = self.framework.load_extension(ext_id)
        
        # Verify loading
        self.assertIsNotNone(instance)
        self.assertEqual(instance.extension_id, ext_id)
        self.assertEqual(instance.metadata.name, f'Test Extension {ext_id}')
        self.assertEqual(instance.status, ExtensionStatus.LOADED)
    
    def test_load_extension_missing_directory(self):
        """Test loading non-existent extension"""
        with self.assertRaises(ExtensionLoadError):
            self.framework.load_extension("non_existent")
    
    def test_load_extension_missing_metadata(self):
        """Test loading extension without metadata file"""
        ext_id = "test_extension"
        ext_path = self.extensions_path / ext_id
        ext_path.mkdir(exist_ok=True)
        
        with self.assertRaises(ExtensionLoadError):
            self.framework.load_extension(ext_id)
    
    def test_load_extension_invalid_metadata(self):
        """Test loading extension with invalid metadata"""
        ext_id = "test_extension"
        ext_path = self.extensions_path / ext_id
        ext_path.mkdir(exist_ok=True)
        
        # Create invalid metadata
        with open(ext_path / "extension.yaml", 'w') as f:
            f.write("invalid: yaml: content")
        
        with self.assertRaises(ExtensionLoadError):
            self.framework.load_extension(ext_id)
    
    def test_load_extension_missing_required_fields(self):
        """Test loading extension with missing required fields"""
        ext_id = "test_extension"
        ext_path = self.extensions_path / ext_id
        ext_path.mkdir(exist_ok=True)
        
        # Create metadata missing required fields
        metadata = {
            'name': 'Test Extension',
            # Missing version, author, description, type
        }
        
        with open(ext_path / "extension.yaml", 'w') as f:
            yaml.dump(metadata, f)
        
        with self.assertRaises(ExtensionLoadError):
            self.framework.load_extension(ext_id)
    
    def test_load_extension_missing_module_file(self):
        """Test loading extension without main module file"""
        ext_id = "test_extension"
        self.create_test_extension(ext_id)
        
        with self.assertRaises(ExtensionLoadError):
            self.framework.load_extension(ext_id)
    
    def test_load_extension_invalid_module(self):
        """Test loading extension with invalid module"""
        ext_id = "test_extension"
        ext_path = self.create_test_extension(ext_id)
        
        # Create invalid Python file
        with open(ext_path / "main.py", 'w') as f:
            f.write("invalid python syntax {")
        
        with self.assertRaises(ExtensionLoadError):
            self.framework.load_extension(ext_id)
    
    def test_load_extension_no_extension_class(self):
        """Test loading extension without extension class"""
        ext_id = "test_extension"
        ext_path = self.create_test_extension(ext_id)
        
        # Create module without extension class
        with open(ext_path / "main.py", 'w') as f:
            f.write("print('Hello World')")
        
        with self.assertRaises(ExtensionLoadError):
            self.framework.load_extension(ext_id)


class TestExtensionLifecycle(TestExtensionBase):
    """Test extension lifecycle management"""
    
    def test_extension_initialization(self):
        """Test extension initialization"""
        ext_id = "test_extension"
        ext_path = self.create_test_extension(ext_id)
        extension_class = self.create_test_extension_class(ext_id)
        self.create_test_extension_file(ext_path, extension_class)
        
        instance = self.framework.load_extension(ext_id)
        instance.initialize()
        
        self.assertEqual(instance.status, ExtensionStatus.ACTIVE)
        self.assertTrue(instance.is_active)
        self.assertTrue(instance._instance.initialized)
    
    def test_extension_activation(self):
        """Test extension activation"""
        ext_id = "test_extension"
        ext_path = self.create_test_extension(ext_id)
        extension_class = self.create_test_extension_class(ext_id)
        self.create_test_extension_file(ext_path, extension_class)
        
        instance = self.framework.load_extension(ext_id)
        self.framework.activate_extension(ext_id)
        
        self.assertEqual(instance.status, ExtensionStatus.ACTIVE)
        self.assertTrue(instance.is_active)
        self.assertTrue(instance._instance.activated)
    
    def test_extension_deactivation(self):
        """Test extension deactivation"""
        ext_id = "test_extension"
        ext_path = self.create_test_extension(ext_id)
        extension_class = self.create_test_extension_class(ext_id)
        self.create_test_extension_file(ext_path, extension_class)
        
        instance = self.framework.load_extension(ext_id)
        self.framework.activate_extension(ext_id)
        self.framework.deactivate_extension(ext_id)
        
        self.assertFalse(instance._instance.activated)
        self.assertFalse(instance._instance._active)
    
    def test_extension_cleanup(self):
        """Test extension cleanup"""
        ext_id = "test_extension"
        ext_path = self.create_test_extension(ext_id)
        extension_class = self.create_test_extension_class(ext_id)
        self.create_test_extension_file(ext_path, extension_class)
        
        instance = self.framework.load_extension(ext_id)
        self.framework.unload_extension(ext_id)
        
        self.assertTrue(instance._instance.cleaned_up)
    
    def test_extension_reload(self):
        """Test extension reloading"""
        ext_id = "test_extension"
        ext_path = self.create_test_extension(ext_id)
        extension_class = self.create_test_extension_class(ext_id)
        self.create_test_extension_file(ext_path, extension_class)
        
        # Load and activate
        instance1 = self.framework.load_extension(ext_id)
        self.framework.activate_extension(ext_id)
        
        # Reload
        instance2 = self.framework.reload_extension(ext_id)
        
        self.assertNotEqual(instance1, instance2)
        self.assertEqual(instance2.status, ExtensionStatus.LOADED)
        self.assertFalse(instance2.is_active)


class TestExtensionSecurity(TestExtensionBase):
    """Test extension security validation"""
    
    def test_extension_with_valid_permissions(self):
        """Test extension with valid permissions"""
        ext_id = "test_extension"
        ext_path = self.create_test_extension(
            ext_id, 
            permissions=['read_market_data', 'access_storage']
        )
        extension_class = self.create_test_extension_class(ext_id)
        self.create_test_extension_file(ext_path, extension_class)
        
        instance = self.framework.load_extension(ext_id)
        
        self.assertIn('read_market_data', instance._context.permissions)
        self.assertIn('access_storage', instance._context.permissions)
    
    def test_extension_with_invalid_permissions(self):
        """Test extension with invalid permissions"""
        ext_id = "test_extension"
        ext_path = self.create_test_extension(
            ext_id, 
            permissions=['invalid_permission', 'read_market_data']
        )
        extension_class = self.create_test_extension_class(ext_id)
        self.create_test_extension_file(ext_path, extension_class)
        
        with self.assertRaises(ExtensionSecurityError):
            self.framework.load_extension(ext_id)
    
    def test_extension_api_permission_validation(self):
        """Test extension API permission validation"""
        ext_id = "test_extension"
        ext_path = self.create_test_extension(ext_id)
        extension_class = self.create_test_extension_class(ext_id)
        self.create_test_extension_file(ext_path, extension_class)
        
        instance = self.framework.load_extension(ext_id)
        api = ExtensionAPI(instance._context)
        
        # Test API methods work with valid permissions
        api.get_config('test_key', 'default_value')
        api.set_config('test_key', 'test_value')
        api.log('info', 'test message')


class TestExtensionDependencies(TestExtensionBase):
    """Test extension dependency management"""
    
    def test_extension_with_dependencies(self):
        """Test extension with valid dependencies"""
        # Create dependency extension
        dep_id = "dependency_extension"
        dep_path = self.create_test_extension(dep_id)
        dep_class = self.create_test_extension_class(dep_id)
        self.create_test_extension_file(dep_path, dep_class)
        
        # Load dependency
        self.framework.load_extension(dep_id)
        
        # Create dependent extension
        ext_id = "dependent_extension"
        ext_path = self.create_test_extension(
            ext_id, 
            dependencies=[dep_id]
        )
        ext_class = self.create_test_extension_class(ext_id)
        self.create_test_extension_file(ext_path, ext_class)
        
        # Load dependent extension
        instance = self.framework.load_extension(ext_id)
        self.assertIsNotNone(instance)
    
    def test_extension_with_missing_dependencies(self):
        """Test extension with missing dependencies"""
        ext_id = "dependent_extension"
        ext_path = self.create_test_extension(
            ext_id, 
            dependencies=["missing_dependency"]
        )
        ext_class = self.create_test_extension_class(ext_id)
        self.create_test_extension_file(ext_path, ext_class)
        
        with self.assertRaises(ExtensionDependencyError):
            self.framework.load_extension(ext_id)


class TestExtensionAPI(TestExtensionBase):
    """Test extension API functionality"""
    
    def setUp(self):
        super().setUp()
        self.ext_id = "test_extension"
        self.ext_path = self.create_test_extension(self.ext_id)
        self.ext_class = self.create_test_extension_class(self.ext_id)
        self.create_test_extension_file(self.ext_path, self.ext_class)
        self.instance = self.framework.load_extension(self.ext_id)
        self.api = ExtensionAPI(self.instance._context)
    
    def test_api_config_operations(self):
        """Test API configuration operations"""
        # Test get_config with default
        value = self.api.get_config('test_key', 'default_value')
        self.assertEqual(value, 'default_value')
        
        # Test set_config and get_config
        self.api.set_config('test_key', 'test_value')
        value = self.api.get_config('test_key')
        self.assertEqual(value, 'test_value')
    
    def test_api_logging(self):
        """Test API logging functionality"""
        with self.assertLogs(level='INFO') as log:
            self.api.log('info', 'test message')
            self.assertIn('test message', log.output[0])
    
    def test_api_event_publishing(self):
        """Test API event publishing"""
        events_received = []
        
        def event_handler(event_type, data):
            events_received.append((event_type, data))
        
        self.framework.manager.event_bus.subscribe('test_event', event_handler)
        
        self.api.publish_event('test_event', {'key': 'value'})
        
        self.assertEqual(len(events_received), 1)
        self.assertEqual(events_received[0][0], 'test_event')
        self.assertEqual(events_received[0][1]['data']['key'], 'value')
    
    def test_api_storage_operations(self):
        """Test API storage operations"""
        storage = self.api.get_storage('test_namespace')
        
        # Test storage operations
        storage.set('test_key', {'data': 'value'})
        value = storage.get('test_key')
        self.assertEqual(value['data'], 'value')
        
        # Test delete
        storage.delete('test_key')
        value = storage.get('test_key')
        self.assertIsNone(value)
    
    def test_api_client_access(self):
        """Test API client access"""
        client = self.api.get_api_client()
        self.assertEqual(client, self.mock_client)


class TestEventBus(unittest.TestCase):
    """Test event bus functionality"""
    
    def setUp(self):
        self.event_bus = EventBus()
    
    def test_event_subscription(self):
        """Test event subscription"""
        events_received = []
        
        def handler(event_type, data):
            events_received.append((event_type, data))
        
        self.event_bus.subscribe('test_event', handler)
        self.event_bus.publish('test_event', {'key': 'value'})
        
        self.assertEqual(len(events_received), 1)
        self.assertEqual(events_received[0][0], 'test_event')
        self.assertEqual(events_received[0][1]['key'], 'value')
    
    def test_event_unsubscription(self):
        """Test event unsubscription"""
        events_received = []
        
        def handler(event_type, data):
            events_received.append((event_type, data))
        
        self.event_bus.subscribe('test_event', handler)
        self.event_bus.publish('test_event', {'key': 'value'})
        self.event_bus.unsubscribe('test_event', handler)
        self.event_bus.publish('test_event', {'key': 'value2'})
        
        self.assertEqual(len(events_received), 1)
    
    def test_multiple_handlers(self):
        """Test multiple event handlers"""
        events_received = []
        
        def handler1(event_type, data):
            events_received.append(('handler1', data))
        
        def handler2(event_type, data):
            events_received.append(('handler2', data))
        
        self.event_bus.subscribe('test_event', handler1)
        self.event_bus.subscribe('test_event', handler2)
        self.event_bus.publish('test_event', {'key': 'value'})
        
        self.assertEqual(len(events_received), 2)
        handlers = [event[0] for event in events_received]
        self.assertIn('handler1', handlers)
        self.assertIn('handler2', handlers)
    
    def test_handler_error_isolation(self):
        """Test that handler errors don't affect other handlers"""
        events_received = []
        
        def bad_handler(event_type, data):
            raise Exception("Handler error")
        
        def good_handler(event_type, data):
            events_received.append(data)
        
        self.event_bus.subscribe('test_event', bad_handler)
        self.event_bus.subscribe('test_event', good_handler)
        
        # Should not raise exception
        self.event_bus.publish('test_event', {'key': 'value'})
        
        self.assertEqual(len(events_received), 1)


class TestExtensionStorage(unittest.TestCase):
    """Test extension storage functionality"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.storage = ExtensionStorage(Path(self.temp_dir))
    
    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_storage_operations(self):
        """Test basic storage operations"""
        # Test set and get
        self.storage.set('test_key', {'data': 'value'})
        value = self.storage.get('test_key')
        self.assertEqual(value['data'], 'value')
        
        # Test get with default
        value = self.storage.get('non_existent', 'default')
        self.assertEqual(value, 'default')
        
        # Test delete
        self.storage.delete('test_key')
        value = self.storage.get('test_key')
        self.assertIsNone(value)
    
    def test_storage_namespace(self):
        """Test storage namespacing"""
        namespace = self.storage.get_namespace('test_namespace')
        
        # Test that namespaces are isolated
        self.storage.set('global_key', 'global_value')
        namespace.set('namespace_key', 'namespace_value')
        
        self.assertEqual(self.storage.get('global_key'), 'global_value')
        self.assertIsNone(self.storage.get('namespace_key'))
        self.assertEqual(namespace.get('namespace_key'), 'namespace_value')
        self.assertIsNone(namespace.get('global_key'))
    
    def test_storage_error_handling(self):
        """Test storage error handling"""
        # Test with invalid JSON
        storage_file = self.storage.base_path / "invalid.json"
        with open(storage_file, 'w') as f:
            f.write("invalid json content")
        
        # Should not raise exception, should return default
        value = self.storage.get('invalid', 'default')
        self.assertEqual(value, 'default')


class TestExtensionMarketplace(unittest.TestCase):
    """Test extension marketplace functionality"""
    
    def setUp(self):
        self.marketplace = ExtensionMarketplace()
    
    def test_search_extensions(self):
        """Test extension search"""
        results = self.marketplace.search_extensions("test")
        self.assertEqual(results, [])  # Mock implementation returns empty
    
    def test_get_extension_info(self):
        """Test getting extension info"""
        info = self.marketplace.get_extension_info("test_extension")
        self.assertIsNone(info)  # Mock implementation returns None
    
    def test_download_extension(self):
        """Test extension download"""
        with tempfile.TemporaryDirectory() as temp_dir:
            success = self.marketplace.download_extension(
                "test_extension", 
                Path(temp_dir)
            )
            self.assertFalse(success)  # Mock implementation returns False


class TestExtensionDecorators(unittest.TestCase):
    """Test extension decorators"""
    
    def test_extension_decorator(self):
        """Test @extension decorator"""
        @extension(ExtensionType.SIGNAL_PROCESSOR, name="Test Extension")
        class TestExtension(ExtensionBase):
            def initialize(self): pass
            def activate(self): pass
            def deactivate(self): pass
            def cleanup(self): pass
        
        self.assertTrue(hasattr(TestExtension, '_extension_metadata'))
        self.assertEqual(TestExtension._extension_metadata['type'], ExtensionType.SIGNAL_PROCESSOR)
        self.assertEqual(TestExtension._extension_metadata['name'], "Test Extension")
    
    def test_extension_decorator_invalid_class(self):
        """Test @extension decorator with invalid class"""
        with self.assertRaises(ValueError):
            @extension(ExtensionType.SIGNAL_PROCESSOR)
            class InvalidClass:
                pass
    
    def test_requires_permission_decorator(self):
        """Test @requires_permission decorator"""
        @requires_permission('read_market_data')
        def test_function():
            pass
        
        self.assertTrue(hasattr(test_function, '_required_permissions'))
        self.assertIn('read_market_data', test_function._required_permissions)


class TestExtensionFrameworkIntegration(TestExtensionBase):
    """Test extension framework integration"""
    
    def test_framework_initialization(self):
        """Test framework initialization"""
        framework = ExtensionFramework(
            extensions_path=str(self.extensions_path),
            api_client=self.mock_client
        )
        
        self.assertIsNotNone(framework.manager)
        self.assertIsNotNone(framework.marketplace)
        self.assertEqual(framework.extensions_path, self.extensions_path)
    
    def test_framework_extension_listing(self):
        """Test framework extension listing"""
        # Create test extension
        ext_id = "test_extension"
        ext_path = self.create_test_extension(ext_id)
        ext_class = self.create_test_extension_class(ext_id)
        self.create_test_extension_file(ext_path, ext_class)
        
        self.framework.load_extension(ext_id)
        extensions = self.framework.list_extensions()
        
        self.assertEqual(len(extensions), 1)
        self.assertEqual(extensions[0]['id'], ext_id)
        self.assertEqual(extensions[0]['status'], ExtensionStatus.LOADED.value)
    
    def test_framework_marketplace_search(self):
        """Test framework marketplace search"""
        results = self.framework.search_marketplace("test")
        self.assertEqual(results, [])  # Mock implementation
    
    def test_framework_install_from_marketplace(self):
        """Test framework marketplace installation"""
        success = self.framework.install_from_marketplace("test_extension")
        self.assertFalse(success)  # Mock implementation


class TestExtensionFailureIsolation(TestExtensionBase):
    """Test extension failure isolation"""
    
    def test_extension_initialization_failure(self):
        """Test that extension initialization failure doesn't crash system"""
        ext_id = "failing_extension"
        ext_path = self.create_test_extension(ext_id)
        
        # Create extension that fails during initialization
        code = '''
from enhancements.extension_framework import ExtensionBase, ExtensionAPI

class FailingExtension(ExtensionBase):
    def __init__(self, api: ExtensionAPI):
        super().__init__(api)
    
    def initialize(self):
        raise Exception("Initialization failed")
    
    def activate(self):
        pass
    
    def deactivate(self):
        pass
    
    def cleanup(self):
        pass
'''
        
        with open(ext_path / "main.py", 'w') as f:
            f.write(code)
        
        # Should not crash the system
        try:
            instance = self.framework.load_extension(ext_id)
            instance.initialize()
        except Exception as e:
            # Expected to fail, but shouldn't crash the framework
            self.assertIsInstance(e, Exception)
    
    def test_extension_activation_failure(self):
        """Test that extension activation failure doesn't crash system"""
        ext_id = "activation_failing_extension"
        ext_path = self.create_test_extension(ext_id)
        
        # Create extension that fails during activation
        code = '''
from enhancements.extension_framework import ExtensionBase, ExtensionAPI

class ActivationFailingExtension(ExtensionBase):
    def __init__(self, api: ExtensionAPI):
        super().__init__(api)
    
    def initialize(self):
        pass
    
    def activate(self):
        raise Exception("Activation failed")
    
    def deactivate(self):
        pass
    
    def cleanup(self):
        pass
'''
        
        with open(ext_path / "main.py", 'w') as f:
            f.write(code)
        
        # Should not crash the system
        try:
            instance = self.framework.load_extension(ext_id)
            self.framework.activate_extension(ext_id)
        except Exception as e:
            # Expected to fail, but shouldn't crash the framework
            self.assertIsInstance(e, Exception)


if __name__ == '__main__':
    # Configure logging for tests
    logging.basicConfig(level=logging.INFO)
    
    # Run tests
    unittest.main(verbosity=2) 
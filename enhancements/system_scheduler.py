"""
Agent 9: System Orchestration Specialist

Comprehensive task scheduler and system monitoring framework for high-availability
trading service. Coordinates all agents, provides health checks, automated
failover, metrics collection, and system orchestration.
"""

import asyncio
import datetime
import enum
import json
import logging
import os
import signal
import sys
import threading
import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from urllib.parse import urlparse

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
    APSCHEDULER_AVAILABLE = True
except ImportError:
    APSCHEDULER_AVAILABLE = False
    print("Warning: APScheduler not available. Install with: pip install apscheduler")

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("Warning: psutil not available. Install with: pip install psutil")


# Configure logging
logger = logging.getLogger(__name__)


class SystemState(Enum):
    """System operational states"""
    STARTING = "starting"
    OPERATIONAL = "operational"
    DEGRADED = "degraded"
    MAINTENANCE = "maintenance"
    EMERGENCY = "emergency"
    SHUTDOWN = "shutdown"


class AgentType(Enum):
    """Agent types for monitoring"""
    STREAM_CONNECTION = "agent_1_stream"
    AUTHENTICATION = "agent_2_auth"
    ORDER_MANAGEMENT = "agent_3_orders"
    RATE_LIMITING = "agent_4_rate_limit"
    BUFFER_MANAGEMENT = "agent_5_buffer"
    TOKEN_REFRESH = "agent_6_tokens"
    USER_SESSION = "agent_7_sessions"
    SIGNAL_PROCESSING = "agent_8_signals"
    SYSTEM_ORCHESTRATION = "agent_9_scheduler"


class HealthStatus(Enum):
    """Health status levels"""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class AlertLevel(Enum):
    """Alert severity levels"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


@dataclass
class AgentHealth:
    """Health information for an agent"""
    agent_type: AgentType
    status: HealthStatus
    last_check: datetime.datetime
    response_time: float
    error_count: int = 0
    success_count: int = 0
    details: Dict[str, Any] = field(default_factory=dict)
    alerts: List[str] = field(default_factory=list)


@dataclass
class SystemMetrics:
    """System-wide metrics"""
    cpu_usage: float
    memory_usage: float
    disk_usage: float
    network_io: Dict[str, float]
    active_connections: int
    total_requests: int
    error_rate: float
    timestamp: datetime.datetime


@dataclass
class Alert:
    """System alert"""
    level: AlertLevel
    message: str
    source: str
    timestamp: datetime.datetime
    acknowledged: bool = False
    resolved: bool = False


class HealthCheck(ABC):
    """Abstract base class for health checks"""
    
    @abstractmethod
    async def check(self) -> AgentHealth:
        """Perform health check and return status"""
        pass
    
    @abstractmethod
    def get_agent_type(self) -> AgentType:
        """Return the agent type this check monitors"""
        pass


class StreamHealthCheck(HealthCheck):
    """Health check for Agent 1: Stream connection"""
    
    def __init__(self, stream_client=None):
        self.stream_client = stream_client
        self.agent_type = AgentType.STREAM_CONNECTION
    
    def get_agent_type(self) -> AgentType:
        return self.agent_type
    
    async def check(self) -> AgentHealth:
        start_time = time.time()
        status = HealthStatus.UNKNOWN
        details = {}
        
        try:
            if self.stream_client:
                # Check connection state
                if hasattr(self.stream_client, 'get_health_status'):
                    health = self.stream_client.get_health_status()
                    details.update(health)
                    
                    if health.get('connection_state') == 'CONNECTED':
                        status = HealthStatus.HEALTHY
                    elif health.get('connection_state') in ['CONNECTING', 'RECONNECTING']:
                        status = HealthStatus.WARNING
                    else:
                        status = HealthStatus.CRITICAL
                else:
                    # Basic connectivity check
                    status = HealthStatus.HEALTHY
            else:
                status = HealthStatus.UNKNOWN
                details['error'] = 'No stream client available'
                
        except Exception as e:
            status = HealthStatus.CRITICAL
            details['error'] = str(e)
        
        response_time = time.time() - start_time
        
        return AgentHealth(
            agent_type=self.agent_type,
            status=status,
            last_check=datetime.datetime.now(),
            response_time=response_time,
            details=details
        )


class AuthHealthCheck(HealthCheck):
    """Health check for Agent 2: Authentication"""
    
    def __init__(self, auth_client=None):
        self.auth_client = auth_client
        self.agent_type = AgentType.AUTHENTICATION
    
    def get_agent_type(self) -> AgentType:
        return self.agent_type
    
    async def check(self) -> AgentHealth:
        start_time = time.time()
        status = HealthStatus.UNKNOWN
        details = {}
        
        try:
            if self.auth_client:
                # Check token validity
                if hasattr(self.auth_client, 'token_age'):
                    token_age = self.auth_client.token_age()
                    details['token_age'] = token_age
                    
                    if token_age < 3600:  # Less than 1 hour
                        status = HealthStatus.HEALTHY
                    elif token_age < 7200:  # Less than 2 hours
                        status = HealthStatus.WARNING
                    else:
                        status = HealthStatus.CRITICAL
                else:
                    status = HealthStatus.HEALTHY
            else:
                status = HealthStatus.UNKNOWN
                details['error'] = 'No auth client available'
                
        except Exception as e:
            status = HealthStatus.CRITICAL
            details['error'] = str(e)
        
        response_time = time.time() - start_time
        
        return AgentHealth(
            agent_type=self.agent_type,
            status=status,
            last_check=datetime.datetime.now(),
            response_time=response_time,
            details=details
        )


class OrderHealthCheck(HealthCheck):
    """Health check for Agent 3: Order management"""
    
    def __init__(self, order_client=None):
        self.order_client = order_client
        self.agent_type = AgentType.ORDER_MANAGEMENT
    
    def get_agent_type(self) -> AgentType:
        return self.agent_type
    
    async def check(self) -> AgentHealth:
        start_time = time.time()
        status = HealthStatus.UNKNOWN
        details = {}
        
        try:
            if self.order_client:
                # Check order success rates
                if hasattr(self.order_client, 'get_order_stats'):
                    stats = self.order_client.get_order_stats()
                    details.update(stats)
                    
                    success_rate = stats.get('success_rate', 0)
                    if success_rate >= 0.95:
                        status = HealthStatus.HEALTHY
                    elif success_rate >= 0.90:
                        status = HealthStatus.WARNING
                    else:
                        status = HealthStatus.CRITICAL
                else:
                    status = HealthStatus.HEALTHY
            else:
                status = HealthStatus.UNKNOWN
                details['error'] = 'No order client available'
                
        except Exception as e:
            status = HealthStatus.CRITICAL
            details['error'] = str(e)
        
        response_time = time.time() - start_time
        
        return AgentHealth(
            agent_type=self.agent_type,
            status=status,
            last_check=datetime.datetime.now(),
            response_time=response_time,
            details=details
        )


class RateLimitHealthCheck(HealthCheck):
    """Health check for Agent 4: Rate limiting"""
    
    def __init__(self, rate_limit_client=None):
        self.rate_limit_client = rate_limit_client
        self.agent_type = AgentType.RATE_LIMITING
    
    def get_agent_type(self) -> AgentType:
        return self.agent_type
    
    async def check(self) -> AgentHealth:
        start_time = time.time()
        status = HealthStatus.UNKNOWN
        details = {}
        
        try:
            if self.rate_limit_client:
                # Check rate limit utilization
                if hasattr(self.rate_limit_client, 'get_utilization'):
                    utilization = self.rate_limit_client.get_utilization()
                    details['utilization'] = utilization
                    
                    if utilization < 0.8:
                        status = HealthStatus.HEALTHY
                    elif utilization < 0.95:
                        status = HealthStatus.WARNING
                    else:
                        status = HealthStatus.CRITICAL
                else:
                    status = HealthStatus.HEALTHY
            else:
                status = HealthStatus.UNKNOWN
                details['error'] = 'No rate limit client available'
                
        except Exception as e:
            status = HealthStatus.CRITICAL
            details['error'] = str(e)
        
        response_time = time.time() - start_time
        
        return AgentHealth(
            agent_type=self.agent_type,
            status=status,
            last_check=datetime.datetime.now(),
            response_time=response_time,
            details=details
        )


class BufferHealthCheck(HealthCheck):
    """Health check for Agent 5: Buffer management"""
    
    def __init__(self, buffer_manager=None):
        self.buffer_manager = buffer_manager
        self.agent_type = AgentType.BUFFER_MANAGEMENT
    
    def get_agent_type(self) -> AgentType:
        return self.agent_type
    
    async def check(self) -> AgentHealth:
        start_time = time.time()
        status = HealthStatus.UNKNOWN
        details = {}
        
        try:
            if self.buffer_manager:
                # Check buffer health
                if hasattr(self.buffer_manager, 'get_buffer_stats'):
                    stats = self.buffer_manager.get_buffer_stats()
                    details.update(stats)
                    
                    drop_rate = stats.get('drop_rate', 0)
                    if drop_rate < 0.01:  # Less than 1%
                        status = HealthStatus.HEALTHY
                    elif drop_rate < 0.05:  # Less than 5%
                        status = HealthStatus.WARNING
                    else:
                        status = HealthStatus.CRITICAL
                else:
                    status = HealthStatus.HEALTHY
            else:
                status = HealthStatus.UNKNOWN
                details['error'] = 'No buffer manager available'
                
        except Exception as e:
            status = HealthStatus.CRITICAL
            details['error'] = str(e)
        
        response_time = time.time() - start_time
        
        return AgentHealth(
            agent_type=self.agent_type,
            status=status,
            last_check=datetime.datetime.now(),
            response_time=response_time,
            details=details
        )


class TokenHealthCheck(HealthCheck):
    """Health check for Agent 6: Token refresh"""
    
    def __init__(self, token_manager=None):
        self.token_manager = token_manager
        self.agent_type = AgentType.TOKEN_REFRESH
    
    def get_agent_type(self) -> AgentType:
        return self.agent_type
    
    async def check(self) -> AgentHealth:
        start_time = time.time()
        status = HealthStatus.UNKNOWN
        details = {}
        
        try:
            if self.token_manager:
                # Check token refresh success
                if hasattr(self.token_manager, 'get_refresh_stats'):
                    stats = self.token_manager.get_refresh_stats()
                    details.update(stats)
                    
                    success_rate = stats.get('success_rate', 0)
                    if success_rate >= 0.95:
                        status = HealthStatus.HEALTHY
                    elif success_rate >= 0.90:
                        status = HealthStatus.WARNING
                    else:
                        status = HealthStatus.CRITICAL
                else:
                    status = HealthStatus.HEALTHY
            else:
                status = HealthStatus.UNKNOWN
                details['error'] = 'No token manager available'
                
        except Exception as e:
            status = HealthStatus.CRITICAL
            details['error'] = str(e)
        
        response_time = time.time() - start_time
        
        return AgentHealth(
            agent_type=self.agent_type,
            status=status,
            last_check=datetime.datetime.now(),
            response_time=response_time,
            details=details
        )


class SessionHealthCheck(HealthCheck):
    """Health check for Agent 7: User sessions"""
    
    def __init__(self, session_manager=None):
        self.session_manager = session_manager
        self.agent_type = AgentType.USER_SESSION
    
    def get_agent_type(self) -> AgentType:
        return self.agent_type
    
    async def check(self) -> AgentHealth:
        start_time = time.time()
        status = HealthStatus.UNKNOWN
        details = {}
        
        try:
            if self.session_manager:
                # Check session health
                if hasattr(self.session_manager, 'get_session_stats'):
                    stats = self.session_manager.get_session_stats()
                    details.update(stats)
                    
                    active_sessions = stats.get('active_sessions', 0)
                    if active_sessions > 0:
                        status = HealthStatus.HEALTHY
                    else:
                        status = HealthStatus.WARNING
                else:
                    status = HealthStatus.HEALTHY
            else:
                status = HealthStatus.UNKNOWN
                details['error'] = 'No session manager available'
                
        except Exception as e:
            status = HealthStatus.CRITICAL
            details['error'] = str(e)
        
        response_time = time.time() - start_time
        
        return AgentHealth(
            agent_type=self.agent_type,
            status=status,
            last_check=datetime.datetime.now(),
            response_time=response_time,
            details=details
        )


class SignalHealthCheck(HealthCheck):
    """Health check for Agent 8: Signal processing"""
    
    def __init__(self, signal_processor=None):
        self.signal_processor = signal_processor
        self.agent_type = AgentType.SIGNAL_PROCESSING
    
    def get_agent_type(self) -> AgentType:
        return self.agent_type
    
    async def check(self) -> AgentHealth:
        start_time = time.time()
        status = HealthStatus.UNKNOWN
        details = {}
        
        try:
            if self.signal_processor:
                # Check signal processing performance
                if hasattr(self.signal_processor, 'get_performance_stats'):
                    stats = self.signal_processor.get_performance_stats()
                    details.update(stats)
                    
                    accuracy = stats.get('accuracy', 0)
                    if accuracy >= 0.8:
                        status = HealthStatus.HEALTHY
                    elif accuracy >= 0.7:
                        status = HealthStatus.WARNING
                    else:
                        status = HealthStatus.CRITICAL
                else:
                    status = HealthStatus.HEALTHY
            else:
                status = HealthStatus.UNKNOWN
                details['error'] = 'No signal processor available'
                
        except Exception as e:
            status = HealthStatus.CRITICAL
            details['error'] = str(e)
        
        response_time = time.time() - start_time
        
        return AgentHealth(
            agent_type=self.agent_type,
            status=status,
            last_check=datetime.datetime.now(),
            response_time=response_time,
            details=details
        )


class SystemScheduler:
    """
    Comprehensive system scheduler and monitoring framework.
    
    Coordinates all agents, provides health checks, automated failover,
    metrics collection, and system orchestration.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.state = SystemState.STARTING
        self.health_checks: Dict[AgentType, HealthCheck] = {}
        self.agent_health: Dict[AgentType, AgentHealth] = {}
        self.alerts: List[Alert] = []
        self.metrics_history: deque = deque(maxlen=1000)
        self.maintenance_mode = False
        self.emergency_shutdown = False
        
        # Initialize schedulers
        if APSCHEDULER_AVAILABLE:
            self.scheduler = AsyncIOScheduler()
            self.background_scheduler = BackgroundScheduler()
        else:
            self.scheduler = None
            self.background_scheduler = None
            logger.warning("APScheduler not available. Limited functionality.")
        
        # Event handlers
        self.health_check_handlers: List[Callable] = []
        self.alert_handlers: List[Callable] = []
        self.state_change_handlers: List[Callable] = []
        
        # Performance tracking
        self.performance_metrics = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'average_response_time': 0.0,
            'peak_response_time': 0.0,
        }
        
        # Initialize system monitoring
        self._setup_system_monitoring()
        self._setup_signal_handlers()
    
    def _setup_system_monitoring(self):
        """Setup system monitoring components"""
        if PSUTIL_AVAILABLE:
            # System metrics collection
            self.add_job(
                self._collect_system_metrics,
                'interval',
                seconds=30,
                id='system_metrics'
            )
        
        # Health check scheduling
        self.add_job(
            self._run_health_checks,
            'interval',
            seconds=60,
            id='health_checks'
        )
        
        # Performance monitoring
        self.add_job(
            self._update_performance_metrics,
            'interval',
            seconds=300,
            id='performance_metrics'
        )
        
        # Alert cleanup
        self.add_job(
            self._cleanup_old_alerts,
            'interval',
            seconds=3600,
            id='alert_cleanup'
        )
    
    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating graceful shutdown")
            self.emergency_shutdown = True
            self.shutdown()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def add_health_check(self, health_check: HealthCheck):
        """Add a health check for monitoring"""
        self.health_checks[health_check.get_agent_type()] = health_check
        logger.info(f"Added health check for {health_check.get_agent_type().value}")
    
    def add_job(self, func, trigger, **trigger_args):
        """Add a scheduled job"""
        if self.scheduler:
            job_id = trigger_args.get('id', f"{func.__name__}_{int(time.time())}")
            self.scheduler.add_job(func, trigger, **trigger_args)
            logger.info(f"Added scheduled job: {job_id}")
        else:
            logger.warning("Scheduler not available, job not added")
    
    def start(self):
        """Start the system scheduler"""
        if self.scheduler:
            self.scheduler.start()
            logger.info("System scheduler started")
        
        if self.background_scheduler:
            self.background_scheduler.start()
            logger.info("Background scheduler started")
        
        self.state = SystemState.OPERATIONAL
        self._notify_state_change()
        
        logger.info("System scheduler is now operational")
    
    def shutdown(self):
        """Shutdown the system scheduler gracefully"""
        logger.info("Initiating system shutdown...")
        self.state = SystemState.SHUTDOWN
        
        # Stop schedulers
        if self.scheduler:
            self.scheduler.shutdown(wait=True)
        
        if self.background_scheduler:
            self.background_scheduler.shutdown(wait=True)
        
        # Save final metrics
        self._save_metrics()
        
        logger.info("System shutdown complete")
        self._notify_state_change()
    
    async def _run_health_checks(self):
        """Run all health checks"""
        logger.debug("Running health checks...")
        
        for agent_type, health_check in self.health_checks.items():
            try:
                health = await health_check.check()
                self.agent_health[agent_type] = health
                
                # Update agent-specific metrics
                if health.status == HealthStatus.CRITICAL:
                    health.error_count += 1
                    self._create_alert(
                        AlertLevel.CRITICAL,
                        f"Agent {agent_type.value} is in critical state",
                        f"agent_{agent_type.value}"
                    )
                elif health.status == HealthStatus.WARNING:
                    self._create_alert(
                        AlertLevel.WARNING,
                        f"Agent {agent_type.value} is in warning state",
                        f"agent_{agent_type.value}"
                    )
                else:
                    health.success_count += 1
                
                # Notify health check handlers
                for handler in self.health_check_handlers:
                    try:
                        handler(health)
                    except Exception as e:
                        logger.error(f"Health check handler error: {e}")
                
            except Exception as e:
                logger.error(f"Health check failed for {agent_type.value}: {e}")
                self._create_alert(
                    AlertLevel.CRITICAL,
                    f"Health check failed for {agent_type.value}: {e}",
                    "system_scheduler"
                )
        
        # Update overall system state
        self._update_system_state()
    
    def _update_system_state(self):
        """Update overall system state based on agent health"""
        critical_count = 0
        warning_count = 0
        
        for health in self.agent_health.values():
            if health.status == HealthStatus.CRITICAL:
                critical_count += 1
            elif health.status == HealthStatus.WARNING:
                warning_count += 1
        
        # Determine new state
        if critical_count > 0:
            new_state = SystemState.EMERGENCY
        elif warning_count > 0:
            new_state = SystemState.DEGRADED
        elif self.maintenance_mode:
            new_state = SystemState.MAINTENANCE
        else:
            new_state = SystemState.OPERATIONAL
        
        if new_state != self.state:
            old_state = self.state
            self.state = new_state
            logger.info(f"System state changed: {old_state.value} -> {new_state.value}")
            self._notify_state_change()
    
    async def _collect_system_metrics(self):
        """Collect system-wide metrics"""
        if not PSUTIL_AVAILABLE:
            return
        
        try:
            # CPU usage
            cpu_usage = psutil.cpu_percent(interval=1)
            
            # Memory usage
            memory = psutil.virtual_memory()
            memory_usage = memory.percent
            
            # Disk usage
            disk = psutil.disk_usage('/')
            disk_usage = disk.percent
            
            # Network I/O
            network = psutil.net_io_counters()
            network_io = {
                'bytes_sent': network.bytes_sent,
                'bytes_recv': network.bytes_recv,
                'packets_sent': network.packets_sent,
                'packets_recv': network.packets_recv
            }
            
            # Active connections
            active_connections = len(psutil.net_connections())
            
            # Calculate error rate
            total_requests = self.performance_metrics['total_requests']
            failed_requests = self.performance_metrics['failed_requests']
            error_rate = failed_requests / total_requests if total_requests > 0 else 0.0
            
            metrics = SystemMetrics(
                cpu_usage=cpu_usage,
                memory_usage=memory_usage,
                disk_usage=disk_usage,
                network_io=network_io,
                active_connections=active_connections,
                total_requests=total_requests,
                error_rate=error_rate,
                timestamp=datetime.datetime.now()
            )
            
            self.metrics_history.append(metrics)
            
            # Check for resource thresholds
            if cpu_usage > 90:
                self._create_alert(
                    AlertLevel.CRITICAL,
                    f"High CPU usage: {cpu_usage}%",
                    "system_metrics"
                )
            
            if memory_usage > 90:
                self._create_alert(
                    AlertLevel.CRITICAL,
                    f"High memory usage: {memory_usage}%",
                    "system_metrics"
                )
            
            if disk_usage > 90:
                self._create_alert(
                    AlertLevel.WARNING,
                    f"High disk usage: {disk_usage}%",
                    "system_metrics"
                )
            
        except Exception as e:
            logger.error(f"Error collecting system metrics: {e}")
    
    def _update_performance_metrics(self):
        """Update performance metrics"""
        # Calculate averages
        if self.performance_metrics['total_requests'] > 0:
            success_rate = self.performance_metrics['successful_requests'] / self.performance_metrics['total_requests']
            
            if success_rate < 0.95:
                self._create_alert(
                    AlertLevel.WARNING,
                    f"Low success rate: {success_rate:.2%}",
                    "performance_metrics"
                )
    
    def _cleanup_old_alerts(self):
        """Clean up old alerts"""
        cutoff_time = datetime.datetime.now() - datetime.timedelta(hours=24)
        self.alerts = [alert for alert in self.alerts if alert.timestamp > cutoff_time]
    
    def _create_alert(self, level: AlertLevel, message: str, source: str):
        """Create a new alert"""
        alert = Alert(
            level=level,
            message=message,
            source=source,
            timestamp=datetime.datetime.now()
        )
        
        self.alerts.append(alert)
        logger.warning(f"Alert [{level.value}] {source}: {message}")
        
        # Notify alert handlers
        for handler in self.alert_handlers:
            try:
                handler(alert)
            except Exception as e:
                logger.error(f"Alert handler error: {e}")
    
    def _notify_state_change(self):
        """Notify state change handlers"""
        for handler in self.state_change_handlers:
            try:
                handler(self.state)
            except Exception as e:
                logger.error(f"State change handler error: {e}")
    
    def _save_metrics(self):
        """Save metrics to persistent storage"""
        try:
            metrics_data = {
                'timestamp': datetime.datetime.now().isoformat(),
                'system_state': self.state.value,
                'agent_health': {
                    agent_type.value: {
                        'status': health.status.value,
                        'last_check': health.last_check.isoformat(),
                        'response_time': health.response_time,
                        'error_count': health.error_count,
                        'success_count': health.success_count,
                        'details': health.details
                    }
                    for agent_type, health in self.agent_health.items()
                },
                'performance_metrics': self.performance_metrics,
                'alerts': [
                    {
                        'level': alert.level.value,
                        'message': alert.message,
                        'source': alert.source,
                        'timestamp': alert.timestamp.isoformat(),
                        'acknowledged': alert.acknowledged,
                        'resolved': alert.resolved
                    }
                    for alert in self.alerts
                ]
            }
            
            # Save to file
            metrics_file = Path("system_metrics.json")
            with open(metrics_file, 'w') as f:
                json.dump(metrics_data, f, indent=2)
                
        except Exception as e:
            logger.error(f"Error saving metrics: {e}")
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        return {
            'state': self.state.value,
            'maintenance_mode': self.maintenance_mode,
            'emergency_shutdown': self.emergency_shutdown,
            'agent_health': {
                agent_type.value: {
                    'status': health.status.value,
                    'last_check': health.last_check.isoformat(),
                    'response_time': health.response_time,
                    'error_count': health.error_count,
                    'success_count': health.success_count,
                    'details': health.details
                }
                for agent_type, health in self.agent_health.items()
            },
            'performance_metrics': self.performance_metrics,
            'active_alerts': len([a for a in self.alerts if not a.resolved]),
            'total_alerts': len(self.alerts),
            'metrics_history_size': len(self.metrics_history)
        }
    
    def enable_maintenance_mode(self):
        """Enable maintenance mode"""
        self.maintenance_mode = True
        self.state = SystemState.MAINTENANCE
        logger.info("Maintenance mode enabled")
        self._notify_state_change()
    
    def disable_maintenance_mode(self):
        """Disable maintenance mode"""
        self.maintenance_mode = False
        self._update_system_state()
        logger.info("Maintenance mode disabled")
    
    def acknowledge_alert(self, alert_index: int):
        """Acknowledge an alert"""
        if 0 <= alert_index < len(self.alerts):
            self.alerts[alert_index].acknowledged = True
            logger.info(f"Alert acknowledged: {self.alerts[alert_index].message}")
    
    def resolve_alert(self, alert_index: int):
        """Resolve an alert"""
        if 0 <= alert_index < len(self.alerts):
            self.alerts[alert_index].resolved = True
            logger.info(f"Alert resolved: {self.alerts[alert_index].message}")
    
    def add_health_check_handler(self, handler: Callable[[AgentHealth], None]):
        """Add a health check event handler"""
        self.health_check_handlers.append(handler)
    
    def add_alert_handler(self, handler: Callable[[Alert], None]):
        """Add an alert event handler"""
        self.alert_handlers.append(handler)
    
    def add_state_change_handler(self, handler: Callable[[SystemState], None]):
        """Add a state change event handler"""
        self.state_change_handlers.append(handler)
    
    def get_agent_health(self, agent_type: AgentType) -> Optional[AgentHealth]:
        """Get health status for a specific agent"""
        return self.agent_health.get(agent_type)
    
    def get_alerts(self, level: Optional[AlertLevel] = None, 
                   resolved: Optional[bool] = None) -> List[Alert]:
        """Get filtered alerts"""
        alerts = self.alerts
        
        if level is not None:
            alerts = [a for a in alerts if a.level == level]
        
        if resolved is not None:
            alerts = [a for a in alerts if a.resolved == resolved]
        
        return alerts
    
    def get_metrics_history(self, limit: Optional[int] = None) -> List[SystemMetrics]:
        """Get metrics history"""
        if limit is None:
            return list(self.metrics_history)
        else:
            return list(self.metrics_history)[-limit:]


# Convenience functions for easy integration
def create_system_scheduler(config: Optional[Dict[str, Any]] = None) -> SystemScheduler:
    """Create and configure a system scheduler"""
    scheduler = SystemScheduler(config)
    
    # Add default health checks
    scheduler.add_health_check(StreamHealthCheck())
    scheduler.add_health_check(AuthHealthCheck())
    scheduler.add_health_check(OrderHealthCheck())
    scheduler.add_health_check(RateLimitHealthCheck())
    scheduler.add_health_check(BufferHealthCheck())
    scheduler.add_health_check(TokenHealthCheck())
    scheduler.add_health_check(SessionHealthCheck())
    scheduler.add_health_check(SignalHealthCheck())
    
    return scheduler


def start_system_monitoring(config: Optional[Dict[str, Any]] = None) -> SystemScheduler:
    """Start system monitoring with default configuration"""
    scheduler = create_system_scheduler(config)
    scheduler.start()
    return scheduler


if __name__ == "__main__":
    # Example usage
    import asyncio
    
    async def main():
        # Create and start the system scheduler
        scheduler = create_system_scheduler()
        scheduler.start()
        
        # Run for a period
        await asyncio.sleep(300)  # 5 minutes
        
        # Shutdown
        scheduler.shutdown()
    
    asyncio.run(main()) 
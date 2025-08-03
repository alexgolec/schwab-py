"""
Demo script for Agent 9: System Scheduler

Demonstrates the comprehensive system monitoring and scheduling framework
with real-time health checks, alert management, and system orchestration.
"""

import asyncio
import datetime
import logging
import time
from typing import Dict, Any

from system_scheduler import (
    SystemScheduler, SystemState, AgentType, HealthStatus, AlertLevel,
    create_system_scheduler, start_system_monitoring
)


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DemoSystemScheduler:
    """Demo system scheduler with simulated agents"""
    
    def __init__(self):
        self.scheduler = create_system_scheduler()
        self.simulation_running = False
        self.demo_data = {
            'stream_connection': {'status': 'CONNECTED', 'retry_count': 0},
            'authentication': {'token_age': 1800},  # 30 minutes
            'order_management': {'success_rate': 0.98},
            'rate_limiting': {'utilization': 0.6},
            'buffer_management': {'drop_rate': 0.005},
            'token_refresh': {'success_rate': 0.98},
            'user_sessions': {'active_sessions': 5},
            'signal_processing': {'accuracy': 0.85}
        }
    
    def setup_demo_health_checks(self):
        """Setup demo health checks with simulated data"""
        from system_scheduler import (
            StreamHealthCheck, AuthHealthCheck, OrderHealthCheck, RateLimitHealthCheck,
            BufferHealthCheck, TokenHealthCheck, SessionHealthCheck, SignalHealthCheck
        )
        
        # Create mock clients for demo
        mock_stream_client = MockStreamClient(self.demo_data['stream_connection'])
        mock_auth_client = MockAuthClient(self.demo_data['authentication'])
        mock_order_client = MockOrderClient(self.demo_data['order_management'])
        mock_rate_limit_client = MockRateLimitClient(self.demo_data['rate_limiting'])
        mock_buffer_manager = MockBufferManager(self.demo_data['buffer_management'])
        mock_token_manager = MockTokenManager(self.demo_data['token_refresh'])
        mock_session_manager = MockSessionManager(self.demo_data['user_sessions'])
        mock_signal_processor = MockSignalProcessor(self.demo_data['signal_processing'])
        
        # Add health checks with mock clients
        self.scheduler.add_health_check(StreamHealthCheck(mock_stream_client))
        self.scheduler.add_health_check(AuthHealthCheck(mock_auth_client))
        self.scheduler.add_health_check(OrderHealthCheck(mock_order_client))
        self.scheduler.add_health_check(RateLimitHealthCheck(mock_rate_limit_client))
        self.scheduler.add_health_check(BufferHealthCheck(mock_buffer_manager))
        self.scheduler.add_health_check(TokenHealthCheck(mock_token_manager))
        self.scheduler.add_health_check(SessionHealthCheck(mock_session_manager))
        self.scheduler.add_health_check(SignalHealthCheck(mock_signal_processor))
    
    def setup_event_handlers(self):
        """Setup event handlers for demo"""
        def health_check_handler(health):
            logger.info(f"Health check: {health.agent_type.value} - {health.status.value}")
        
        def alert_handler(alert):
            logger.warning(f"Alert [{alert.level.value}] {alert.source}: {alert.message}")
        
        def state_change_handler(state):
            logger.info(f"System state changed to: {state.value}")
        
        self.scheduler.add_health_check_handler(health_check_handler)
        self.scheduler.add_alert_handler(alert_handler)
        self.scheduler.add_state_change_handler(state_change_handler)
    
    def simulate_system_load(self):
        """Simulate varying system load"""
        import random
        
        # Simulate realistic load variations
        self.demo_data['stream_connection']['retry_count'] = random.randint(0, 5)
        self.demo_data['authentication']['token_age'] = random.randint(1800, 7200)
        self.demo_data['order_management']['success_rate'] = random.uniform(0.85, 0.99)
        self.demo_data['rate_limiting']['utilization'] = random.uniform(0.3, 0.95)
        self.demo_data['buffer_management']['drop_rate'] = random.uniform(0.001, 0.08)
        self.demo_data['token_refresh']['success_rate'] = random.uniform(0.90, 0.99)
        self.demo_data['user_sessions']['active_sessions'] = random.randint(1, 20)
        self.demo_data['signal_processing']['accuracy'] = random.uniform(0.70, 0.95)
    
    def simulate_failures(self):
        """Simulate various failure scenarios"""
        scenarios = [
            # Stream connection failure
            lambda: self.demo_data.update({
                'stream_connection': {'status': 'DISCONNECTED', 'retry_count': 10}
            }),
            # Authentication token expired
            lambda: self.demo_data.update({
                'authentication': {'token_age': 10800}  # 3 hours
            }),
            # Order management failure
            lambda: self.demo_data.update({
                'order_management': {'success_rate': 0.75}
            }),
            # Rate limiting overload
            lambda: self.demo_data.update({
                'rate_limiting': {'utilization': 0.98}
            }),
            # Buffer overflow
            lambda: self.demo_data.update({
                'buffer_management': {'drop_rate': 0.12}
            }),
            # Token refresh failure
            lambda: self.demo_data.update({
                'token_refresh': {'success_rate': 0.80}
            }),
            # No active sessions
            lambda: self.demo_data.update({
                'user_sessions': {'active_sessions': 0}
            }),
            # Signal processing degradation
            lambda: self.demo_data.update({
                'signal_processing': {'accuracy': 0.65}
            })
        ]
        
        import random
        scenario = random.choice(scenarios)
        scenario()
        logger.info("Simulated failure scenario")
    
    def print_system_status(self):
        """Print current system status"""
        status = self.scheduler.get_system_status()
        
        print("\n" + "="*60)
        print("SYSTEM STATUS DASHBOARD")
        print("="*60)
        print(f"System State: {status['state'].upper()}")
        print(f"Maintenance Mode: {status['maintenance_mode']}")
        print(f"Active Alerts: {status['active_alerts']}")
        print(f"Total Alerts: {status['total_alerts']}")
        print(f"Metrics History: {status['metrics_history_size']} entries")
        
        print("\nAGENT HEALTH STATUS:")
        print("-" * 40)
        for agent_name, agent_status in status['agent_health'].items():
            print(f"{agent_name:25} | {agent_status['status']:10} | "
                  f"Response: {agent_status['response_time']:.3f}s")
        
        print("\nPERFORMANCE METRICS:")
        print("-" * 40)
        metrics = status['performance_metrics']
        print(f"Total Requests: {metrics['total_requests']}")
        print(f"Successful Requests: {metrics['successful_requests']}")
        print(f"Failed Requests: {metrics['failed_requests']}")
        if metrics['total_requests'] > 0:
            success_rate = metrics['successful_requests'] / metrics['total_requests']
            print(f"Success Rate: {success_rate:.2%}")
        
        print("\nRECENT ALERTS:")
        print("-" * 40)
        recent_alerts = self.scheduler.get_alerts(resolved=False)[-5:]
        for i, alert in enumerate(recent_alerts):
            print(f"{i+1}. [{alert.level.value.upper()}] {alert.message}")
        
        print("="*60)
    
    async def run_demo(self, duration: int = 300):
        """Run the demo for specified duration"""
        logger.info(f"Starting system scheduler demo for {duration} seconds")
        
        # Setup demo components
        self.setup_demo_health_checks()
        self.setup_event_handlers()
        
        # Start the scheduler
        self.scheduler.start()
        self.simulation_running = True
        
        start_time = time.time()
        last_status_print = 0
        
        try:
            while time.time() - start_time < duration and self.simulation_running:
                # Simulate system load
                self.simulate_system_load()
                
                # Occasionally simulate failures
                if time.time() - start_time > 60:  # After 1 minute
                    if time.time() % 30 < 1:  # Every 30 seconds
                        self.simulate_failures()
                
                # Print status every 10 seconds
                if time.time() - last_status_print > 10:
                    self.print_system_status()
                    last_status_print = time.time()
                
                # Small delay
                await asyncio.sleep(1)
        
        except KeyboardInterrupt:
            logger.info("Demo interrupted by user")
        
        finally:
            self.simulation_running = False
            self.scheduler.shutdown()
            logger.info("Demo completed")


# Mock classes for demo
class MockStreamClient:
    def __init__(self, data):
        self.data = data
    
    def get_health_status(self):
        return self.data


class MockAuthClient:
    def __init__(self, data):
        self.data = data
    
    def token_age(self):
        return self.data['token_age']


class MockOrderClient:
    def __init__(self, data):
        self.data = data
    
    def get_order_stats(self):
        return self.data


class MockRateLimitClient:
    def __init__(self, data):
        self.data = data
    
    def get_utilization(self):
        return self.data['utilization']


class MockBufferManager:
    def __init__(self, data):
        self.data = data
    
    def get_buffer_stats(self):
        return self.data


class MockTokenManager:
    def __init__(self, data):
        self.data = data
    
    def get_refresh_stats(self):
        return self.data


class MockSessionManager:
    def __init__(self, data):
        self.data = data
    
    def get_session_stats(self):
        return self.data


class MockSignalProcessor:
    def __init__(self, data):
        self.data = data
    
    def get_performance_stats(self):
        return self.data


def main():
    """Main demo function"""
    print("Agent 9: System Scheduler Demo")
    print("=" * 40)
    print("This demo showcases:")
    print("- Real-time system monitoring")
    print("- Health checks for all agents")
    print("- Alert generation and management")
    print("- System state transitions")
    print("- Performance metrics collection")
    print("- Graceful shutdown procedures")
    print("=" * 40)
    
    # Create and run demo
    demo = DemoSystemScheduler()
    
    try:
        asyncio.run(demo.run_demo(duration=300))  # 5 minutes
    except KeyboardInterrupt:
        print("\nDemo interrupted. Shutting down gracefully...")
    except Exception as e:
        logger.error(f"Demo error: {e}")
        raise


if __name__ == "__main__":
    main() 
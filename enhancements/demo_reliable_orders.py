#!/usr/bin/env python3
"""
Demonstration of ReliableOrderClient usage

This script shows how to use the enhanced order management system
with reliable cancellation verification.

Agent 3: Order Management Specialist
"""

from reliable_orders import (
    ReliableOrderClient,
    CancellationTimeoutError,
    CancellationFailedError,
    BulkCancellationError,
    OrderEvent
)


def example_event_handler(event: OrderEvent):
    """Example event handler for Agent 8 integration"""
    print(f"Order Event: {event.event_type} for order {event.order_id} - Status: {event.status}")


def main():
    """Demonstrate ReliableOrderClient usage"""
    
    # This is a demonstration - in real usage you would pass actual session and API key
    print("=== ReliableOrderClient Demo ===")
    print("Note: This is a demonstration script showing the API interface.")
    print("In production, you would provide a real session and API key.\n")
    
    # Mock session for demo (in real usage, this would be a proper requests session)
    class MockSession:
        pass
    
    try:
        # Create reliable order client
        client = ReliableOrderClient(
            api_key="demo_api_key",
            session=MockSession()
        )
        
        # Register event handler for Agent 8 integration
        client.register_event_handler(example_event_handler)
        
        # Example: Single order cancellation with verification
        print("1. Single Order Cancellation with Verification:")
        print("   client.cancel_order_and_verify('12345', 'account_hash', 'user_123')")
        print("   - Polls every 2 seconds for up to 30 seconds")
        print("   - Retries cancellation up to 3 times if needed")
        print("   - Returns True when CANCELED or REJECTED")
        print()
        
        # Example: Bulk order cancellation
        print("2. Bulk Order Cancellation with Rollback:")
        orders = [
            ("order_1", "account_hash"),
            ("order_2", "account_hash"),
            ("order_3", "account_hash")
        ]
        print(f"   orders = {orders}")
        print("   client.bulk_cancel_orders(orders, user_id='user_123')")
        print("   - Cancels all orders individually")
        print("   - Rolls back successful cancellations on partial failure")
        print()
        
        # Example: User isolation (Agent 7)
        print("3. Per-User Order Isolation (Agent 7):")
        print("   client.set_user_context('user_123', 'order_1', 'account_hash')")
        print("   user_orders = client.get_user_orders('user_123')")
        print("   - Isolates orders by user for multi-tenant systems")
        print()
        
        # Example: Rate limiting (Agent 4)
        print("4. Rate Limiting Integration (Agent 4):")
        print("   client._respect_rate_limit()  # Called automatically")
        print("   - Ensures minimum 500ms between requests")
        print("   - 2-second polling counts toward rate limit")
        print()
        
        # Example: Order state tracking
        print("5. Order State Tracking:")
        print("   state = client.get_order_state('order_1', 'account_hash')")
        print("   - Fast in-memory order status lookups")
        print("   - Tracks cancellation attempts and timestamps")
        print()
        
        # Example: Audit trail
        print("6. Compliance Audit Trail:")
        print("   trail = client.audit_trail.get_trail_for_order('order_1')")
        print("   user_trail = client.audit_trail.get_trail_for_user('user_123')")
        print("   - Complete audit log for regulatory compliance")
        print()
        
        # Example: Error handling
        print("7. Comprehensive Error Handling:")
        print("   try:")
        print("       client.cancel_order_and_verify('12345', 'account_hash')")
        print("   except CancellationTimeoutError as e:")
        print("       # Handle timeout after 30 seconds")
        print("   except CancellationFailedError as e:")
        print("       # Handle cancellation failure after retries")
        print("   except BulkCancellationError as e:")
        print("       # Handle bulk operation failures with rollback info")
        print()
        
        # Example: Recovery after restart
        print("8. Service Recovery:")
        print("   recovered = client.recover_orders_after_restart()")
        print("   - Rebuilds order state after service restart")
        print("   - Supports both global and per-user recovery")
        print()
        
        print("=== Configuration Options ===")
        print(f"Poll interval: {client.poll_interval} seconds")
        print(f"Max poll duration: {client.max_poll_duration} seconds")
        print(f"Max cancellation retries: {client.max_cancellation_retries}")
        print(f"Min request interval: {client._min_request_interval} seconds")
        
        print("\n=== Integration Points ===")
        print("✓ Agent 4: Rate limiting with 2-second polling")
        print("✓ Agent 6: Token refresh during long operations")
        print("✓ Agent 7: Per-user order isolation")
        print("✓ Agent 8: Order event emission for signal processing")
        
        print("\n=== Reliability Features ===")
        print("✓ Network timeout handling")
        print("✓ Order recovery after service restart")
        print("✓ Comprehensive audit trail")
        print("✓ Bulk operations with rollback")
        print("✓ Thread-safe state management")
        print("✓ Memory leak prevention (state cleanup)")
        
    except Exception as e:
        print(f"Demo error (expected without real session): {e}")
        print("This is normal for the demo - shows the API structure.")


if __name__ == "__main__":
    main()
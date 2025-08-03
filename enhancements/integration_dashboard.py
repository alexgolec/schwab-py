#!/usr/bin/env python3
"""
Integration Dashboard for schwab-py High-Availability Enhancement

Provides real-time monitoring of multi-agent development progress and integration status.
Displays agent progress, conflicts, and integration readiness across all phases.
"""

import json
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import os
import sys

# Import our orchestrator and analyzer
from project_orchestrator import ProjectOrchestrator, AgentStatus, IntegrationPhase
from architectural_analyzer import ArchitecturalAnalyzer, ConflictType


@dataclass
class DashboardMetrics:
    """Dashboard metrics for monitoring"""
    total_agents: int
    active_agents: int
    completed_agents: int
    blocked_agents: int
    overall_progress: float
    phase_readiness: Dict[str, bool]
    active_conflicts: int
    critical_issues: int
    integration_ready: int
    last_updated: datetime


class IntegrationDashboard:
    """Real-time integration dashboard"""
    
    def __init__(self, refresh_interval: int = 30):
        self.orchestrator = ProjectOrchestrator()
        self.analyzer = ArchitecturalAnalyzer()
        self.refresh_interval = refresh_interval
        self.metrics: Optional[DashboardMetrics] = None
        self.is_monitoring = False
        self.monitor_thread: Optional[threading.Thread] = None
        
        # Load initial state
        self.orchestrator.load_state()
        self._update_metrics()
    
    def _update_metrics(self):
        """Update dashboard metrics"""
        overview = self.orchestrator.get_project_overview()
        conflicts = self.analyzer.analyze_agent_conflicts()
        
        # Calculate phase readiness
        phase_readiness = {}
        for phase in IntegrationPhase:
            status = overview['phase_status'][phase.value]
            phase_readiness[phase.value] = status['all_agents_ready']
        
        # Count critical issues
        critical_issues = len([c for c in conflicts if c.severity == "critical"])
        
        self.metrics = DashboardMetrics(
            total_agents=overview['total_agents'],
            active_agents=overview['total_agents'] - overview['completed_agents'] - overview['blocked_agents'],
            completed_agents=overview['completed_agents'],
            blocked_agents=overview['blocked_agents'],
            overall_progress=overview['overall_progress'],
            phase_readiness=phase_readiness,
            active_conflicts=overview['active_conflicts'],
            critical_issues=critical_issues,
            integration_ready=overview['integration_ready'],
            last_updated=datetime.now()
        )
    
    def start_monitoring(self):
        """Start continuous monitoring"""
        if self.is_monitoring:
            print("Monitoring already active")
            return
        
        self.is_monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        print("Dashboard monitoring started")
    
    def stop_monitoring(self):
        """Stop continuous monitoring"""
        self.is_monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join()
        print("Dashboard monitoring stopped")
    
    def _monitor_loop(self):
        """Main monitoring loop"""
        while self.is_monitoring:
            try:
                self._update_metrics()
                self._save_monitoring_data()
                time.sleep(self.refresh_interval)
            except Exception as e:
                print(f"Monitoring error: {e}")
                time.sleep(5)
    
    def _save_monitoring_data(self):
        """Save monitoring data to file"""
        if not self.metrics:
            return
        
        data = {
            "timestamp": self.metrics.last_updated.isoformat(),
            "metrics": asdict(self.metrics),
            "agent_status": {
                agent_id: {
                    "name": agent.name,
                    "status": agent.status.value,
                    "progress": agent.progress_percentage,
                    "phase": agent.integration_phase.value
                }
                for agent_id, agent in self.orchestrator.agents.items()
            }
        }
        
        with open("dashboard_data.json", "w") as f:
            json.dump(data, f, indent=2)
    
    def display_dashboard(self):
        """Display the current dashboard"""
        self._update_metrics()
        
        if not self.metrics:
            print("No metrics available")
            return
        
        print("\n" + "="*80)
        print("SCHWAB-PY HIGH-AVAILABILITY ENHANCEMENT DASHBOARD")
        print("="*80)
        print(f"Last Updated: {self.metrics.last_updated.strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        # Overall Progress
        print("📊 OVERALL PROGRESS")
        print("-" * 40)
        print(f"Total Agents:     {self.metrics.total_agents}")
        print(f"Active Agents:    {self.metrics.active_agents}")
        print(f"Completed:        {self.metrics.completed_agents}")
        print(f"Integration Ready: {self.metrics.integration_ready}")
        print(f"Blocked:          {self.metrics.blocked_agents}")
        print(f"Overall Progress: {self.metrics.overall_progress:.1f}%")
        print()
        
        # Agent Status
        print("🤖 AGENT STATUS")
        print("-" * 40)
        for agent_id, agent in self.orchestrator.agents.items():
            status_icon = self._get_status_icon(agent.status)
            progress_bar = self._get_progress_bar(agent.progress_percentage)
            print(f"Agent {agent_id:2d}: {status_icon} {agent.name[:30]:<30} {progress_bar} {agent.progress_percentage:5.1f}%")
        print()
        
        # Phase Readiness
        print("📋 INTEGRATION PHASES")
        print("-" * 40)
        for phase in IntegrationPhase:
            status = self.orchestrator.get_integration_status(phase)
            ready_icon = "✅" if status['all_agents_ready'] else "⏳"
            agent_count = len(status['agent_statuses'])
            print(f"{phase.value.upper():<15} {ready_icon} Week {status['week']} - {agent_count} agents")
        print()
        
        # Issues and Conflicts
        print("⚠️  ISSUES & CONFLICTS")
        print("-" * 40)
        print(f"Active Conflicts: {self.metrics.active_conflicts}")
        print(f"Critical Issues:  {self.metrics.critical_issues}")
        
        # Show recent conflicts
        conflicts = self.analyzer.analyze_agent_conflicts()
        if conflicts:
            print("\nRecent Conflicts:")
            for conflict in conflicts[:3]:  # Show top 3
                severity_icon = self._get_severity_icon(conflict.severity)
                print(f"  {severity_icon} {conflict.description[:60]}...")
        print()
        
        # Integration Timeline
        print("📅 INTEGRATION TIMELINE")
        print("-" * 40)
        for phase in IntegrationPhase:
            status = self.orchestrator.get_integration_status(phase)
            date = datetime.fromisoformat(status['date']).strftime('%Y-%m-%d')
            ready_icon = "✅" if status['all_agents_ready'] else "⏳"
            print(f"Week {status['week']:2d} ({date}): {ready_icon} {phase.value.replace('_', ' ').title()}")
        print()
        
        # Recommendations
        print("💡 RECOMMENDATIONS")
        print("-" * 40)
        recommendations = self.analyzer.generate_integration_recommendations()
        
        if recommendations["critical"]:
            print("Critical Actions Needed:")
            for rec in recommendations["critical"][:2]:
                print(f"  🔴 {rec}")
        
        if recommendations["high"]:
            print("High Priority:")
            for rec in recommendations["high"][:2]:
                print(f"  🟡 {rec}")
        
        if not recommendations["critical"] and not recommendations["high"]:
            print("  🟢 No critical issues detected")
        print()
    
    def _get_status_icon(self, status: AgentStatus) -> str:
        """Get status icon for agent"""
        icons = {
            AgentStatus.NOT_STARTED: "⏸️ ",
            AgentStatus.IN_PROGRESS: "🔄",
            AgentStatus.COMPLETED: "✅",
            AgentStatus.BLOCKED: "🚫",
            AgentStatus.INTEGRATION_READY: "🎯"
        }
        return icons.get(status, "❓")
    
    def _get_severity_icon(self, severity: str) -> str:
        """Get severity icon for conflicts"""
        icons = {
            "critical": "🔴",
            "high": "🟡",
            "medium": "🟠",
            "low": "🟢"
        }
        return icons.get(severity, "⚪")
    
    def _get_progress_bar(self, progress: float, width: int = 20) -> str:
        """Generate progress bar"""
        filled = int(progress / 100 * width)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}]"
    
    def get_agent_details(self, agent_id: int) -> Dict:
        """Get detailed information about a specific agent"""
        agent = self.orchestrator.get_agent_status(agent_id)
        if not agent:
            return {"error": f"Agent {agent_id} not found"}
        
        # Get conflicts involving this agent
        conflicts = self.analyzer.analyze_agent_conflicts()
        agent_conflicts = [
            c for c in conflicts 
            if agent_id in c.agent_ids
        ]
        
        # Get dependencies
        dependencies = self.analyzer.analyze_dependencies()
        agent_deps = dependencies.get(agent_id, [])
        
        return {
            "id": agent.id,
            "name": agent.name,
            "branch": agent.branch,
            "description": agent.description,
            "status": agent.status.value,
            "progress": agent.progress_percentage,
            "phase": agent.integration_phase.value,
            "dependencies": agent_deps,
            "conflicts": [c.description for c in agent_conflicts],
            "issues": agent.issues,
            "last_update": agent.last_update.isoformat()
        }
    
    def generate_alert_report(self) -> List[Dict]:
        """Generate alerts for critical issues"""
        alerts = []
        
        # Check for blocked agents
        for agent_id, agent in self.orchestrator.agents.items():
            if agent.status == AgentStatus.BLOCKED:
                alerts.append({
                    "type": "blocked_agent",
                    "severity": "high",
                    "message": f"Agent {agent_id} ({agent.name}) is blocked",
                    "agent_id": agent_id
                })
        
        # Check for critical conflicts
        conflicts = self.analyzer.analyze_agent_conflicts()
        for conflict in conflicts:
            if conflict.severity == "critical":
                alerts.append({
                    "type": "critical_conflict",
                    "severity": "critical",
                    "message": conflict.description,
                    "agent_ids": conflict.agent_ids
                })
        
        # Check for phase readiness issues
        for phase in IntegrationPhase:
            status = self.orchestrator.get_integration_status(phase)
            if not status['all_agents_ready']:
                missing_agents = [
                    agent_id for agent_id, agent_status in status['agent_statuses'].items()
                    if not agent_status['ready']
                ]
                if missing_agents:
                    alerts.append({
                        "type": "phase_not_ready",
                        "severity": "medium",
                        "message": f"Phase {phase.value} not ready - missing agents: {missing_agents}",
                        "phase": phase.value,
                        "missing_agents": missing_agents
                    })
        
        return alerts
    
    def export_report(self, filename: str = "integration_report.json"):
        """Export comprehensive report"""
        self._update_metrics()
        
        report = {
            "timestamp": datetime.now().isoformat(),
            "metrics": asdict(self.metrics) if self.metrics else {},
            "agents": {
                agent_id: self.get_agent_details(agent_id)
                for agent_id in self.orchestrator.agents.keys()
            },
            "phases": {
                phase.value: self.orchestrator.get_integration_status(phase)
                for phase in IntegrationPhase
            },
            "conflicts": [
                {
                    "type": conflict.conflict_type.value,
                    "severity": conflict.severity,
                    "description": conflict.description,
                    "agent_ids": conflict.agent_ids,
                    "resolution_suggestions": conflict.resolution_suggestions
                }
                for conflict in self.analyzer.analyze_agent_conflicts()
            ],
            "alerts": self.generate_alert_report(),
            "recommendations": self.analyzer.generate_integration_recommendations()
        }
        
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"Report exported to {filename}")


def main():
    """Main function for dashboard"""
    dashboard = IntegrationDashboard()
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "display":
            dashboard.display_dashboard()
        
        elif command == "monitor":
            dashboard.start_monitoring()
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                dashboard.stop_monitoring()
        
        elif command == "agent" and len(sys.argv) > 2:
            agent_id = int(sys.argv[2])
            details = dashboard.get_agent_details(agent_id)
            print(json.dumps(details, indent=2))
        
        elif command == "alerts":
            alerts = dashboard.generate_alert_report()
            for alert in alerts:
                severity_icon = dashboard._get_severity_icon(alert["severity"])
                print(f"{severity_icon} {alert['message']}")
        
        elif command == "export":
            filename = sys.argv[2] if len(sys.argv) > 2 else "integration_report.json"
            dashboard.export_report(filename)
        
        else:
            print("Usage:")
            print("  python integration_dashboard.py display")
            print("  python integration_dashboard.py monitor")
            print("  python integration_dashboard.py agent <agent_id>")
            print("  python integration_dashboard.py alerts")
            print("  python integration_dashboard.py export [filename]")
    else:
        dashboard.display_dashboard()


if __name__ == "__main__":
    main() 
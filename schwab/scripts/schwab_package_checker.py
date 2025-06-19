#!/usr/bin/env python
"""
Pachage Analysis Module for Schwab API

This module provides utilities to check package versions, check for package updates.

Usage:
    python token_analysis.py                   # Basic analysis
    python token_analysis.py --check-updates   # Include package update checks
    python token_analysis.py --help            # Show all options
"""
"""
Contributed by George Neusse 6/2025 Ver. 1.0.0
"""
import argparse
import json
import sys
import httpx
from dataclasses import dataclass
from importlib import metadata
from typing import Dict, List, Optional, Tuple
from packaging import version



@dataclass
class PackageInfo:
    """Data class to hold package version information."""
    name: str
    installed_version: str
    latest_version: Optional[str] = None
    update_available: bool = False
    is_installed: bool = True


class PackageVersionChecker:
    """Utility class for checking installed package versions and available updates."""
    
    # Package distributions to check for compatibility analysis
    CRITICAL_PACKAGES = [
        'autopep8',
        'authlib',
        'flask',
        'httpx',
        'multiprocess',
        'psutil',
        'python-dateutil',
        'urllib3',
        'websockets',
        "certifi",
        "pytest",
        "schwab-py",  # Main Schwab API package
        "packaging",   # Added since we're using it
    ]
    
    def __init__(self, timeout_seconds: int = 10):
        """
        Initialize the package version checker.
        
        Args:
            timeout_seconds: Timeout for PyPI API requests
        """
        self.timeout = timeout_seconds
        self.pypi_base_url = "https://pypi.org/pypi"
    
    @staticmethod
    def get_installed_version(package_name: str) -> str:
        """
        Get the version of an installed package.
        
        Args:
            package_name: Name of the package to check
            
        Returns:
            Version string or 'not installed' if package not found
        """
        try:
            return metadata.version(package_name)
        except metadata.PackageNotFoundError:
            return "not installed"
    
    def get_latest_version(self, package_name: str) -> Optional[str]:
        """
        Get the latest version of a package from PyPI.
        
        Args:
            package_name: Name of the package to check
            
        Returns:
            Latest version string or None if unable to fetch
        """
        try:
            url = f"{self.pypi_base_url}/{package_name}/json"
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(url)
                response.raise_for_status()
                data = response.json()
                return data["info"]["version"]
        except (httpx.HTTPError, KeyError, json.JSONDecodeError):
            return None
    
    def check_package_info(self, package_name: str, check_updates: bool = False) -> PackageInfo:
        """
        Get comprehensive information about a package.
        
        Args:
            package_name: Name of the package to check
            check_updates: Whether to check for available updates
            
        Returns:
            PackageInfo object with version information
        """
        installed_version = self.get_installed_version(package_name)
        is_installed = installed_version != "not installed"
        
        latest_version = None
        update_available = False
        
        if check_updates and is_installed:
            latest_version = self.get_latest_version(package_name)
            if latest_version:
                try:
                    # Use packaging.version for proper version comparison
                    update_available = version.parse(latest_version) > version.parse(installed_version)
                except version.InvalidVersion:
                    # If version parsing fails, do string comparison as fallback
                    update_available = latest_version != installed_version
        
        return PackageInfo(
            name=package_name,
            installed_version=installed_version,
            latest_version=latest_version,
            update_available=update_available,
            is_installed=is_installed
        )
    
    def get_all_package_info(self, check_updates: bool = False) -> List[PackageInfo]:
        """
        Get information for all critical packages.
        
        Args:
            check_updates: Whether to check for available updates
            
        Returns:
            List of PackageInfo objects
        """
        return [self.check_package_info(pkg, check_updates) for pkg in self.CRITICAL_PACKAGES]
    
    @classmethod
    def get_all_versions(cls) -> Dict[str, str]:
        """
        Get versions of all critical packages (legacy method for compatibility).
        
        Returns:
            Dictionary mapping package names to version strings
        """
        return {pkg: cls.get_installed_version(pkg) for pkg in cls.CRITICAL_PACKAGES}



    def print_package_analysis(self, check_updates: bool = False) -> None:
        """
        Print analysis of installed Python packages.
        
        Args:
            check_updates: Whether to check for package updates
        """
        print("=== PYTHON PACKAGE ANALYSIS ===")
        print(f"Python version: {sys.version.split()[0]}")
        
        if check_updates:
            print("Checking for package updates... (this may take a moment)")
        
        package_info_list = self.get_all_package_info(check_updates)
        
        # Find the longest package name for formatting
        max_name_length = max(len(pkg.name) for pkg in package_info_list)
        
        for pkg_info in package_info_list:
            # Format the basic version info
            version_info = f"{pkg_info.name:{max_name_length}} version: {pkg_info.installed_version}"
            
            if check_updates and pkg_info.is_installed:
                if pkg_info.latest_version:
                    if pkg_info.update_available:
                        version_info += f" → {pkg_info.latest_version} ⚠️  UPDATE AVAILABLE"
                    else:
                        version_info += f" (latest: {pkg_info.latest_version}) ✅"
                else:
                    version_info += " (unable to check for updates)"
            
            print(version_info)
        
        # Summary of updates if checking
        if check_updates:
            updates_available = [pkg for pkg in package_info_list if pkg.update_available]
            if updates_available:
                print(f"\n📦 {len(updates_available)} package(s) have updates available:")
                for pkg in updates_available:
                    print(f"   • {pkg.name}: {pkg.installed_version} → {pkg.latest_version}")
                print("\nTo update packages, run: pip install --upgrade <package_name>")
            else:
                installed_packages = [pkg for pkg in package_info_list if pkg.is_installed]
                print(f"\n✅ All {len(installed_packages)} installed packages are up to date!")






def parse_arguments() -> argparse.Namespace:
    """
    Parse command line arguments.
    
    Returns:
        Parsed command line arguments
    """
    parser = argparse.ArgumentParser(
        description="Analyze Schwab Installed Packages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Basic token analysis
  %(prog)s --check-updates          # Include package update checks
  %(prog)s --timeout 15             # Set custom timeout for update checks
        """
    )
    
    parser.add_argument(
        '--check-updates', '-u',
        action='store_true',
        help='Check for available package updates (requires internet connection)'
    )
    
    parser.add_argument(
        '--timeout',
        type=int,
        default=10,
        help='Timeout in seconds for update checks (default: 10)'
    )
    
    return parser.parse_args()


def main() -> None:
    """
    Main function demonstrating token analysis and API testing.
    
    This function:
    1. Parses command line arguments
    2. heck packages 
    """
    # Parse command line arguments
    args = parse_arguments()
    
    try:
        pvc = PackageVersionChecker() 
        
        # Update package checker timeout if checking updates
        if args.check_updates:
            pvc.timeout = args.timeout
        
        pvc.print_package_analysis(args.check_updates)
        
    except httpx.TimeoutException:
        print(f"❌ Timeout error: Consider increasing --timeout value (current: {args.timeout}s)")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        if args.check_updates:
            print("💡 Try running without --check-updates if network issues persist")


if __name__ == "__main__":
    main()

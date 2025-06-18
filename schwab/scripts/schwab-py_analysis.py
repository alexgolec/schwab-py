"""
Token Analysis Module for Schwab API

This module provides utilities to analyze authentication tokens, check package versions,
check for package updates, and test API connectivity for the Schwab trading platform.

Usage:
    python token_analysis.py                    # Basic analysis
    python token_analysis.py --check-updates   # Include package update checks
    python token_analysis.py --help            # Show all options
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from packaging import version

import httpx
from schwab.auth import client_from_token_file


@dataclass
class TokenInfo:
    """Data class to hold token information in a structured way."""
    refresh_token: str
    access_token: str
    token_type: str
    expires_in: int
    expires_at: int
    scope: str


@dataclass
class TokenAnalysis:
    """Data class to hold token analysis results."""
    creation_timestamp: int
    current_timestamp: int
    token_info: TokenInfo
    age_seconds: int
    time_until_expiry: int
    is_expired: bool
    should_refresh: bool


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
        "authlib",
        "httpx", 
        "certifi",
        "urllib3",
        "requests",
        "request",
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


class TimeUtils:
    """Utility class for time-related operations."""
    
    @staticmethod
    def split_seconds(total_seconds: int) -> Tuple[int, int, int, int]:
        """
        Convert seconds into human-readable time components.
        
        Args:
            total_seconds: Total number of seconds (non-negative)
            
        Returns:
            Tuple of (days, hours, minutes, seconds)
        """
        if total_seconds < 0:
            total_seconds = abs(total_seconds)
            
        days, remainder = divmod(total_seconds, 86400)     # 86400 seconds in a day
        hours, remainder = divmod(remainder, 3600)         # 3600 seconds in an hour
        minutes, seconds = divmod(remainder, 60)           # 60 seconds in a minute
        
        return days, hours, minutes, seconds
    
    @staticmethod
    def format_timestamp(timestamp: int) -> str:
        """
        Format a Unix timestamp as a human-readable string.
        
        Args:
            timestamp: Unix timestamp
            
        Returns:
            Formatted datetime string
        """
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


class TokenAnalyzer:
    """Main class for token analysis and management."""
    
    def __init__(self, refresh_threshold_seconds: int = 300):
        """
        Initialize the token analyzer.
        
        Args:
            refresh_threshold_seconds: Seconds before expiry to recommend refresh (default: 5 minutes)
        """
        self.refresh_threshold = refresh_threshold_seconds
        self.package_checker = PackageVersionChecker()
        
    def load_token_data(self, token_path: Path) -> Dict:
        """
        Load and validate token data from file.
        
        Args:
            token_path: Path to the token file
            
        Returns:
            Dictionary containing token data
            
        Raises:
            FileNotFoundError: If token file doesn't exist
            ValueError: If token file contains invalid JSON or missing required fields
        """
        if not token_path.exists():
            raise FileNotFoundError(f"Token file not found: {token_path}")
            
        try:
            with token_path.open('r', encoding='utf-8') as file:
                token_data = json.load(file)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in token file {token_path}: {e}")
        
        # Validate required fields
        required_fields = ['token', 'creation_timestamp']
        missing_fields = [field for field in required_fields if field not in token_data]
        if missing_fields:
            raise ValueError(f"Missing required fields in token data: {missing_fields}")
            
        return token_data
    
    def analyze_token(self, token_data: Dict) -> TokenAnalysis:
        """
        Analyze token data and return structured analysis.
        
        Args:
            token_data: Raw token data dictionary
            
        Returns:
            TokenAnalysis object with all analysis results
        """
        current_time = int(time.time())
        token_dict = token_data['token']
        
        # Create structured token info
        token_info = TokenInfo(
            refresh_token=token_dict['refresh_token'],
            access_token=token_dict['access_token'],
            token_type=token_dict['token_type'],
            expires_in=token_dict['expires_in'],
            expires_at=token_dict.get('expires_at', 0),
            scope=token_dict['scope']
        )
        
        # Calculate timing information
        age_seconds = current_time - token_data['creation_timestamp']
        time_until_expiry = token_info.expires_at - current_time
        is_expired = time_until_expiry <= 0
        should_refresh = time_until_expiry <= self.refresh_threshold
        
        return TokenAnalysis(
            creation_timestamp=token_data['creation_timestamp'],
            current_timestamp=current_time,
            token_info=token_info,
            age_seconds=age_seconds,
            time_until_expiry=time_until_expiry,
            is_expired=is_expired,
            should_refresh=should_refresh
        )
    
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
        
        package_info_list = self.package_checker.get_all_package_info(check_updates)
        
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
    
    def print_token_analysis(self, analysis: TokenAnalysis) -> None:
        """
        Print detailed token analysis information.
        
        Args:
            analysis: TokenAnalysis object containing analysis results
        """
        print("\n=== TOKEN ANALYSIS ===")
        
        # Token creation and age information
        creation_time_str = TimeUtils.format_timestamp(analysis.creation_timestamp)
        print(f"Token Creation: {creation_time_str}")
        
        days, hours, minutes, seconds = TimeUtils.split_seconds(analysis.age_seconds)
        print(f"Token Age: {days} days, {hours} hours, {minutes} minutes, {seconds} seconds")
        
        # Token details (with masked sensitive information)
        token = analysis.token_info
        print(f"\nRefresh Token: XXXX...{token.refresh_token[-5:]}")
        print(f"Access Token:  XXXX...{token.access_token[-5:]}")
        print(f"Token Type: {token.token_type}")
        print(f"Expires In: {token.expires_in} seconds")
        print(f"Scope: {token.scope}")
        
        # Expiry analysis
        current_time_str = TimeUtils.format_timestamp(analysis.current_timestamp)
        expires_time_str = TimeUtils.format_timestamp(token.expires_at)
        
        print(f"\nCurrent Time: {current_time_str}")
        print(f"Expires At: {expires_time_str}")
        print(f"Time Until Expiry: {analysis.time_until_expiry} seconds "
              f"({analysis.time_until_expiry/60:.1f} minutes)")
        print(f"Is Expired: {analysis.is_expired}")
        print(f"Should Refresh ({self.refresh_threshold}s margin): {analysis.should_refresh}")
    
    def analyze_and_print(self, token_path: Path, check_updates: bool = False) -> TokenAnalysis:
        """
        Convenience method to load, analyze, and print token information.
        
        Args:
            token_path: Path to the token file
            check_updates: Whether to check for package updates
            
        Returns:
            TokenAnalysis object with results
        """
        token_data = self.load_token_data(token_path)
        analysis = self.analyze_token(token_data)
        
        self.print_package_analysis(check_updates)
        self.print_token_analysis(analysis)
        
        return analysis


class SchwabAPITester:
    """Class for testing Schwab API connectivity and performance."""
    
    def __init__(self, api_key: str, app_secret: str):
        """
        Initialize the API tester.
        
        Args:
            api_key: Schwab API key
            app_secret: Schwab application secret
        """
        self.api_key = api_key
        self.app_secret = app_secret
    
    def create_client(self, token_path: Path):
        """
        Create a Schwab API client from token file.
        
        Args:
            token_path: Path to the token file
            
        Returns:
            Schwab API client object
        """
        return client_from_token_file(
            api_key=self.api_key,
            app_secret=self.app_secret,
            token_path=str(token_path)
        )
    
    def test_quote_retrieval(self, client, symbol: str = 'TSLA') -> Tuple[float, Dict]:
        """
        Test API connectivity by retrieving a stock quote.
        
        Args:
            client: Schwab API client
            symbol: Stock symbol to query (default: TSLA)
            
        Returns:
            Tuple of (execution_time_seconds, quote_data)
            
        Raises:
            httpx.HTTPStatusError: If API request fails
        """
        start_time = time.perf_counter()
        
        response = client.get_quote(symbol)
        response.raise_for_status()  # Raise exception for HTTP errors
        
        end_time = time.perf_counter()
        execution_time = end_time - start_time
        
        quote_data = response.json()
        return execution_time, quote_data


def parse_arguments() -> argparse.Namespace:
    """
    Parse command line arguments.
    
    Returns:
        Parsed command line arguments
    """
    parser = argparse.ArgumentParser(
        description="Analyze Schwab API tokens and test connectivity",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Basic token analysis
  %(prog)s --check-updates          # Include package update checks
  %(prog)s --token-path auth.json   # Use custom token file
  %(prog)s --timeout 15             # Set custom timeout for update checks
        """
    )
    
    parser.add_argument(
        '--check-updates', '-u',
        action='store_true',
        help='Check for available package updates (requires internet connection)'
    )
    
    parser.add_argument(
        '--token-path', '-t',
        type=Path,
        default=Path('token.txt'),
        help='Path to the token file (default: token.txt)'
    )
    
    parser.add_argument(
        '--timeout',
        type=int,
        default=10,
        help='Timeout in seconds for update checks (default: 10)'
    )
    
    parser.add_argument(
        '--refresh-threshold',
        type=int,
        default=300,
        help='Token refresh threshold in seconds (default: 300)'
    )
    
    return parser.parse_args()


def main() -> None:
    """
    Main function demonstrating token analysis and API testing.
    
    This function:
    1. Parses command line arguments
    2. Analyzes the token file and prints diagnostics
    3. Creates a Schwab API client
    4. Tests connectivity with a sample quote request
    5. Reports timing information
    """
    # Parse command line arguments
    args = parse_arguments()
    
    # Get API credentials from environment variables
    import os
    api_key = os.getenv("schwab_api_key")
    app_secret = os.getenv("schwab_app_secret")
    
    if not api_key or not app_secret:
        print("❌ ERROR: Missing required environment variables:")
        print("  - schwab_api_key")
        print("  - schwab_app_secret")
        return
    
    try:
        # Step 1: Analyze token
        analyzer = TokenAnalyzer(refresh_threshold_seconds=args.refresh_threshold)
        
        # Update package checker timeout if checking updates
        if args.check_updates:
            analyzer.package_checker.timeout = args.timeout
        
        analysis = analyzer.analyze_and_print(args.token_path, args.check_updates)
        
        if analysis.is_expired:
            print("\n⚠️  WARNING: Token is expired!")
            #return
        elif analysis.should_refresh:
            print(f"\n⚠️  WARNING: Token expires soon (within {analyzer.refresh_threshold} seconds)")
        
        # Step 2: Test API connectivity
        print("\n=== CREATING CLIENT ===")
        client_start_time = time.perf_counter()
        
        api_tester = SchwabAPITester(api_key, app_secret)
        client = api_tester.create_client(args.token_path)
        print(f"Client object: {client}")
        
        # Step 3: Test quote retrieval
        print("\n=== GETTING TSLA QUOTE ===")
        quote_time, quote_data = api_tester.test_quote_retrieval(client, 'TSLA')
        
        # Extract and display quote information
        tsla_quote = quote_data['TSLA']['regular']
        last_price = tsla_quote['regularMarketLastPrice']
        print(f"TSLA - regularMarketLastPrice: ${last_price}")
        
        # Step 4: Display timing information
        total_time = time.perf_counter() - client_start_time
        print("\n=== TIMING ===")
        print(f"Total execution time (client + quote): {total_time:.4f} seconds")
        print(f"Quote retrieval time only:             {quote_time:.4f} seconds")
        
        # Show usage tip for update checking if not used
        if not args.check_updates:
            print(f"\n💡 Tip: Use '{sys.argv[0]} --check-updates' to check for package updates")
        
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        print(f"💡 Use --token-path to specify a different token file location")
    except ValueError as e:
        print(f"❌ Token validation error: {e}")
    except httpx.HTTPStatusError as e:
        print(f"❌ API request failed: {e}")
    except httpx.TimeoutException:
        print(f"❌ Timeout error: Consider increasing --timeout value (current: {args.timeout}s)")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        if args.check_updates:
            print("💡 Try running without --check-updates if network issues persist")


if __name__ == "__main__":
    main()

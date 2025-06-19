#!/usr/bin/env python3
"""
Minimal CLI utility to refresh Schwab API access token
Usage: python refresh_token.py [token_file]
"""

import json
import time
import base64
import sys
import os
import httpx
from datetime import datetime
from pathlib import Path

def refresh_token(api_key, app_secret, refresh_token_value):
    """Refresh OAuth token using Schwab API"""
    credentials = f"{api_key}:{app_secret}"
    auth_header = base64.b64encode(credentials.encode()).decode()
    
    headers = {
        'Authorization': f'Basic {auth_header}',
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json'
    }
    
    data = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token_value
    }
    
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            'https://api.schwabapi.com/v1/oauth/token',
            headers=headers,
            data=data
        )
        
        if response.status_code != 200:
            raise Exception(f"Refresh failed: {response.status_code} - {response.text}")
        
        token = response.json()
        # Add expires_at timestamp
        token['expires_at'] = int(time.time()) + token.get('expires_in', 1800)
        return token


def main():
    if len(sys.argv) > 1:
        print("Usage: python refresh_token.py")
        sys.exit(1)
    
    # Get credentials from environment variables
    api_key = os.environ.get('SCHWAB_API_KEY')
    app_secret = os.environ.get('SCHWAB_APP_SECRET')
    token_file = Path(os.environ.get('SCHWAB_TOKEN_PATH'))
    
    if not api_key or not app_secret or not token_file:
        print("Error: SCHWAB_API_KEY and SCHWAB_APP_SECRET environment variables must be set")
        sys.exit(1)
    
    try:
        # Load current token
        with open(token_file, 'r') as f:
            token_data = json.load(f)
        
        # Refresh token
        new_token = refresh_token(api_key, app_secret, token_data['token']['refresh_token'])
        
        # Save refreshed token
        token_data['token'] = new_token
        with open(token_file, 'w') as f:
            json.dump(token_data, f, indent=2)
        
        print(f"Token refreshed successfully - expires at {new_token['expires_at']} ({datetime.fromtimestamp(new_token['expires_at'])})")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
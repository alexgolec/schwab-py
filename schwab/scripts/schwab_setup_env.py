#!/usr/bin/env python3
import os
import sys
import argparse
import subprocess
from urllib.parse import urlparse

VARS = {
    "schwab_api_key": {
        "desc": "Your Schwab API Key (alphanumeric)",
        "validator": lambda v: v.isalnum() and len(v) >= 10,
        "error": "Must be alphanumeric and at least 10 characters.",
    },
    "schwab_app_secret": {
        "desc": "Your Schwab App Secret (alphanumeric)",
        "validator": lambda v: v.isalnum() and len(v) >= 10,
        "error": "Must be alphanumeric and at least 10 characters.",
    },
    "schwab_callback_url": {
        "desc": "Your Schwab OAuth Callback URL (must start https://) use port :8182/",
        "validator": lambda v: bool(urlparse(v).scheme in ("https") and urlparse(v).netloc),
        "error": "Must be a valid URL, starting with https://",
    },
    "schwab_token_path": {
        "desc": "Filesystem path where your Schwab token will be stored",
        "validator": lambda v: os.path.isdir(os.path.dirname(os.path.abspath(v))) or os.access(os.getcwd(), os.W_OK),
        "error": "Directory must exist or be writable.",
    },
}

def display_vars():
    print("Current Schwab environment variables:")
    for name in VARS:
        val = os.environ.get(name)
        print(f"  {name} = {val!r}" if val else f"  {name} is not set")
    sys.exit(0)

def set_env(name, value):
    # set for current process
    os.environ[name] = value
    # persist in user environment via setx
    subprocess.run(["setx", name, value], check=True)

def prompt_var(name, info):
    existing = os.environ.get(name)
    if existing:
        print(f"\n{name} is currently set to: {existing!r}")
        change = input("Would you like to change it? [y/N]: ").strip().lower()
        if change != 'y':
            return
    else:
        create = input(f"\n{name} is not set. Create it now? [Y/n]: ").strip().lower()
        if create == 'n':
            return

    # loop until valid
    while True:
        val = input(f"Enter {info['desc']}: ").strip()
        if info["validator"](val):
            set_env(name, val)
            print(f"{name} set to {val!r}.\n")
            break
        else:
            print(f"Invalid value: {info['error']}")

def main():
    parser = argparse.ArgumentParser(
        description="Manage Schwab environment variables."
    )
    parser.add_argument(
        "-s", "--show", action="store_true",
        help="Display current env vars and exit"
    )
    args = parser.parse_args()

    if args.show:
        display_vars()

    print("This script will help you set up the following environment variables:\n")
    for name, info in VARS.items():
        print(f" • {name}: {info['desc']}")
    print("\n")

    for name, info in VARS.items():
        prompt_var(name, info)

    print("Done. You may need to restart your terminal or log out and back in for changes to take effect.")

if __name__ == "__main__":
    main()

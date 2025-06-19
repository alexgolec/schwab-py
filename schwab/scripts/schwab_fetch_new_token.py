#!/usr/bin/env python3
import os
import sys
import shutil
import schwab.auth
#import importlib.util
import schwab.scripts.schwab_setup_env as se
# # 1) Try the package import
# try:
#     from schwab.scripts import schwab_setup_env as se
# except ImportError:
#     # 2) Fallback: load by file path next to this script
#     pkg_dir = os.path.dirname(__file__)
#     module_path = os.path.join(pkg_dir, "schwab_setup_env.py")
#     if not os.path.exists(module_path):
#         print(f"Error: cannot find helper at {module_path}", file=sys.stderr)
#         sys.exit(1)
#     spec = importlib.util.spec_from_file_location("schwab_setup_env", module_path)
#     se = importlib.util.module_from_spec(spec)
#     spec.loader.exec_module(se)


def ensure_env_vars():
    missing = [name for name in schwab.scripts.schwab_setup_env.VARS if not os.environ.get(name)]
    if missing:
        print("The following environment variables are missing:")
        for name in missing:
            print(f"  • {name}")
        print("\nLet's set them now:\n")
        for name in missing:
            se.prompt_var(name, se.VARS[name])

    # Final check
    still_missing = [n for n in se.VARS if not os.environ.get(n)]
    if still_missing:
        print(f"Error: Still missing {', '.join(still_missing)}. Exiting.")
        sys.exit(1)

def delete_old_token(path):
    if os.path.exists(path):
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            print(f"Deleted old token file: {path}")
        except Exception as e:
            print(f"Warning: could not delete {path}: {e}")

def main():
    # 1. Ensure all required env vars are present (and set them interactively if not)
    ensure_env_vars()

    # 2. Read them
    api_key      = os.environ["schwab_api_key"]
    app_secret   = os.environ["schwab_app_secret"]
    callback_url = os.environ["schwab_callback_url"]
    token_path   = os.environ["schwab_token_path"]

    # 3. Remove any existing token file or directory
    delete_old_token(token_path)

    # 4. Acquire a fresh token via manual flow
    print("\nStarting manual OAuth flow. Follow the instructions in your console...\n")
    schwab.auth.client_from_manual_flow(
        api_key,
        app_secret,
        callback_url,
        token_path
    )

    print(f"\n✅ New token saved at: {token_path}")
    sys.exit(0)

if __name__ == "__main__":
    main()

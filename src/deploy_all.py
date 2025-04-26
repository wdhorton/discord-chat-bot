#!/usr/bin/env python3
"""
Deploy script for Discord Bot and Datasette on Modal

This script deploys both the Discord bot and Datasette interface to Modal,
making it easy to handle both components at once.

Usage:
    python deploy_all.py
"""

import subprocess
import sys
import time
import os

def run_command(command, description):
    """Run a shell command and handle errors"""
    print(f"🚀 {description}...")
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"❌ Error: {result.stderr}")
        return False
    
    print(f"✅ {description} completed successfully")
    print(result.stdout)
    return True

def main():
    # Get the current directory
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Step 1: Deploy the Discord bot
    if not run_command(f"cd {current_dir} && modal deploy modal_discord_bot.py", "Deploying Discord bot"):
        sys.exit(1)
    
    # Step 2: Initialize the database on Modal
    if not run_command(f"cd {current_dir} && modal run modal_discord_bot.py::init_database", "Initializing database"):
        sys.exit(1)
    
    # Give time for the database to be created if it doesn't exist
    print("⏱️ Waiting for database to be ready...")
    time.sleep(3)
    
    # Step 3: Deploy the Datasette interface
    if not run_command(f"cd {current_dir} && modal deploy deploy_datasette.py", "Deploying Datasette interface"):
        sys.exit(1)
    
    # Step 4: Create or update slash commands
    if not run_command(f"cd {current_dir} && modal run modal_discord_bot.py::create_slash_command --args force=True", 
                      "Creating/updating Discord slash commands"):
        sys.exit(1)
    
    print("\n🎉 Deployment completed successfully!")
    print("\nImportant URLs:")
    print("1. Copy the Discord bot URL and paste it in the Discord Developer Portal")
    print("2. The Datasette interface should be available at the URL provided in the output")

if __name__ == "__main__":
    main()
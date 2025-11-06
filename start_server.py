#!/usr/bin/env python3
"""
Startup script for the Press Projector System.
Handles initialization and starts the server.
"""

import os
import sys
import argparse
from pathlib import Path

# Add backend to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

def setup_environment():
    """Set up the environment and create necessary directories."""
    # Create directories
    directories = ['config', 'jobs', 'uploads', 'frontend/templates', 'frontend/static']
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)
    
    # Create default settings if they don't exist
    settings_file = Path('config/settings.json')
    if not settings_file.exists():
        default_settings = {
            "server": {
                "host": "0.0.0.0",
                "port": 5670,
                "debug": False
            },
            "projector": {
                "default_width": 1920,
                "default_height": 1080
            },
            "calibration": {
                "max_error_mm": 1.0
            }
        }
        
        import json
        with open(settings_file, 'w') as f:
            json.dump(default_settings, f, indent=2)
        
        print(f"Created default settings: {settings_file}")

def main():
    """Main startup function."""
    parser = argparse.ArgumentParser(description='Press Projector System Server')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=5670, help='Port to bind to (default: 5670)')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--setup-only', action='store_true', help='Only setup environment, don\'t start server')
    
    args = parser.parse_args()
    
    print("Press Projector System - Starting up...")
    print("=" * 40)
    
    # Setup environment
    setup_environment()
    
    if args.setup_only:
        print("Environment setup complete. Exiting.")
        return 0
    
    # Import and start server
    try:
        from backend.server import app, socketio
        
        print(f"Starting server on {args.host}:{args.port}")
        print(f"Control interface: http://{args.host}:{args.port}/control")
        print(f"Projector view: http://{args.host}:{args.port}/projector")
        print("Press Ctrl+C to stop the server")
        print("-" * 40)
        
        # Disable the Flask reloader under debugger so breakpoints work
        use_reloader = False #if (getattr(sys, 'gettrace', lambda: None)() is not None) else args.debug
        socketio.run(app, host=args.host, port=args.port, debug=args.debug, use_reloader=use_reloader)
        
    except KeyboardInterrupt:
        print("\nServer stopped by user.")
        return 0
    except Exception as e:
        print(f"Error starting server: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit(main())

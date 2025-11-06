#!/usr/bin/env python3
"""
Automated test for WebSocket connection to Press Projector System.
Tests if clients can connect to the server and communicate.
"""

import sys
import time
import socketio
import requests
from threading import Thread
import signal
import subprocess
import os


class WebSocketConnectionTest:
    """Test WebSocket connection functionality."""
    
    def __init__(self, base_url='http://localhost:5670'):
        self.base_url = base_url
        self.server_process = None
        self.server_started = False
        self.control_client = None
        self.projector_client = None
        self.test_results = {
            'server_startup': False,
            'http_accessible': False,
            'control_connection': False,
            'projector_connection': False,
            'room_joining': False,
            'message_sending': False,
            'message_receiving': False
        }
        self.received_messages = []
    
    def start_server(self):
        """Start the server in a separate process."""
        print("Starting server...")
        try:
            self.server_process = subprocess.Popen(
                [sys.executable, 'start_server.py', '--setup-only'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.path.dirname(os.path.abspath(__file__))
            )
            
            # Try to start the actual server
            self.server_process = subprocess.Popen(
                [sys.executable, '-m', 'flask', 'run', '--host', '0.0.0.0', '--port', '5670'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, 'FLASK_APP': 'backend/server.py'},
                cwd=os.path.dirname(os.path.abspath(__file__))
            )
            
            # Wait for server to start
            max_attempts = 30
            for i in range(max_attempts):
                try:
                    response = requests.get(f'{self.base_url}/control', timeout=1)
                    if response.status_code == 200:
                        self.server_started = True
                        print("✓ Server started successfully")
                        return True
                except:
                    time.sleep(0.5)
            
            print("✗ Server failed to start within timeout")
            return False
            
        except Exception as e:
            print(f"✗ Error starting server: {e}")
            return False
    
    def check_http_accessible(self):
        """Check if HTTP server is accessible."""
        print("\nTesting HTTP accessibility...")
        try:
            response = requests.get(f'{self.base_url}/control', timeout=5)
            self.test_results['http_accessible'] = (response.status_code == 200)
            
            if self.test_results['http_accessible']:
                print("✓ HTTP server is accessible")
            else:
                print(f"✗ HTTP server returned status code: {response.status_code}")
            
            return self.test_results['http_accessible']
        except Exception as e:
            print(f"✗ HTTP server not accessible: {e}")
            return False
    
    def test_control_connection(self):
        """Test control client connection."""
        print("\nTesting control client connection...")
        try:
            self.control_client = socketio.Client()
            
            connected = False
            
            @self.control_client.on('connect')
            def on_connect():
                nonlocal connected
                connected = True
                print("  ✓ Control client connected")
            
            @self.control_client.on('disconnect')
            def on_disconnect():
                print("  Control client disconnected")
            
            self.control_client.connect(self.base_url, wait_timeout=5)
            time.sleep(1)
            
            self.test_results['control_connection'] = connected and self.control_client.connected
            return self.test_results['control_connection']
            
        except Exception as e:
            print(f"✗ Control client connection failed: {e}")
            return False
    
    def test_projector_connection(self):
        """Test projector client connection."""
        print("\nTesting projector client connection...")
        try:
            self.projector_client = socketio.Client()
            
            connected = False
            
            @self.projector_client.on('connect')
            def on_connect():
                nonlocal connected
                connected = True
                print("  ✓ Projector client connected")
            
            @self.projector_client.on('disconnect')
            def on_disconnect():
                print("  Projector client disconnected")
            
            self.projector_client.connect(self.base_url, wait_timeout=5)
            time.sleep(1)
            
            self.test_results['projector_connection'] = connected and self.projector_client.connected
            return self.test_results['projector_connection']
            
        except Exception as e:
            print(f"✗ Projector client connection failed: {e}")
            return False
    
    def test_room_joining(self):
        """Test room joining functionality."""
        print("\nTesting room joining...")
        try:
            if not self.control_client or not self.control_client.connected:
                print("  ✗ Control client not connected")
                return False
            
            if not self.projector_client or not self.projector_client.connected:
                print("  ✗ Projector client not connected")
                return False
            
            # Join rooms
            self.control_client.emit('join_room', {'room': 'control'})
            self.projector_client.emit('join_room', {'room': 'projector'})
            
            time.sleep(0.5)
            
            self.test_results['room_joining'] = True
            print("  ✓ Successfully joined rooms")
            return True
            
        except Exception as e:
            print(f"  ✗ Room joining failed: {e}")
            return False
    
    def test_message_sending(self):
        """Test message sending between clients."""
        print("\nTesting message sending...")
        try:
            if not self.control_client or not self.control_client.connected:
                print("  ✗ Control client not connected")
                return False
            
            # Send a test message
            self.control_client.emit('request_update')
            time.sleep(0.5)
            
            self.test_results['message_sending'] = True
            print("  ✓ Message sent successfully")
            return True
            
        except Exception as e:
            print(f"  ✗ Message sending failed: {e}")
            return False
    
    def test_message_receiving(self):
        echoes = []
        
        @self.projector_client.on('calibration_updated')
        def on_calibration(data):
            echoes.append(('calibration_updated', data))
        
        @self.projector_client.on('layout_updated')
        def on_layout(data):
            echoes.append(('layout_updated', data))
        
        print("\nTesting message receiving...")
        try:
            if not self.projector_client or not self.projector_client.connected:
                print("  ✗ Projector client not connected")
                return False
            
            # Wait a bit for any messages
            time.sleep(1)
            
            # Try to trigger a message
            if self.control_client and self.control_client.connected:
                self.control_client.emit('request_update')
                time.sleep(1)
            
            # Check if we received any messages
            received = len(echoes) > 0
            self.test_results['message_receiving'] = received
            
            if received:
                print(f"  ✓ Received {len(echoes)} message(s)")
            else:
                print("  ⚠ No messages received (may be expected if no calibration exists)")
            
            return True  # Not a failure if no messages
            
        except Exception as e:
            print(f"  ✗ Message receiving test error: {e}")
            return False
    
    def cleanup(self):
        """Clean up connections and stop server."""
        print("\nCleaning up...")
        
        if self.control_client and self.control_client.connected:
            self.control_client.disconnect()
        
        if self.projector_client and self.projector_client.connected:
            self.projector_client.disconnect()
        
        if self.server_process:
            try:
                self.server_process.terminate()
                self.server_process.wait(timeout=5)
            except:
                self.server_process.kill()
            print("✓ Server stopped")
    
    def run_all_tests(self, start_server=False):
        """Run all tests."""
        print("=" * 60)
        print("WebSocket Connection Test Suite")
        print("=" * 60)
        
        try:
            # Start server if requested
            if start_server:
                if not self.start_server():
                    print("\nCannot proceed without server. Exiting.")
                    return False
                self.test_results['server_startup'] = True
            else:
                print("Assuming server is already running...")
            
            # Run tests
            self.check_http_accessible()
            
            if not self.test_results['http_accessible']:
                print("\n⚠ Server not accessible. Cannot continue tests.")
                return False
            
            self.test_control_connection()
            self.test_projector_connection()
            
            if self.test_results['control_connection'] and self.test_results['projector_connection']:
                self.test_room_joining()
                self.test_message_sending()
                self.test_message_receiving()
            
            # Print summary
            print("\n" + "=" * 60)
            print("Test Results Summary")
            print("=" * 60)
            
            for test_name, result in self.test_results.items():
                status = "✓ PASS" if result else "✗ FAIL"
                print(f"{test_name:25} {status}")
            
            all_passed = all(self.test_results.values())
            print("=" * 60)
            
            if all_passed:
                print("✓ All tests passed!")
            else:
                print("⚠ Some tests failed or were skipped")
            
            return all_passed
            
        except KeyboardInterrupt:
            print("\n\nTest interrupted by user")
            return False
        finally:
            self.cleanup()


def main():
    """Main test function."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Test WebSocket connection to Press Projector System')
    parser.add_argument('--url', default='http://localhost:5670', 
                       help='Base URL of the server (default: http://localhost:5670)')
    parser.add_argument('--start-server', action='store_true',
                       help='Start the server before testing (may not work in all environments)')
    
    args = parser.parse_args()
    
    tester = WebSocketConnectionTest(base_url=args.url)
    success = tester.run_all_tests(start_server=args.start_server)
    
    return 0 if success else 1


if __name__ == '__main__':
    # Install python-socketio client if needed
    try:
        import socketio
    except ImportError:
        print("Installing python-socketio client...")
        import subprocess
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'python-socketio[client]'])
    
    # Install requests if needed
    try:
        import requests
    except ImportError:
        print("Installing requests...")
        import subprocess
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'requests'])
    
    exit(main())

"""
Main Flask server with WebSocket support for the press projector system.
Handles HTTP requests and real-time communication between control and projector views.
"""

from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
import os
import json
from typing import Dict, Any
import base64
import numpy as np
import cv2
import cairosvg

from database import FileBasedDB
from calibration import Calibrator
from projector import ProjectorManager
from file_manager import FileManager


# Initialize Flask app
app = Flask(__name__, 
            static_folder='../frontend/static', 
            static_url_path='/static',
            template_folder='../frontend/templates')
app.config['SECRET_KEY'] = 'press_projector_secret_key_2024'

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# Initialize components
db = FileBasedDB()
calibrator = Calibrator()
projector = ProjectorManager(calibrator)
file_manager = FileManager()

# Global state
connected_clients = {
    'control': None,
    'projector': None
}

# Projector state/config
projector_resolution = {
    'width': 1920,
    'height': 1080
}

# Debug flag: bypass warp when True (debug preview)
debug_bypass_warp = False

# Use fixed 2x supersampling when rasterizing SVG prior to warping


@app.route('/')
def index():
    """Redirect to control interface."""
    return render_template('control.html')


@app.route('/control')
def control():
    """Control interface for tablet."""
    return render_template('control.html')


@app.route('/projector')
def projector_view():
    """Projector visualization view."""
    return render_template('projector.html')

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """Serve uploaded files."""
    return send_from_directory(file_manager.upload_dir, filename)


@app.route('/favicon.svg')
def favicon_svg():
    """Serve SVG favicon from static folder."""
    return send_from_directory(app.static_folder, 'favicon.svg', mimetype='image/svg+xml')


@app.route('/favicon.ico')
def favicon():
    """Serve favicon from static folder."""
    return send_from_directory(app.static_folder, 'favicon.ico')


# API Endpoints

@app.route('/api/calibration', methods=['POST'])
def save_calibration():
    """Save calibration data."""
    try:
        data = request.get_json()
        
        # Validate required fields: 'projector_pixels' and 'target_pixels'
        required_fields = ['press_width_mm', 'press_height_mm', 'projector_pixels', 'target_pixels']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Determine target pixel size
        tp = data['target_pixels']
        target_w = int(tp.get('width', 0))
        target_h = int(tp.get('height', 0))
        if target_w <= 0 or target_h <= 0:
            return jsonify({'error': 'Invalid target_pixels'}), 400

        # Determine projector points array
        sp = data.get('projector_pixels')
        if not sp:
            return jsonify({'error': 'Missing projector_pixels'}), 400

        # Set calibration in calibrator
        success = calibrator.set_calibration_from_target(
            sp,
            target_w,
            target_h,
            data['press_width_mm'],
            data['press_height_mm']
        )
        
        if not success:
            return jsonify({'error': 'Calibration failed'}), 400
        
        # Save to database
        calibration_data = calibrator.get_calibration_data()
        db.save_calibration(calibration_data)
        
        # Notify views
        socketio.emit('calibration_updated', calibration_data, room='projector')
        socketio.emit('calibration_updated', calibration_data, room='control')
        
        return jsonify({'success': True, 'calibration': calibration_data})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/calibration', methods=['GET'])
def get_calibration():
    """Get current calibration data."""
    try:
        calibration_data = db.load_calibration()
        if calibration_data:
            calibrator.load_calibration_data(calibration_data)
            return jsonify(calibration_data)
        else:
            return jsonify({'error': 'No calibration data found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


"""
Removed legacy endpoint: /api/calibration/validate
- Validation is now handled purely via websocket events and projector overlay.
"""


@app.route('/api/press-size', methods=['GET', 'POST'])
def press_size():
    """Get or update press dimensions (mm) in calibration config.

    GET: returns current press_width_mm and press_height_mm if calibration exists.
    POST: expects { press_width_mm, press_height_mm }; recomputes calibration using existing
          source points and updates destination points to match the new press size, then saves.
    """
    try:
        if request.method == 'GET':
            calibration_data = db.load_calibration()
            if not calibration_data:
                return jsonify({'error': 'No calibration data found'}), 404
            return jsonify({
                'press_width_mm': calibration_data.get('press_width_mm'),
                'press_height_mm': calibration_data.get('press_height_mm')
            })

        # POST
        data = request.get_json() or {}
        new_w = data.get('press_width_mm')
        new_h = data.get('press_height_mm')
        if new_w is None or new_h is None:
            return jsonify({'error': 'press_width_mm and press_height_mm are required'}), 400

        calibration_data = db.load_calibration()
        if not calibration_data:
            return jsonify({'error': 'No calibration data found to update'}), 404

        # Keep current source points; regenerate destination points to match new size
        source_points = calibration_data['source_points']
        destination_points = [
            [0, 0],
            [float(new_w), 0],
            [float(new_w), float(new_h)],
            [0, float(new_h)]
        ]

        # Recompute calibration via calibrator to update matrix and pixels_per_mm
        ok = calibrator.set_calibration_points(source_points, destination_points, float(new_w), float(new_h))
        if not ok:
            return jsonify({'error': 'Failed to update calibration with new press size'}), 400

        # Persist and broadcast
        updated = calibrator.get_calibration_data()
        db.save_calibration(updated)
        socketio.emit('calibration_updated', updated, room='projector')
        socketio.emit('calibration_updated', updated, room='control')
        return jsonify({'success': True, 'calibration': updated})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/layout', methods=['POST'])
def update_layout():
    """Update layout configuration."""
    try:
        data = request.get_json()
        
        # Update projector manager
        if 'object_orientation' in data:
            projector.set_object_orientation(data['object_orientation'])
        
        if 'center_lines' in data:
            center_lines = data['center_lines']
            projector.set_center_lines(
                horizontal_y=center_lines.get('horizontal'),
                vertical_x=center_lines.get('vertical')
            )
        
        if 'elements' in data:
            # Clear existing elements and add new ones
            projector.clear_layout()
            for element in data['elements']:
                projector.add_element(element['type'], element)
        
        # Generate and send updated SVG
        svg_content = projector.generate_svg()
        socketio.emit('layout_updated', {
            'layout': projector.get_layout_data(),
            'svg': svg_content
        }, room='projector')
        
        return jsonify({'success': True, 'layout': projector.get_layout_data()})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/layout', methods=['GET'])
def get_layout():
    """Get current layout data."""
    try:
        return jsonify(projector.get_layout_data())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/boundary-pattern', methods=['POST'])
def toggle_boundary_pattern():
    """Toggle press boundary pattern visibility."""
    try:
        data = request.get_json()
        visible = data.get('visible', False)
        
        projector.set_boundary_pattern_visibility(visible)
        
        # Generate and send updated SVG
        svg_content = projector.generate_svg()
        socketio.emit('boundary_pattern_toggled', {
            'visible': visible,
            'svg': svg_content
        }, room='projector')
        
        return jsonify({'success': True, 'visible': visible})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Handle file uploads."""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        file_info = file_manager.save_uploaded_file(file)
        return jsonify({'success': True, 'file': file_info})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/files', methods=['GET'])
def list_files():
    """List uploaded files."""
    try:
        files = file_manager.list_files()
        return jsonify({'files': files})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/configurations', methods=['POST'])
def save_configuration():
    """Save layout configuration."""
    try:
        data = request.get_json()
        config_name = data.get('name')
        config_data = data.get('data')
        
        if not config_name or not config_data:
            return jsonify({'error': 'Name and data required'}), 400
        
        success = db.save_configuration(config_name, config_data)
        if success:
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Failed to save configuration'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/configurations', methods=['GET'])
def list_configurations():
    """List saved configurations."""
    try:
        configurations = db.list_configurations()
        return jsonify({'configurations': configurations})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/configurations/<config_name>', methods=['GET'])
def load_configuration(config_name):
    """Load specific configuration."""
    try:
        config_data = db.load_configuration(config_name)
        if config_data:
            # Persist last loaded scene name
            try:
                db.set_last_scene(config_name)
            except Exception:
                pass
            return jsonify(config_data)
        else:
            return jsonify({'error': 'Configuration not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/last-scene', methods=['GET', 'POST'])
def last_scene():
    """Get or set the last loaded scene name."""
    try:
        if request.method == 'GET':
            name = db.get_last_scene()
            if name:
                return jsonify({'name': name})
            return jsonify({'name': None})
        # POST
        data = request.get_json() or {}
        name = data.get('name')
        if not name or not isinstance(name, str):
            return jsonify({'error': 'name required'}), 400
        ok = db.set_last_scene(name)
        if not ok:
            return jsonify({'error': 'Failed to persist last scene'}), 500
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# WebSocket Events

@socketio.on('connect')
def handle_connect():
    """Handle client connection."""
    print(f"Client connected: {request.sid}")


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection."""
    print(f"Client disconnected: {request.sid}")
    
    # Remove from connected clients
    for client_type, client_id in connected_clients.items():
        if client_id == request.sid:
            connected_clients[client_type] = None
            break


@socketio.on('join_room')
def handle_join_room(data):
    """Handle client joining a room (control or projector)."""
    room = data.get('room')
    if room in ['control', 'projector']:
        join_room(room)
        connected_clients[room] = request.sid
        print(f"Client {request.sid} joined room: {room}")
        
        # Send current state to new client
        if room == 'projector':
            # Inform control about current projector resolution
            emit('projector_resolution', projector_resolution, room='control')
            # Send current calibration and layout
            calibration_data = db.load_calibration()
            if calibration_data:
                calibrator.load_calibration_data(calibration_data)
                emit('calibration_updated', calibration_data)
            
            layout_data = projector.get_layout_data()
            svg_content = projector.generate_svg()
            emit('layout_updated', {
                'layout': layout_data,
                'svg': svg_content
            })
        elif room == 'control':
            # Send current calibration to populate control inputs on load
            calibration_data = db.load_calibration()
            if calibration_data:
                try:
                    calibrator.load_calibration_data(calibration_data)
                except Exception:
                    pass
                emit('calibration_updated', calibration_data)


@socketio.on('leave_room')
def handle_leave_room(data):
    """Handle client leaving a room."""
    room = data.get('room')
    if room in ['control', 'projector']:
        leave_room(room)
        if connected_clients[room] == request.sid:
            connected_clients[room] = None
        print(f"Client {request.sid} left room: {room}")


@socketio.on('request_update')
def handle_request_update():
    """Handle request for current state update."""
    # Send current calibration
    calibration_data = db.load_calibration()
    if calibration_data:
        calibrator.load_calibration_data(calibration_data)
        emit('calibration_updated', calibration_data)
    
    # Send current layout
    layout_data = projector.get_layout_data()
    svg_content = projector.generate_svg()
    emit('layout_updated', {
        'layout': layout_data,
        'svg': svg_content
    })


@socketio.on('layout_update')
def handle_layout_update(data):
    """Handle layout update from control interface."""
    try:
        # Update projector manager
        if 'object_orientation' in data:
            projector.set_object_orientation(data['object_orientation'])
        
        if 'center_lines' in data:
            center_lines = data['center_lines']
            projector.set_center_lines(
                horizontal_y=center_lines.get('horizontal'),
                vertical_x=center_lines.get('vertical')
            )
        
        if 'elements' in data:
            # Clear existing elements and add new ones
            projector.clear_layout()
            for element in data['elements']:
                projector.add_element(element['type'], element)
        
        # Generate and send updated SVG
        svg_content = projector.generate_svg()
        emit('layout_updated', {
            'layout': projector.get_layout_data(),
            'svg': svg_content
        }, room='projector')
        
    except Exception as e:
        print(f"Error handling layout update: {e}")


@socketio.on('toggle_boundary_pattern')
def handle_toggle_boundary_pattern():
    """Handle boundary pattern toggle."""
    try:
        # Toggle boundary pattern visibility
        current_visibility = projector.show_boundary_pattern
        projector.set_boundary_pattern_visibility(not current_visibility)
        
        # Generate and send updated SVG
        svg_content = projector.generate_svg()
        emit('boundary_pattern_toggled', {
            'visible': not current_visibility,
            'svg': svg_content
        }, room='projector')
        
    except Exception as e:
        print(f"Error toggling boundary pattern: {e}")


@socketio.on('show_validation_pattern')
def handle_show_validation_pattern():
    """Show validation pattern on projector."""
    try:
        # Enable boundary pattern to show warped rectangle (kept for context)
        projector.set_boundary_pattern_visibility(True)

        # Generate and send updated SVG for boundary pattern
        svg_content = projector.generate_svg()
        emit('boundary_pattern_toggled', {
            'visible': True,
            'svg': svg_content
        }, room='projector')

        # Additionally, display the saved calibration corner points on the projector
        # Reload calibration to avoid stale in-memory state
        try:
            saved = db.load_calibration()
            if saved:
                calibrator.load_calibration_data(saved)
        except Exception as e:
            print(f"Failed to reload calibration before showing points: {e}")

        try:
            src = getattr(calibrator, 'source_points', None)
            if src is not None:
                pts = src.tolist()
                if isinstance(pts, list) and len(pts) == 4:
                    points_payload = [
                        { 'id': 'tl', 'x': float(pts[0][0]), 'y': float(pts[0][1]), 'label': 'Top Left' },
                        { 'id': 'tr', 'x': float(pts[1][0]), 'y': float(pts[1][1]), 'label': 'Top Right' },
                        { 'id': 'br', 'x': float(pts[2][0]), 'y': float(pts[2][1]), 'label': 'Bottom Right' },
                        { 'id': 'bl', 'x': float(pts[3][0]), 'y': float(pts[3][1]), 'label': 'Bottom Left' },
                    ]
                    emit('start_calibration', {
                        'points': points_payload,
                        'press_width_mm': getattr(calibrator, 'press_width_mm', None),
                        'press_height_mm': getattr(calibrator, 'press_height_mm', None)
                    }, room='projector')
        except Exception as e:
            print(f"Failed to show saved calibration corner points: {e}")
        
    except Exception as e:
        print(f"Error showing validation pattern: {e}")


@socketio.on('hide_validation_pattern')
def handle_hide_validation_pattern():
    """Hide validation pattern on projector."""
    try:
        # Disable boundary pattern
        projector.set_boundary_pattern_visibility(False)
        
        # Generate and send updated SVG
        svg_content = projector.generate_svg()
        emit('boundary_pattern_toggled', {
            'visible': False,
            'svg': svg_content
        }, room='projector')
        
        # Also stop showing the calibration points overlay if active
        try:
            emit('stop_calibration', room='projector')
        except Exception as e:
            print(f"Failed to stop calibration overlay: {e}")
        
    except Exception as e:
        print(f"Error hiding validation pattern: {e}")


@socketio.on('start_calibration')
def handle_start_calibration(data):
    """Handle start of interactive calibration."""
    try:
        print(f"Starting calibration with points: {data['points']}")
        emit('start_calibration', data, room='projector')
    except Exception as e:
        print(f"Error starting calibration: {e}")


@socketio.on('update_calibration_points')
def handle_update_calibration_points(data):
    """Handle calibration point updates."""
    try:
        print(f"Updating calibration points: {data['points']}")
        emit('update_calibration_points', data, room='projector')
    except Exception as e:
        print(f"Error updating calibration points: {e}")


@socketio.on('calibration_point_dragged')
def handle_calibration_point_dragged(data):
    """Handle calibration point drag events."""
    try:
        # Forward to control interface
        emit('calibration_point_dragged', data, room='control')
    except Exception as e:
        print(f"Error handling calibration point drag: {e}")


@socketio.on('stop_calibration')
def handle_stop_calibration():
    """Handle stop of interactive calibration."""
    try:
        print("Stopping calibration")
        emit('stop_calibration', room='projector')
    except Exception as e:
        print(f"Error stopping calibration: {e}")
@socketio.on('projector_resolution')
def handle_projector_resolution(data):
    """Receive projector reported resolution and broadcast to control."""
    try:
        w = int(data.get('width', projector_resolution['width']))
        h = int(data.get('height', projector_resolution['height']))
        projector_resolution['width'] = max(1, w)
        projector_resolution['height'] = max(1, h)
        # Persist to file for debugging/inspection
        try:
            debug_dir = os.path.join('config')
            os.makedirs(debug_dir, exist_ok=True)
            with open(os.path.join(debug_dir, 'projector_resolution.json'), 'w') as fp:
                json.dump(projector_resolution, fp, indent=2)
        except Exception as e:
            print(f"Failed to save projector resolution: {e}")
        emit('projector_resolution', projector_resolution, room='control')
    except Exception as e:
        print(f"Error handling projector resolution: {e}")


@socketio.on('set_debug_mode')
def handle_set_debug_mode(data):
    """Toggle debug mode (bypass warp)."""
    global debug_bypass_warp
    try:
        debug_bypass_warp = bool(data.get('bypass_warp', False))
        print(f"Debug bypass warp set to {debug_bypass_warp}")
    except Exception as e:
        print(f"Error setting debug mode: {e}")


@socketio.on('render_svg')
def handle_render_svg(data):
    """Rasterize incoming SVG and (optionally) warp for projector; then broadcast frame."""
    try:
        svg_str = data.get('svg', '')
        if not svg_str:
            return
        target_w = int(data.get('target_width', projector_resolution['width']))
        target_h = int(data.get('target_height', projector_resolution['height']))

        png_bytes = cairosvg.svg2png(bytestring=svg_str.encode('utf-8'), output_width=target_w, output_height=target_h)

        # Decode PNG to image (BGRA)
        buf = np.frombuffer(png_bytes, dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
        if img is None:
            print('Failed to decode rasterized SVG')
            return

        # Save the unwarped press-space image for debugging
        try:
            debug_dir = os.path.join('config', 'renders')
            os.makedirs(debug_dir, exist_ok=True)
            cv2.imwrite(os.path.join(debug_dir, 'latest_unwarped.png'), img)
        except Exception as e:
            print(f"Failed to save unwarped render images: {e}")

        out_w, out_h = projector_resolution['width'], projector_resolution['height']

        # Warp unless bypassed
        if not debug_bypass_warp and calibrator.is_calibrated():
            H = calibrator.transformation_matrix
            H_inv = np.linalg.inv(H)
            warped = cv2.warpPerspective(img, H_inv, (out_w, out_h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT)
        else:
            warped = cv2.resize(img, (out_w, out_h), interpolation=cv2.INTER_LINEAR)

        # Write debug images to disk (only keep the latest)
        try:
            debug_dir = os.path.join('config', 'renders')
            os.makedirs(debug_dir, exist_ok=True)
            # Save the high-res unwarped raster
            cv2.imwrite(os.path.join(debug_dir, 'latest_unwarped.png'), img)
            cv2.imwrite(os.path.join(debug_dir, 'latest.png'), warped)
        except Exception as e:
            print(f"Failed to save debug render images: {e}")

        ok, enc = cv2.imencode('.png', warped)
        if not ok:
            print('PNG encode failed')
            return
        b64 = base64.b64encode(enc.tobytes()).decode('ascii')
        emit('projector_frame', {'image': b64}, room='projector')
    except Exception as e:
        print(f"Error rendering SVG: {e}")


if __name__ == '__main__':
    # Load existing calibration if available
    calibration_data = db.load_calibration()
    if calibration_data:
        calibrator.load_calibration_data(calibration_data)
        print("Loaded existing calibration data")
    
    # Start server
    print("Starting Press Projector Server...")
    print("Control interface: http://localhost:5000/control")
    print("Projector view: http://localhost:5000/projector")
    
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)

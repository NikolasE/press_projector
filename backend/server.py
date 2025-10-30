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
from threading import Timer

from database import FileBasedDB
from calibration import Calibrator
from file_manager import FileManager
import types


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
# Inline projector state and functions (no new classes)
_layout_state = {
    'object_orientation': 0.0,
    'center_lines': { 'horizontal': None, 'vertical': None },
    'elements': []
}
_show_boundary_pattern = False

def pj_set_object_orientation(angle_degrees: float):
    _layout_state['object_orientation'] = float(angle_degrees or 0)

def pj_set_center_lines(horizontal_y=None, vertical_x=None):
    if horizontal_y is not None:
        _layout_state['center_lines']['horizontal'] = horizontal_y
    if vertical_x is not None:
        _layout_state['center_lines']['vertical'] = vertical_x

def pj_clear_layout():
    _layout_state['elements'] = []
    _layout_state['center_lines'] = { 'horizontal': None, 'vertical': None }
    _layout_state['object_orientation'] = 0.0

def pj_add_element(element_type: str, element_data: Dict[str, Any]):
    ed = dict(element_data)
    ed['type'] = element_type
    _layout_state['elements'].append(ed)

def pj_get_layout_data() -> Dict[str, Any]:
    return json.loads(json.dumps(_layout_state))

def pj_set_boundary_pattern_visibility(visible: bool):
    global _show_boundary_pattern
    _show_boundary_pattern = bool(visible)

def _svg_center_lines(width: int, height: int) -> str:
    lines = []
    try:
        y_mm = _layout_state['center_lines']['horizontal']
        if y_mm is not None:
            y_px = calibrator.press_to_projector(0, y_mm)[1]
            lines.append(f'<line x1="0" y1="{y_px}" x2="{width}" y2="{y_px}" class="center-line"/>')
    except Exception as e:
        print(f"center line H err: {e}")
    try:
        x_mm = _layout_state['center_lines']['vertical']
        if x_mm is not None:
            x_px = calibrator.press_to_projector(x_mm, 0)[0]
            lines.append(f'<line x1="{x_px}" y1="0" x2="{x_px}" y2="{height}" class="center-line"/>')
    except Exception as e:
        print(f"center line V err: {e}")
    return '\n'.join(lines)

def _svg_element(el: Dict[str, Any]) -> str:
    t = el.get('type')
    if t == 'rectangle':
        x_mm, y_mm = (el.get('position') or [0,0])
        w_mm = el.get('width', 10)
        h_mm = el.get('height', 10)
        rot = el.get('rotation', 0)
        color = el.get('color', '#00ffff')
        x_px, y_px = calibrator.press_to_projector(x_mm, y_mm)
        w_px, h_px = calibrator.press_to_projector(w_mm, h_mm)
        w_px = abs(w_px - calibrator.press_to_projector(0,0)[0])
        h_px = abs(h_px - calibrator.press_to_projector(0,0)[1])
        if rot:
            cx = x_px + w_px/2; cy = y_px + h_px/2
            return f'<g transform="rotate({rot} {cx} {cy})"><rect x="{x_px}" y="{y_px}" width="{w_px}" height="{h_px}" class="element-shape" stroke="{color}" fill="none"/></g>'
        return f'<rect x="{x_px}" y="{y_px}" width="{w_px}" height="{h_px}" class="element-shape" stroke="{color}" fill="none"/>'
    if t == 'circle':
        x_mm, y_mm = (el.get('position') or [0,0])
        r_mm = el.get('radius', 5)
        x_px, y_px = calibrator.press_to_projector(x_mm, y_mm)
        r_px = abs(calibrator.press_to_projector(r_mm, 0)[0] - calibrator.press_to_projector(0,0)[0])
        return f'<circle cx="{x_px}" cy="{y_px}" r="{r_px}" class="element-shape" fill="none"/>'
    if t == 'text':
        x_mm, y_mm = (el.get('position') or [0,0])
        fs = el.get('font_size', 16)
        color = el.get('color', '#ffffff')
        rot = el.get('rotation', 0)
        txt = (el.get('text') or '').replace('&','&amp;')
        x_px, y_px = calibrator.press_to_projector(x_mm, y_mm)
        if rot:
            return f'<g transform="rotate({rot} {x_px} {y_px})"><text x="{x_px}" y="{y_px}" fill="{color}" font-size="{fs}" font-family="Arial, sans-serif">{txt}</text></g>'
        return f'<text x="{x_px}" y="{y_px}" fill="{color}" font-size="{fs}" font-family="Arial, sans-serif">{txt}</text>'
    if t == 'image':
        x_mm, y_mm = (el.get('position') or [0,0])
        w_mm = el.get('width', 20)
        rot = el.get('rotation', 0)
        url = el.get('image_url', '')
        x_px, y_px = calibrator.press_to_projector(x_mm, y_mm)
        w_px = abs(calibrator.press_to_projector(w_mm, 0)[0] - calibrator.press_to_projector(0,0)[0])
        if rot:
            cx = x_px + w_px/2; cy = y_px + w_px/2
            return f'<g transform="rotate({rot} {cx} {cy})"><image x="{x_px}" y="{y_px}" width="{w_px}" height="{w_px}" xlink:href="{url}"/></g>'
        return f'<image x="{x_px}" y="{y_px}" width="{w_px}" height="{w_px}" xlink:href="{url}"/>'
    if t == 'line':
        (x1_mm,y1_mm) = (el.get('start') or [0,0]); (x2_mm,y2_mm) = (el.get('end') or [0,0])
        x1_px,y1_px = calibrator.press_to_projector(x1_mm,y1_mm)
        x2_px,y2_px = calibrator.press_to_projector(x2_mm,y2_mm)
        return f'<line x1="{x1_px}" y1="{y1_px}" x2="{x2_px}" y2="{y2_px}" class="element-shape"/>'
    return ''

def pj_generate_svg(width: int = 1920, height: int = 1080) -> str:
    if not calibrator.is_calibrated():
        return f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg"><rect width="100%" height="100%" fill="#222"/><text x="50%" y="50%" fill="#fff" text-anchor="middle">Calibration required</text></svg>'
    parts = []
    rot = _layout_state['object_orientation']
    if rot:
        cx, cy = width//2, height//2
        parts.append(f'<g transform="rotate({rot} {cx} {cy})">')
    if _show_boundary_pattern:
        parts.append(f'<rect x="10" y="10" width="{width-20}" height="{height-20}" class="boundary"/>')
    parts.append(_svg_center_lines(width, height))
    for el in _layout_state['elements']:
        svg_el = _svg_element(el)
        if svg_el:
            parts.append(svg_el)
    if rot:
        parts.append('</g>')
    styles = (
        '.center-line{stroke:#f00;stroke-width:3;stroke-dasharray:10,5}'
        '.boundary{stroke:#ff0;stroke-width:4;fill:rgba(255,255,0,0.2)}'
        '.element-shape{stroke:#0ff;stroke-width:2;fill:none}'
    )
    body = '\n'.join([p for p in parts if p])
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"><defs><style>{styles}</style></defs>{body}</svg>'

# Create a simple namespace to keep existing call sites
projector = types.SimpleNamespace(
    set_object_orientation=pj_set_object_orientation,
    set_center_lines=pj_set_center_lines,
    clear_layout=pj_clear_layout,
    add_element=pj_add_element,
    get_layout_data=pj_get_layout_data,
    set_boundary_pattern_visibility=pj_set_boundary_pattern_visibility,
    generate_svg=pj_generate_svg
)
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

# Periodic update timer
periodic_update_timer = None

# Use fixed 2x supersampling when rasterizing SVG prior to warping

def broadcast_layout_update():
    """Broadcast current layout to all projectors."""
    global periodic_update_timer
    try:
        if connected_clients['projector']:
            layout_data = projector.get_layout_data()
            svg_content = projector.generate_svg()
            socketio.emit('layout_updated', {
                'layout': layout_data,
                'svg': svg_content
            }, room='projector')
    except Exception as e:
        print(f"Error broadcasting layout update: {e}")
    
    # Schedule next update in 2 seconds
    periodic_update_timer = Timer(2.0, broadcast_layout_update)
    periodic_update_timer.start()

def start_periodic_updates():
    """Start periodic updates to projector."""
    global periodic_update_timer
    if periodic_update_timer:
        periodic_update_timer.cancel()
    periodic_update_timer = Timer(2.0, broadcast_layout_update)
    periodic_update_timer.start()

def stop_periodic_updates():
    """Stop periodic updates."""
    global periodic_update_timer
    if periodic_update_timer:
        periodic_update_timer.cancel()
        periodic_update_timer = None


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


# Removed unused /api/boundary-pattern endpoint (no callers in frontend)


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


@app.route('/api/files/<filename>/base64', methods=['GET'])
def get_file_base64(filename):
    """Get file as base64 encoded data URL."""
    try:
        filepath = os.path.join(file_manager.upload_dir, filename)
        if not os.path.exists(filepath):
            return jsonify({'error': 'File not found'}), 404
        
        # Read file and encode as base64
        with open(filepath, 'rb') as f:
            file_data = f.read()
        
        # Get file extension to determine MIME type
        ext = filename.rsplit('.', 1)[-1].lower()
        mime_types = {
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'svg': 'image/svg+xml'
        }
        mime_type = mime_types.get(ext, 'application/octet-stream')
        
        b64_data = base64.b64encode(file_data).decode('ascii')
        data_url = f'data:{mime_type};base64,{b64_data}'
        
        return jsonify({'data_url': data_url})
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
    
    # Send current layout to projector room
    layout_data = projector.get_layout_data()
    svg_content = projector.generate_svg()
    emit('layout_updated', {
        'layout': layout_data,
        'svg': svg_content
    }, room='projector')


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


# @socketio.on('toggle_boundary_pattern')
# def handle_toggle_boundary_pattern():
#     """Handle boundary pattern toggle."""
#     try:
#         # Toggle boundary pattern visibility
#         current_visibility = projector.show_boundary_pattern
#         projector.set_boundary_pattern_visibility(not current_visibility)
        
#         # Generate and send updated SVG
#         svg_content = projector.generate_svg()
#         emit('boundary_pattern_toggled', {
#             'visible': not current_visibility,
#             'svg': svg_content
#         }, room='projector')
        
#     except Exception as e:
#         print(f"Error toggling boundary pattern: {e}")


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
    print(f"Rendering SVG: {data}")
    """Rasterize incoming SVG and (optionally) warp for projector; then broadcast frame."""
    try:
        svg_str = data.get('svg', '')
        if not svg_str:
            return
        target_w = int(data.get('target_width', projector_resolution['width']))
        target_h = int(data.get('target_height', projector_resolution['height']))

        # Convert image URLs under /uploads/ to base64 data URIs for rasterization
        import re
        def encode_filename_to_data_url(filename):
            filepath = os.path.join(file_manager.upload_dir, filename)
            if os.path.exists(filepath):
                try:
                    # Read image file
                    with open(filepath, 'rb') as f:
                        img_data = f.read()
                    
                    # Determine MIME type from extension
                    ext = filename.rsplit('.', 1)[-1].lower()
                    mime_types = {
                        'png': 'image/png',
                        'jpg': 'image/jpeg',
                        'jpeg': 'image/jpeg',
                        'svg': 'image/svg+xml'
                    }
                    mime_type = mime_types.get(ext, 'image/png')
                    
                    # Encode as base64
                    b64_data = base64.b64encode(img_data).decode('ascii')
                    data_url = f'data:{mime_type};base64,{b64_data}'
                    
                    return data_url
                except Exception as e:
                    print(f"Error encoding image {filename}: {e}")
                    return None
            else:
                return None
        
        def replace_xlink_relative(match):
            filename = match.group(1)
            data_url = encode_filename_to_data_url(filename)
            return f'xlink:href="{data_url}"' if data_url else match.group(0)
        
        def replace_xlink_absolute(match):
            filename = match.group(1)
            data_url = encode_filename_to_data_url(filename)
            return f'xlink:href="{data_url}"' if data_url else match.group(0)
        
        def replace_href_relative(match):
            filename = match.group(1)
            data_url = encode_filename_to_data_url(filename)
            return f'href="{data_url}"' if data_url else match.group(0)
        
        def replace_href_absolute(match):
            filename = match.group(1)
            data_url = encode_filename_to_data_url(filename)
            return f'href="{data_url}"' if data_url else match.group(0)
        
        svg_processed = svg_str
        # xlink:href with relative /uploads/
        svg_processed = re.sub(r'xlink:href="/uploads/([^"]+)"', replace_xlink_relative, svg_processed)
        # xlink:href with absolute http(s)://.../uploads/
        svg_processed = re.sub(r'xlink:href="https?://[^\"]+/uploads/([^"]+)"', replace_xlink_absolute, svg_processed)
        # href with relative /uploads/
        svg_processed = re.sub(r'href="/uploads/([^"]+)"', replace_href_relative, svg_processed)
        # href with absolute http(s)://.../uploads/
        svg_processed = re.sub(r'href="https?://[^\"]+/uploads/([^"]+)"', replace_href_absolute, svg_processed)
        
        # Save SVG to disk before rasterizing (with pretty printing)
        try:
            import xml.dom.minidom
            debug_dir = os.path.join('config', 'renders')
            os.makedirs(debug_dir, exist_ok=True)
            svg_filepath = os.path.join(debug_dir, 'latest.svg')
            
            # Parse and pretty-print the SVG
            dom = xml.dom.minidom.parseString(svg_processed.encode('utf-8'))
            pretty_svg = dom.toprettyxml(indent="  ", encoding=None)
            
            with open(svg_filepath, 'w', encoding='utf-8') as f:
                f.write(pretty_svg)
        except Exception as e:
            print(f"Failed to save SVG to disk: {e}")

        png_bytes = cairosvg.svg2png(bytestring=svg_processed.encode('utf-8'), output_width=target_w, output_height=target_h)

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
    
    # Start periodic updates
    start_periodic_updates()
    print("Started periodic layout updates (every 2 seconds)")
    
    # Start server
    print("Starting Press Projector Server...")
    print("Control interface: http://localhost:5000/control")
    print("Projector view: http://localhost:5000/projector")
    
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)

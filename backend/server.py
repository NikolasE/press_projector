"""
Main Flask server with WebSocket support for the press projector system.
Handles HTTP requests and real-time communication between control and projector views.
"""

from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
import os
import sys
import json
from typing import Dict, Any, Optional
from enum import Enum
import base64
import numpy as np
import cv2
import cairosvg
from threading import Timer
import re
import logging
from pathlib import Path

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

# Configure logging to both file and console
os.makedirs('debug', exist_ok=True)
log_format = '%(asctime)s %(levelname)s %(name)s %(message)s'

# Configure root logger - remove existing handlers first
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
# Clear any existing handlers to avoid duplicates
for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)

# File handler
file_handler = logging.FileHandler(
    filename=os.path.join('debug', 'press_projector.log'),
    mode='a'
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter(log_format))

# Console handler (terminal output) - use sys.stdout explicitly
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter(log_format))

# Add handlers to root logger
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

# Also configure Flask's logger
flask_logger = logging.getLogger('werkzeug')
flask_logger.setLevel(logging.INFO)
for handler in flask_logger.handlers[:]:
    flask_logger.removeHandler(handler)
flask_logger.addHandler(file_handler)
flask_logger.addHandler(console_handler)

logger = logging.getLogger(__name__)
logger.info("Logging configured - file and console output enabled")

# Initialize components
db = FileBasedDB()
# Multi-press calibrators
_press_calibrators = {
    'press1': Calibrator(),
    'press2': Calibrator()
}
_active_press = 'press1'  # Current active press for calibration/layout operations
# Inline projector state and functions (no new classes)
_layout_state = {
    'object_orientation': 0.0,
    'center_lines': { 'horizontal': None, 'vertical': None },
    'elements': []
}
_show_boundary_pattern = False

# Operation mode enumeration
class OperationMode(str, Enum):
    SCENE_SETUP = 'scene_setup'
    PRODUCTION = 'production'


# Operation mode state - scenes loaded per press
_operation_state = {
    'press1': {'scene_name': None, 'layout_data': None},
    'press2': {'scene_name': None, 'layout_data': None}
}


def _determine_operation_mode_from_state() -> OperationMode:
    operation_mode_active = any(
        _operation_state.get(press_id, {}).get('layout_data')
        for press_id in ['press1', 'press2']
    )
    return OperationMode.PRODUCTION if operation_mode_active else OperationMode.SCENE_SETUP


def _parse_operation_mode(value: Any) -> Optional[OperationMode]:
    if isinstance(value, OperationMode):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        for mode in OperationMode:
            if normalized == mode.value:
                return mode
        return None
    if isinstance(value, bool):
        # Backwards compatibility with legacy boolean payloads
        return OperationMode.PRODUCTION if value else OperationMode.SCENE_SETUP
    return None

# Press management functions
def get_active_press() -> str:
    """Get current active press ID."""
    return _active_press

def set_active_press(press_id: str) -> bool:
    """Set active press ID."""
    global _active_press
    if press_id in _press_calibrators:
        _active_press = press_id
        return True
    return False

def get_calibrator(press_id: str = None) -> Calibrator:
    """Get calibrator for specific press or active press."""
    if press_id is None:
        press_id = _active_press
    return _press_calibrators.get(press_id, _press_calibrators['press1'])

def load_press_calibration(press_id: str) -> bool:
    """Load calibration data for a specific press."""
    try:
        calibration_data = db.load_press_calibration(press_id)
        if calibration_data:
            calibrator = get_calibrator(press_id)
            return calibrator.load_calibration_data(calibration_data)
        return False
    except Exception as e:
        logger.exception("Error loading calibration for press %s", press_id)
        return False

def pj_set_object_orientation(angle_degrees: float):
    _layout_state['object_orientation'] = float(angle_degrees or 0)

def pj_set_center_lines(horizontal_y=None, vertical_x=None):
    if horizontal_y is not None:
        _layout_state['center_lines']['horizontal'] = horizontal_y
    if vertical_x is not None:
        _layout_state['center_lines']['vertical'] = vertical_x

def pj_clear_layout():
    # Only clear elements; preserve center lines and object orientation
    _layout_state['elements'] = []

def pj_add_element(element_type: str, element_data: Dict[str, Any]):
    ed = dict(element_data)
    ed['type'] = element_type
    _layout_state['elements'].append(ed)

def pj_get_layout_data() -> Dict[str, Any]:
    return json.loads(json.dumps(_layout_state))

def pj_set_boundary_pattern_visibility(visible: bool):
    global _show_boundary_pattern
    _show_boundary_pattern = bool(visible)

def _svg_center_lines(width_mm: float, height_mm: float) -> str:
    """Generate center lines in press space (mm)."""
    lines = []
    try:
        y_mm = _layout_state['center_lines']['horizontal']
        if y_mm is not None:
            lines.append(f'<line x1="0" y1="{y_mm}" x2="{width_mm}" y2="{y_mm}" class="center-line"/>')
    except Exception as e:
        logger.exception("center line H err")
    try:
        x_mm = _layout_state['center_lines']['vertical']
        if x_mm is not None:
            lines.append(f'<line x1="{x_mm}" y1="0" x2="{x_mm}" y2="{height_mm}" class="center-line"/>')
    except Exception as e:
        logger.exception("center line V err")
    return '\n'.join(lines)

def _svg_element(el: Dict[str, Any]) -> str:
    """Generate SVG element in press space (mm coordinates)."""
    t = el.get('type')
    if t == 'rectangle':
        x_mm, y_mm = (el.get('position') or [0,0])
        w_mm = el.get('width', 10)
        h_mm = el.get('height', 10)
        rot = el.get('rotation', 0)
        color = el.get('color', '#00ffff')
        if rot:
            cx = x_mm + w_mm/2; cy = y_mm + h_mm/2
            return f'<g transform="rotate({rot} {cx} {cy})"><rect x="{x_mm}" y="{y_mm}" width="{w_mm}" height="{h_mm}" class="element-shape" stroke="{color}" fill="none"/></g>'
        return f'<rect x="{x_mm}" y="{y_mm}" width="{w_mm}" height="{h_mm}" class="element-shape" stroke="{color}" fill="none"/>'
    if t == 'circle':
        x_mm, y_mm = (el.get('position') or [0,0])
        r_mm = el.get('radius', 5)
        return f'<circle cx="{x_mm}" cy="{y_mm}" r="{r_mm}" class="element-shape" fill="none"/>'
    if t == 'text':
        x_mm, y_mm = (el.get('position') or [0,0])
        fs = el.get('font_size', 10)
        color = el.get('color', '#0ff')
        rot = el.get('rotation', 0)
        txt = (el.get('text') or '').replace('&','&amp;')
        baseline_y = y_mm
        text_attrs = f'x="{x_mm}" y="{baseline_y}" fill="{color}" font-size="{fs}" font-family="Arial, sans-serif" alignment-baseline="hanging"'
        if rot:
            return f'<g transform="rotate({rot} {x_mm} {baseline_y})"><text {text_attrs}>{txt}</text></g>'
        return f'<text {text_attrs}>{txt}</text>'
    if t == 'image':
        x_mm, y_mm = (el.get('position') or [0,0])
        w_mm = el.get('width', 20)
        rot = el.get('rotation', 0)
        url = el.get('image_url', '')
        # Determine image aspect ratio if possible
        h_mm = w_mm
        try:
            aspect = get_image_aspect_ratio_from_url(url)
            if aspect and aspect > 0:
                h_mm = float(w_mm) * float(aspect)
        except Exception as e:
            logger.exception("Failed to compute image aspect ratio for %s", url)
            h_mm = w_mm
        if rot:
            cx = x_mm + w_mm/2; cy = y_mm + h_mm/2
            return f'<g transform="rotate({rot} {cx} {cy})"><image x="{x_mm}" y="{y_mm}" width="{w_mm}" height="{h_mm}" xlink:href="{url}"/></g>'
        return f'<image x="{x_mm}" y="{y_mm}" width="{w_mm}" height="{h_mm}" xlink:href="{url}"/>'
    if t == 'line':
        (x1_mm,y1_mm) = (el.get('start') or [0,0]); (x2_mm,y2_mm) = (el.get('end') or [0,0])
        return f'<line x1="{x1_mm}" y1="{y1_mm}" x2="{x2_mm}" y2="{y2_mm}" class="element-shape"/>'
    return ''

def pj_generate_svg(width: int = 1920,
                    height: int = 1080,
                    press_id: str = None,
                    operation_mode: OperationMode = OperationMode.SCENE_SETUP) -> str:
    """Generate SVG for a single press (press space in mm).
    Uses per-press operation layout if available; otherwise falls back to the global layout state."""
    
    # Single press mode
    # Ensure press_id is set (default to active press)
    if press_id is None:
        press_id = _active_press
    
    # Ensure calibration is loaded for this press
    calibrator = get_calibrator(press_id)
    if not calibrator.is_calibrated():
        # Try to load calibration if not already loaded
        load_press_calibration(press_id)
        if not calibrator.is_calibrated():
            logger.warning(f"Calibration not available for {press_id} when generating SVG")
            return f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg"><rect width="100%" height="100%" fill="#222"/><text x="50%" y="50%" fill="#fff" text-anchor="middle">Calibration required</text></svg>'
    
    # Get press dimensions in mm
    press_width_mm = calibrator.press_width_mm
    press_height_mm = calibrator.press_height_mm
    
    # Prefer per-press operation layout if available in production mode
    op_layout = None
    if operation_mode is OperationMode.PRODUCTION and press_id:
        op_layout = _operation_state.get(press_id, {}).get('layout_data')
    layout_src = op_layout or _layout_state
    
    parts = []
    rot = layout_src.get('object_orientation', 0.0)
    if rot:
        cx, cy = press_width_mm/2, press_height_mm/2
        parts.append(f'<g transform="rotate({rot} {cx} {cy})">')
    if _show_boundary_pattern:
        parts.append(f'<rect x="0" y="0" width="{press_width_mm}" height="{press_height_mm}" class="boundary"/>')
    # Render center lines from the chosen layout source
    try:
        prev_center = _layout_state.get('center_lines')
        _layout_state['center_lines'] = (layout_src.get('center_lines') or {'horizontal': None, 'vertical': None})
        parts.append(_svg_center_lines(press_width_mm, press_height_mm))
    finally:
        _layout_state['center_lines'] = prev_center
    
    for el in (layout_src.get('elements') or []):
        svg_el = _svg_element(el)
        if svg_el:
            parts.append(svg_el)
    if rot:
        parts.append('</g>')
    styles = (
        '.center-line{stroke:#f00;stroke-width:5;stroke-dasharray:10,5}'
        '.boundary{stroke:#ff0;stroke-width:4;fill:rgba(255,255,0,0.2)}'
        '.element-shape{stroke:#0ff;stroke-width:2;fill:none}'
    )
    body = '\n'.join([p for p in parts if p])
    # SVG viewBox and dimensions in mm
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<svg width="{press_width_mm}mm" height="{press_height_mm}mm" viewBox="0 0 {press_width_mm} {press_height_mm}" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"><defs><style>{styles}</style></defs>{body}</svg>'

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

# Render coalescing state: drop intermediate renders while one is in progress
is_rendering = False
pending_render = None


def encode_filename_to_data_url(filename: str):
    """Encode an uploaded image filename to a base64 data URL if it exists."""
    filepath = os.path.join(file_manager.upload_dir, filename)
    if os.path.exists(filepath):
        try:
            with open(filepath, 'rb') as f:
                img_data = f.read()
            ext = filename.rsplit('.', 1)[-1].lower()
            mime_types = {
                'png': 'image/png',
                'jpg': 'image/jpeg',
                'jpeg': 'image/jpeg',
                'svg': 'image/svg+xml'
            }
            mime_type = mime_types.get(ext, 'image/png')
            b64_data = base64.b64encode(img_data).decode('ascii')
            return f'data:{mime_type};base64,{b64_data}'
        except Exception as e:
            print(f"Error encoding image {filename}: {e}")
            return None
    return None

def inline_upload_image_links(svg_str: str) -> str:
    """Replace href/xlink:href that point to /uploads with data URLs."""
    def repl(match):
        attr = match.group(1)
        filename = match.group(2)
        data_url = encode_filename_to_data_url(filename)
        return f'{attr}="{data_url}"' if data_url else match.group(0)

    pattern = r'(xlink:href|href)="(?:(?:https?://[^\"]+)?/)?uploads/([^"]+)"'
    return re.sub(pattern, repl, svg_str)

def extract_upload_filename(url: str):
    """Extract filename from a URL that points to uploads, handling absolute/relative forms."""
    if not isinstance(url, str) or not url:
        return None
    if 'data:' in url:
        return None
    marker = '/uploads/'
    if marker in url:
        return url.split(marker, 1)[1]
    # handle 'uploads/...' without leading slash
    if 'uploads/' in url:
        return url.split('uploads/', 1)[1]
    return None

def get_image_aspect_ratio_from_url(url: str):
    """Return height/width aspect ratio for an uploaded image URL, or None if unavailable."""
    fname = extract_upload_filename(url)
    if not fname:
        return None
    try:
        path = os.path.join(file_manager.upload_dir, fname)
        if os.path.exists(path):
            img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if img is not None and img.shape[1] > 0:
                return float(img.shape[0]) / float(img.shape[1])
    except Exception as e:
        print(f"Failed to read image for aspect ratio {url}: {e}")
    return None

def adjust_upload_image_heights(svg_str: str) -> str:
    """Ensure <image> elements referencing uploads have height set by aspect ratio.
    Uses element width and measured image aspect to compute height in the same units.
    """
    def replace_image_tag(match: re.Match) -> str:
        tag = match.group(0)
        # Find href within this tag
        href_m = re.search(r'(?:xlink:href|href)="([^"]+)"', tag)
        if not href_m:
            return tag
        url = href_m.group(1)
        aspect = get_image_aspect_ratio_from_url(url)
        if not aspect or aspect <= 0:
            return tag
        # Find width value
        w_m = re.search(r'\bwidth="([0-9]+(?:\.[0-9]+)?)"', tag)
        if not w_m:
            return tag
        try:
            w_val = float(w_m.group(1))
        except Exception:
            return tag
        h_val = w_val * float(aspect)
        # Replace or add height attribute with computed value
        if re.search(r'\bheight="', tag):
            tag = re.sub(r'\bheight="[0-9]+(?:\.[0-9]+)?"', f'height="{h_val}"', tag)
        else:
            # Insert before closing
            tag = re.sub(r'/?>$', f' height="{h_val}"\g<0>', tag)
        # Also fix rotation centers if present (optional: leave as-is; projector warping uses pixel image)
        return tag
    # Only process <image ...> tags
    return re.sub(r'<image\b[^>]*?>', replace_image_tag, svg_str)

def save_debug_png(image: np.ndarray, filename: str) -> str:
    """Save a PNG image to debug/renders with the given filename.

    Args:
        image: Image array (BGR or BGRA) to write as PNG
        filename: Target filename, e.g. 'latest.png'

    Returns:
        The file path on success, or None if saving failed.
    """
    try:
        debug_dir = os.path.join('debug', 'renders')
        os.makedirs(debug_dir, exist_ok=True)
        filepath = os.path.join(debug_dir, Path(filename).with_suffix('.png'))
        ok = cv2.imwrite(filepath, image)
        if not ok:
            logger.warning("cv2.imwrite returned False for %s", filepath)
            return None
        return filepath

    except Exception:
        logger.exception("Failed to save debug PNG '%s'", filename)
        return None

def save_debug_svg(svg_content: str, filename: str = 'latest.svg') -> str:
    """Save an SVG to debug/renders with the given filename.

    Args:
        svg_content: SVG content to save
        filename: Target filename, e.g. 'latest.svg'

    Returns:
        The file path on success, or None if saving failed.
    """
    try:
        import xml.dom.minidom
        debug_dir = os.path.join('debug', 'renders')
        os.makedirs(debug_dir, exist_ok=True)
        filepath = os.path.join(debug_dir, Path(filename).with_suffix('.svg'))

        # Parse and pretty-print the SVG
        dom = xml.dom.minidom.parseString(svg_content.encode('utf-8'))
        pretty_svg = dom.toprettyxml(indent="  ", encoding=None)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(pretty_svg)

        return filepath
    except Exception as e:
        logger.exception("Failed to save SVG to disk: %s", e)
        return None


def send_layout_update_to_control(layout_data: Dict[str, Any],
                                  svg_content: str,
                                  operation_mode: OperationMode = OperationMode.SCENE_SETUP) -> None:
    socketio.emit('layout_updated', {
        'layout': layout_data,
        'svg': svg_content,
        'operation_mode': operation_mode.value
    }, room='control')

def broadcast_layout_update():
    """Broadcast current layout to all projectors."""
    global periodic_update_timer
    try:
        mode = _determine_operation_mode_from_state()

        if mode is OperationMode.PRODUCTION:
            # Operation mode: generate multi-press SVG
            svg_content = projector.generate_svg(operation_mode=mode)
            try:
                save_debug_svg(svg_content, 'operation_latest.svg')
            except Exception:
                pass
            # Send to control for preview
            socketio.emit('layout_updated', {
                'layout': None,  # Operation mode doesn't use _layout_state
                'svg': svg_content,
                'operation_mode': mode.value
            }, room='control')
        else:
            # Normal mode: send current layout
            layout_data = projector.get_layout_data()
            svg_content = projector.generate_svg(operation_mode=mode)
            try:
                save_debug_svg(svg_content, 'control_latest.svg')
            except Exception:
                pass
            send_layout_update_to_control(layout_data, svg_content, mode)
    except Exception as e:
        logger.exception("Error broadcasting layout update")
    
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
    """Save calibration data for active press."""
    try:
        data = request.get_json()
        
        # Get press_id from request or use active press
        press_id = data.get('press_id', _active_press)
        if press_id not in _press_calibrators:
            return jsonify({'error': f'Invalid press_id: {press_id}'}), 400
        
        # Validate required fields
        required_fields = ['press_width_mm', 'press_height_mm', 'projector_pixels']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
    

        # Determine projector points array
        sp = data.get('projector_pixels')
        if not sp:
            return jsonify({'error': 'Missing projector_pixels'}), 400

        # Set calibration in press-specific calibrator
        calibrator = get_calibrator(press_id)
        success = calibrator.set_calibration_from_target(
            sp,
            data['press_width_mm'],
            data['press_height_mm']
        )
        
        if not success:
            return jsonify({'error': 'Calibration failed'}), 400
        
        # Save to database
        calibration_data = calibrator.get_calibration_data()
        db.save_press_calibration(press_id, calibration_data)
        
        # Notify views
        socketio.emit('press_calibration_updated', {
            'press_id': press_id,
            'calibration_data': calibration_data
        }, room='projector')
        socketio.emit('press_calibration_updated', {
            'press_id': press_id,
            'calibration_data': calibration_data
        }, room='control')
        
        return jsonify({'success': True, 'calibration': calibration_data, 'press_id': press_id})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/calibration', methods=['GET'])
def get_calibration():
    """Get calibration data for active press or specified press."""
    try:
        # Get press_id from query parameter or use active press
        press_id = request.args.get('press_id', _active_press)
        if press_id not in _press_calibrators:
            return jsonify({'error': f'Invalid press_id: {press_id}'}), 400
        
        calibration_data = db.load_press_calibration(press_id)
        if calibration_data:
            calibrator = get_calibrator(press_id)
            calibrator.load_calibration_data(calibration_data)
            return jsonify(calibration_data)
        else:
            return jsonify({'error': f'No calibration data found for {press_id}'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


"""
Removed legacy endpoint: /api/calibration/validate
- Validation is now handled purely via websocket events and projector overlay.
"""


@app.route('/api/presses', methods=['GET'])
def list_presses():
    """List all configured press IDs."""
    try:
        presses = db.list_presses()
        # Ensure press1 and press2 are always available
        all_presses = ['press1', 'press2']
        return jsonify({'presses': all_presses, 'configured': presses})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/presses', methods=['POST'])
def create_press():
    """Create a new press (press2 only, press1 always exists)."""
    try:
        data = request.get_json() or {}
        press_id = data.get('press_id', 'press2')
        
        if press_id not in ['press1', 'press2']:
            return jsonify({'error': f'Invalid press_id: {press_id}. Only press1 and press2 are supported.'}), 400
        
        # Check if press already exists
        calibration_data = db.load_press_calibration(press_id)
        if calibration_data:
            return jsonify({'error': f'Press {press_id} already exists'}), 400
        
        # Press is created implicitly when calibration is saved
        # Just return success
        socketio.emit('press_created', {'press_id': press_id}, room='control')
        socketio.emit('press_created', {'press_id': press_id}, room='projector')
        return jsonify({'success': True, 'press_id': press_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/presses/<press_id>', methods=['DELETE'])
def delete_press_endpoint(press_id: str):
    """Delete a press and its calibration."""
    try:
        if press_id == 'press1':
            return jsonify({'error': 'Cannot delete press1'}), 400
        
        if press_id not in _press_calibrators:
            return jsonify({'error': f'Invalid press_id: {press_id}'}), 400
        
        success = db.delete_press(press_id)
        if success:
            # Reset calibrator for this press
            _press_calibrators[press_id] = Calibrator()
            socketio.emit('press_deleted', {'press_id': press_id}, room='control')
            socketio.emit('press_deleted', {'press_id': press_id}, room='projector')
            return jsonify({'success': True})
        else:
            return jsonify({'error': f'Failed to delete press {press_id}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/presses/<press_id>/calibration', methods=['POST'])
def save_press_calibration_endpoint(press_id: str):
    """Save calibration for a specific press."""
    try:
        if press_id not in _press_calibrators:
            return jsonify({'error': f'Invalid press_id: {press_id}'}), 400
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No calibration data provided'}), 400
        
        # Validate required fields
        required_fields = ['press_width_mm', 'press_height_mm', 'projector_pixels']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Set calibration
        calibrator = get_calibrator(press_id)
        success = calibrator.set_calibration_from_target(
            data['projector_pixels'],
            data['press_width_mm'],
            data['press_height_mm']
        )
        
        if not success:
            return jsonify({'error': 'Calibration failed'}), 400
        
        # Save to database
        calibration_data = calibrator.get_calibration_data()
        db.save_press_calibration(press_id, calibration_data)
        
        # Notify views
        socketio.emit('press_calibration_updated', {
            'press_id': press_id,
            'calibration_data': calibration_data
        }, room='projector')
        socketio.emit('press_calibration_updated', {
            'press_id': press_id,
            'calibration_data': calibration_data
        }, room='control')
        
        return jsonify({'success': True, 'calibration': calibration_data, 'press_id': press_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/presses/<press_id>/calibration', methods=['GET'])
def get_press_calibration_endpoint(press_id: str):
    """Get calibration for a specific press."""
    try:
        if press_id not in _press_calibrators:
            return jsonify({'error': f'Invalid press_id: {press_id}'}), 400
        
        calibration_data = db.load_press_calibration(press_id)
        if calibration_data:
            calibrator = get_calibrator(press_id)
            calibrator.load_calibration_data(calibration_data)
            return jsonify(calibration_data)
        else:
            return jsonify({'error': f'No calibration data found for {press_id}'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/active-press', methods=['GET', 'POST'])
def active_press():
    """Get or set the active press."""
    try:
        if request.method == 'GET':
            return jsonify({'press_id': _active_press})
        
        # POST
        data = request.get_json() or {}
        press_id = data.get('press_id')
        if not press_id:
            return jsonify({'error': 'press_id required'}), 400
        
        if set_active_press(press_id):
            socketio.emit('active_press_changed', {'press_id': press_id}, room='control')
            socketio.emit('active_press_changed', {'press_id': press_id}, room='projector')
            return jsonify({'success': True, 'press_id': press_id})
        else:
            return jsonify({'error': f'Invalid press_id: {press_id}'}), 400
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
            print(f"[REST /api/layout] incoming center_lines: {center_lines}")
            projector.set_center_lines(
                horizontal_y=center_lines.get('horizontal'),
                vertical_x=center_lines.get('vertical')
            )
            print(f"[REST /api/layout] stored center_lines: {_layout_state['center_lines']}")
        
        if 'elements' in data:
            # Clear existing elements and add new ones
            projector.clear_layout()
            for element in data['elements']:
                projector.add_element(element['type'], element)
        
        # Generate and send updated SVG
        svg_content = projector.generate_svg()
        try:
            save_debug_svg(svg_content, 'layout_update_latest.svg')
        except Exception:
            pass
        # Notify control UI only; projector consumes rasterized frames
        try:
            send_layout_update_to_control(projector.get_layout_data(), svg_content, OperationMode.SCENE_SETUP)
        except Exception:
            pass
        # Ensure calibration overlay is not shown during normal edits
        try:
            socketio.emit('stop_calibration', room='projector')
        except Exception:
            pass
        
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


def convert_absolute_to_relative(layout_data: Dict[str, Any]) -> Dict[str, Any]:
    """Convert absolute positions to design-center-relative coordinates."""
    center_lines = layout_data.get('center_lines', {})
    center_x = center_lines.get('vertical')
    center_y = center_lines.get('horizontal')
    
    if center_x is None or center_y is None:
        # No center lines defined, keep absolute positions
        return layout_data
    
    # Create new layout with relative coordinates
    relative_layout = {
        'object_orientation': layout_data.get('object_orientation', 0.0),
        'center_lines': {
            'horizontal': center_y,  # Store absolute position
            'vertical': center_x     # Store absolute position
        },
        'elements': []
    }
    
    # Convert element positions to relative to center lines
    for el in layout_data.get('elements', []):
        rel_el = dict(el)
        if 'position' in rel_el:
            x_abs, y_abs = rel_el['position']
            rel_el['position'] = [x_abs - center_x, y_abs - center_y]
        if 'start' in rel_el:
            x1_abs, y1_abs = rel_el['start']
            rel_el['start'] = [x1_abs - center_x, y1_abs - center_y]
        if 'end' in rel_el:
            x2_abs, y2_abs = rel_el['end']
            rel_el['end'] = [x2_abs - center_x, y2_abs - center_y]
        relative_layout['elements'].append(rel_el)
    
    return relative_layout


def convert_relative_to_absolute(scene_data: Dict[str, Any]) -> Dict[str, Any]:
    """Convert design-center-relative coordinates to absolute positions for active press."""
    center_lines = scene_data.get('center_lines', {})
    center_x = center_lines.get('vertical')
    center_y = center_lines.get('horizontal')
    
    if center_x is None or center_y is None:
        # No center lines defined, keep relative positions
        return scene_data
    
    # Create absolute layout
    absolute_layout = {
        'object_orientation': scene_data.get('object_orientation', 0.0),
        'center_lines': {
            'horizontal': center_y,
            'vertical': center_x
        },
        'elements': []
    }
    
    # Convert element positions from relative to absolute
    for el in scene_data.get('elements', []):
        abs_el = dict(el)
        if 'position' in abs_el:
            x_rel, y_rel = abs_el['position']
            abs_el['position'] = [x_rel + center_x, y_rel + center_y]
        if 'start' in abs_el:
            x1_rel, y1_rel = abs_el['start']
            abs_el['start'] = [x1_rel + center_x, y1_rel + center_y]
        if 'end' in abs_el:
            x2_rel, y2_rel = abs_el['end']
            abs_el['end'] = [x2_rel + center_x, y2_rel + center_y]
        absolute_layout['elements'].append(abs_el)
    
    return absolute_layout


@app.route('/api/configurations', methods=['POST'])
def save_configuration():
    """Save layout configuration in design-center coordinate system."""
    try:
        data = request.get_json()
        config_name = data.get('name')
        config_data = data.get('data')
        
        if not config_name or not config_data:
            return jsonify({'error': 'Name and data required'}), 400
        
        # Extract layout from config_data
        layout_data = config_data.get('layout', config_data)
        
        # Convert absolute positions to design-center-relative
        relative_layout = convert_absolute_to_relative(layout_data)
        
        # Store scene with relative coordinates
        scene_data = {
            'layout': relative_layout,
            'config_name': config_name
        }
        
        success = db.save_configuration(config_name, scene_data)
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
    """Load specific configuration and convert to absolute coordinates for active press."""
    try:
        scene_data = db.load_configuration(config_name)
        if scene_data:
            # Persist last loaded scene name
            try:
                db.set_last_scene(config_name)
            except Exception:
                pass
            
            # Extract layout (may be in 'layout' key or root)
            layout_data = scene_data.get('layout', scene_data)
            
            # Convert relative coordinates to absolute for active press
            absolute_layout = convert_relative_to_absolute(layout_data)
            
            # Update layout state with converted coordinates
            if 'object_orientation' in absolute_layout:
                projector.set_object_orientation(absolute_layout['object_orientation'])
            
            if 'center_lines' in absolute_layout:
                center_lines = absolute_layout['center_lines']
                projector.set_center_lines(
                    horizontal_y=center_lines.get('horizontal'),
                    vertical_x=center_lines.get('vertical')
                )
            
            if 'elements' in absolute_layout:
                projector.clear_layout()
                for element in absolute_layout['elements']:
                    projector.add_element(element.get('type'), element)
            
            # Return both relative (for storage) and absolute (for use) versions
            result = dict(scene_data)
            result['layout'] = absolute_layout
            
            return jsonify(result)
        else:
            return jsonify({'error': 'Configuration not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/configurations/<config_name>', methods=['DELETE'])
def delete_configuration(config_name):
    """Delete a saved configuration."""
    try:
        deleted = db.delete_configuration(config_name)
        if deleted:
            try:
                last_scene = db.get_last_scene()
                if last_scene == config_name:
                    db.set_last_scene('')
            except Exception:
                pass
            return jsonify({'success': True})
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


@app.route('/api/operation/load-scene', methods=['POST'])
def operation_load_scene():
    """Load a scene for a specific press in operation mode."""
    try:
        data = request.get_json() or {}
        press_id = data.get('press_id')
        scene_name = data.get('scene_name')
        
        if not press_id or not scene_name:
            return jsonify({'error': 'press_id and scene_name required'}), 400
        
        if press_id not in _press_calibrators:
            return jsonify({'error': f'Invalid press_id: {press_id}'}), 400
        
        # Load scene configuration
        scene_data = db.load_configuration(scene_name)
        if not scene_data:
            return jsonify({'error': f'Scene not found: {scene_name}'}), 404
        
        # Extract layout (may be in 'layout' key or root)
        layout_data = scene_data.get('layout', scene_data)
        
        # Ensure press calibration is loaded
        load_press_calibration(press_id)
        
        # Convert relative coordinates to absolute for target press
        # Note: convert_relative_to_absolute uses center lines from scene, not calibration
        absolute_layout = convert_relative_to_absolute(layout_data)
        
        # Store in operation state
        _operation_state[press_id] = {
            'scene_name': scene_name,
            'layout_data': absolute_layout
        }
        
        # Broadcast operation state update
        socketio.emit('operation_state_updated', _operation_state, room='projector')
        socketio.emit('operation_state_updated', _operation_state, room='control')
        
        # Trigger render for operation mode
        try:
            svg_content = projector.generate_svg(operation_mode=OperationMode.PRODUCTION)
            socketio.emit('layout_updated', {
                'layout': None,
                'svg': svg_content,
                'operation_mode': OperationMode.PRODUCTION.value
            }, room='control')
        except Exception:
            pass
        
        return jsonify({'success': True, 'press_id': press_id, 'scene_name': scene_name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/operation/clear-scene', methods=['POST'])
def operation_clear_scene():
    """Clear a scene from a specific press in operation mode."""
    try:
        data = request.get_json() or {}
        press_id = data.get('press_id')
        
        if not press_id:
            return jsonify({'error': 'press_id required'}), 400
        
        if press_id not in _press_calibrators:
            return jsonify({'error': f'Invalid press_id: {press_id}'}), 400
        
        # Clear operation state for this press
        _operation_state[press_id] = {
            'scene_name': None,
            'layout_data': None
        }
        
        # Broadcast operation state update
        socketio.emit('operation_state_updated', _operation_state, room='projector')
        socketio.emit('operation_state_updated', _operation_state, room='control')
        
        # Trigger render for operation mode (if any scenes still loaded)
        try:
            mode = _determine_operation_mode_from_state()
            if mode is OperationMode.PRODUCTION:
                svg_content = projector.generate_svg(operation_mode=mode)
                socketio.emit('layout_updated', {
                    'layout': None,
                    'svg': svg_content,
                    'operation_mode': mode.value
                }, room='control')
        except Exception:
            pass
        
        return jsonify({'success': True, 'press_id': press_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/operation/state', methods=['GET'])
def get_operation_state():
    """Get current operation state."""
    try:
        return jsonify(_operation_state)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# WebSocket Events

@socketio.on('connect')
def handle_connect():
    """Handle client connection."""
    pass


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection."""
    pass
    
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
        pass
        
        # Send current state to new client
        if room == 'projector':
            # Inform control about current projector resolution
            emit('projector_resolution', projector_resolution, room='control')
            # Send calibrations for all presses
            for press_id in ['press1', 'press2']:
                calibration_data = db.load_press_calibration(press_id)
                if calibration_data:
                    load_press_calibration(press_id)
                    emit('press_calibration_updated', {
                        'press_id': press_id,
                        'calibration_data': calibration_data
                    })
            
            # Do not send raw SVG to projector on join; wait for rasterized frames
        elif room == 'control':
            # Send calibrations for all presses to populate control inputs on load
            for press_id in ['press1', 'press2']:
                calibration_data = db.load_press_calibration(press_id)
                if calibration_data:
                    try:
                        load_press_calibration(press_id)
                        emit('press_calibration_updated', {
                            'press_id': press_id,
                            'calibration_data': calibration_data
                        })
                    except Exception:
                        pass
            # Send active press info
            emit('active_press_changed', {'press_id': _active_press})


@socketio.on('leave_room')
def handle_leave_room(data):
    """Handle client leaving a room."""
    room = data.get('room')
    if room in ['control', 'projector']:
        leave_room(room)
        if connected_clients[room] == request.sid:
            connected_clients[room] = None
        pass


@socketio.on('request_update')
def handle_request_update():
    """Handle request for current state update."""
    # Send calibrations for all presses
    for press_id in ['press1', 'press2']:
        calibration_data = db.load_press_calibration(press_id)
        if calibration_data:
            load_press_calibration(press_id)
            emit('press_calibration_updated', {
                'press_id': press_id,
                'calibration_data': calibration_data
            })
    
    # Send active press info
    emit('active_press_changed', {'press_id': _active_press})
    
    # Send operation state
    emit('operation_state_updated', _operation_state)
    
    # Send current layout to control only; projector will wait for rasterized frame
    try:
        mode = _determine_operation_mode_from_state()

        if mode is OperationMode.PRODUCTION:
            svg_content = projector.generate_svg(operation_mode=mode)
            try:
                save_debug_svg(svg_content, 'control_latest.svg')
            except Exception:
                pass
            emit('layout_updated', {
                'layout': None,
                'svg': svg_content,
                'operation_mode': mode.value
            })
        else:
            layout_data = projector.get_layout_data()
            svg_content = projector.generate_svg(operation_mode=mode)
            try:
                save_debug_svg(svg_content, 'request_update_latest.svg')
            except Exception:
                pass
            send_layout_update_to_control(layout_data, svg_content, mode)
    except Exception as e:
        logger.exception("Error handling request_update")


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
        try:
            save_debug_svg(svg_content, 'layout_update_latest.svg')
        except Exception:
            pass
        # Notify control UI only
        try:
            send_layout_update_to_control(projector.get_layout_data(), svg_content, OperationMode.SCENE_SETUP)
        except Exception:
            pass
        # Ensure calibration overlay is not shown during normal edits
        try:
            emit('stop_calibration', room='projector')
        except Exception:
            pass
        
    except Exception as e:
        logger.exception("Error handling layout update")


 


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
        try:
            emit('set_projection_mode', { 'mode': 'svg' }, room='projector')
        except Exception:
            pass

        # Additionally, display the saved calibration corner points on the projector
        # Reload calibration to avoid stale in-memory state
        try:
            saved = db.load_press_calibration(_active_press)
            if saved:
                calibrator = get_calibrator(_active_press)
                calibrator.load_calibration_data(saved)
        except Exception as e:
            logger.exception("Failed to reload calibration before showing points")

        try:
            calibrator = get_calibrator(_active_press)
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
            logger.exception("Failed to show saved calibration corner points")
        
    except Exception as e:
        logger.exception("Error showing validation pattern")


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
        try:
            emit('set_projection_mode', { 'mode': 'frames' }, room='projector')
        except Exception:
            pass
        
        # Also stop showing the calibration points overlay if active
        try:
            emit('stop_calibration', room='projector')
        except Exception as e:
            logger.exception("Failed to stop calibration overlay")
        
    except Exception as e:
        logger.exception("Error hiding validation pattern")


@socketio.on('start_calibration')
def handle_start_calibration(data):
    """Handle start of interactive calibration."""
    try:
        press_id = data.get('press_id', 'unknown')
        logger.info(f"Starting calibration for press: {press_id}")
        emit('start_calibration', data, room='projector')
    except Exception as e:
        logger.exception("Error starting calibration")


@socketio.on('update_calibration_points')
def handle_update_calibration_points(data):
    """Handle calibration point updates."""
    try:
        emit('update_calibration_points', data, room='projector')
        emit('update_calibration_points', data, room='control')
    except Exception as e:
        logger.exception("Error updating calibration points")


@socketio.on('calibration_point_dragged')
def handle_calibration_point_dragged(data):
    """Handle calibration point drag events."""
    try:
        # Forward to control interface
        emit('calibration_point_dragged', data, room='control')
    except Exception as e:
        logger.exception("Error handling calibration point drag")


@socketio.on('calibration_point_selected')
def handle_calibration_point_selected(data):
    """Handle calibration point selection events."""
    try:
        # Forward to control interface
        emit('calibration_point_selected', data, room='control')
    except Exception as e:
        logger.exception("Error handling calibration point selection")


@socketio.on('stop_calibration')
def handle_stop_calibration():
    """Handle stop of interactive calibration."""
    try:
        emit('stop_calibration', room='projector')
    except Exception as e:
        logger.exception("Error stopping calibration")
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
            logger.exception("Failed to save projector resolution")
        emit('projector_resolution', projector_resolution, room='control')
    except Exception as e:
        logger.exception("Error handling projector resolution")


@socketio.on('set_debug_mode')
def handle_set_debug_mode(data):
    """Toggle debug mode (bypass warp)."""
    global debug_bypass_warp
    try:
        debug_bypass_warp = bool(data.get('bypass_warp', False))
    except Exception as e:
        logger.exception("Error setting debug mode")


def _render_press_scene(press_id: str, svg_str: str, output_width: int, output_height: int) -> np.ndarray:
    """
    Render a scene for a specific press and apply perspective transformation.
    
    Args:
        press_id: ID of the press to render
        svg_str: SVG string to render (in press space, mm coordinates)
        output_width: Output width in projector pixels
        output_height: Output height in projector pixels
    
    Returns:
        Warped image as numpy array (BGRA), or None if rendering failed
    """

    # Ensure calibration is loaded
    calibrator = get_calibrator(press_id)
    if not calibrator.is_calibrated():
        load_press_calibration(press_id)
        if not calibrator.is_calibrated():
            logger.warning(f"Calibration not available for {press_id}, cannot render")
            return None
    
    # Process SVG (inline images, etc.)
    svg_processed = adjust_upload_image_heights(svg_str)
    svg_processed = inline_upload_image_links(svg_processed)
    

    raw_width_px, raw_height_px = calibrator.get_raw_size_px()


    # Rasterize SVG at press-space resolution
    png_bytes = cairosvg.svg2png(bytestring=svg_processed.encode('utf-8'), 
                                  output_width=raw_width_px, 
                                  output_height=raw_height_px)
    
    # Decode PNG to image (BGRA)
    buf = np.frombuffer(png_bytes, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
    if img is None:
        logger.warning(f"Failed to decode PNG for {press_id}")
        return None

    save_debug_png(img, '_render_press_scene.png')
    save_debug_svg(svg_processed, '_render_press_scene.svg')
    
    
    # # Ensure image has alpha channel (BGRA)
    if img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    
    # Composite image onto black background (handle transparent pixels)
    # Create black background
    black_bg = np.zeros((img.shape[0], img.shape[1], 4), dtype=np.uint8)
    black_bg[:, :, 3] = 255  # Opaque black
    
    # Composite: blend image onto black background
    if img.shape[2] == 4:
        alpha = img[:, :, 3:4] / 255.0
        img_composited = (img[:, :, :4] * alpha + black_bg * (1 - alpha)).astype(np.uint8)
    else:
        img_composited = img
    
    # Apply perspective transformation to map from press space to projector space
    if not debug_bypass_warp and calibrator.is_calibrated():
        # Get transformation matrix (maps from projector pixels to press space)
        H = calibrator.transformation_matrix
        # We need inverse: map from press space to projector pixels
        H_inv = np.linalg.inv(H)
        # Apply perspective transformation
        # Use BORDER_CONSTANT with black to fill areas outside warped region
        warped = cv2.warpPerspective(img_composited, H_inv, (output_width, output_height), 
                                      flags=cv2.INTER_CUBIC, 
                                      borderMode=cv2.BORDER_CONSTANT,
                                      borderValue=(0, 0, 0, 255))
        logger.debug(f"Applied perspective transformation for {press_id}")
    else:
        raise NotImplementedError("Debug bypass warp is not implemented")
    # else:
    #     # No calibration or debug bypass: just resize
    #     if img_composited.shape[1] != output_width or img_composited.shape[0] != output_height:
    #         warped = cv2.resize(img_composited, (output_width, output_height), interpolation=cv2.INTER_LINEAR)
    #     else:
    #         warped = img_composited
    #     if not calibrator.is_calibrated():
    #         logger.warning(f"Calibration not available for {press_id}, rendering without perspective transformation")
    
    return warped


def _perform_render_svg(data):
    """Perform the actual rasterization and emission of one SVG payload."""
    svg_str = data.get('svg', '')
    if not svg_str:
        return
        
    # Determine operation mode from payload or current state
    operation_mode = None
    if 'operation_mode' in data:
        operation_mode = _parse_operation_mode(data['operation_mode'])
        if operation_mode is None:
            logger.warning(f"[_perform_render_svg] Unable to parse operation_mode: {data['operation_mode']!r}")
    if operation_mode is None:
        operation_mode = _determine_operation_mode_from_state()
        logger.info(f"[_perform_render_svg] operation_mode not in data, derived from state: {operation_mode.value}")
    else:
        logger.info(f"[_perform_render_svg] Received explicit operation_mode from data: {operation_mode.value}")
    
    logger.info(f"[_perform_render_svg] Final operation_mode: {operation_mode.value}")
    
    out_w, out_h = projector_resolution['width'], projector_resolution['height']

    # Render based on mode
    if operation_mode is OperationMode.SCENE_SETUP:
        # Normal mode: process SVG and render single press scene
        svg_processed = adjust_upload_image_heights(svg_str)
        svg_processed = inline_upload_image_links(svg_processed)
        
        # Save SVG to disk before rasterizing (with pretty printing)

        
        # Render single press scene
        projector_image = _render_press_scene(_active_press, svg_processed, out_w, out_h)
        assert projector_image is not None
    else:
        # Operation mode: Render each press separately, apply perspective transformation, then composite
        # Create a blank black canvas for compositing (opaque black background)
        projector_image = None # np.zeros((out_h, out_w, 3), dtype=np.uint8)
        
        # Process each press that has a scene loaded
        for press_id in ['press1', 'press2']:
            press_state = _operation_state.get(press_id, {})
            if not press_state.get('layout_data'):
                continue
            
            # Generate SVG for this press only
            press_svg = pj_generate_svg(press_id=press_id, operation_mode=operation_mode)
            
            # Render and warp this press's scene
            press_warped = _render_press_scene(press_id, press_svg, out_w, out_h)
            assert press_warped is not None
            if projector_image is None:
                projector_image = press_warped
            else:
                projector_image = cv2.add(projector_image, press_warped)
        logger.debug(f"Composited warped image for {press_id} in operation mode")
    

    ok, enc = cv2.imencode('.png', projector_image)
    if not ok:
        return
    b64 = base64.b64encode(enc.tobytes()).decode('ascii')
    logger.info(f"[_perform_render_svg] Emitting projector_frame with operation_mode: {operation_mode.value}")
    emit('projector_frame', {'image': b64, 'operation_mode': operation_mode.value}, room='projector')
    try:
        emit('set_projection_mode', { 'mode': 'frames' }, room='projector')
    except Exception:
        pass


@socketio.on('render_svg')
def handle_render_svg(data):
    """Coalesce rapid render requests: keep only the newest while rendering."""
    logger.info(f"[handle_render_svg] Received render_svg event, data keys: {list(data.keys()) if isinstance(data, dict) else 'not a dict'}")
    global is_rendering, pending_render
    
    logger.warning(f"Operation mode: {data.get('operation_mode', 'unknown')}")
    
    try:
        # If a render is in progress, replace any pending payload with the newest and return
        if is_rendering:
            logger.info("[handle_render_svg] Render already in progress, queuing request")
            pending_render = data
            return

        # Start rendering and process the newest pending payload after each render
        logger.info("[handle_render_svg] Starting render process")
        is_rendering = True
        current = data
        while current is not None:
            try:
                logger.info(f"[handle_render_svg] Processing render, svg length: {len(current.get('svg', ''))}")
                _perform_render_svg(current)
            except Exception as e:
                logger.exception("Error rendering SVG")
            # Grab the latest pending render (if any), then clear it
            current = pending_render
            pending_render = None
    finally:
        is_rendering = False
        logger.info("[handle_render_svg] Render process completed")


if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info("Press Projector System - Starting Server")
    logger.info("=" * 60)
    
    # Load existing calibrations for all presses if available
    for press_id in ['press1', 'press2']:
        calibration_data = db.load_press_calibration(press_id)
        if calibration_data:
            load_press_calibration(press_id)
            logger.info(f"Loaded calibration for {press_id}")
    
    # Start periodic updates
    start_periodic_updates()
    logger.info("Periodic updates started")
    
    # Start server
    logger.info("Starting server on 0.0.0.0:5670")
    logger.info("Control interface: http://0.0.0.0:5670/control")
    logger.info("Projector view: http://0.0.0.0:5670/projector")
    
    socketio.run(app, host='0.0.0.0', port=5670, debug=True, log_output=True)

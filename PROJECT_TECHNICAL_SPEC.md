# Press Projector Positioning System - Technical Specification

## System Architecture Overview

### High-Level Architecture
The system implements a distributed web application with a monolithic backend service exposing both HTTP REST endpoints and WebSocket-based real-time communication channels. The architecture follows a client-server model with dual-client architecture: one control interface (tablet) and one visualization interface (projector display). The backend implements a stateless design pattern with persistent state management through a file-based abstraction layer.

### Technology Stack
- **Backend Framework**: Flask 2.3.3 with Flask-SocketIO 5.3.6 for bidirectional WebSocket communication
- **Async Transport**: eventlet 0.33.3 for greenlet-based concurrency
- **Computer Vision**: OpenCV 4.8.1.78 (cv2) for perspective transformation matrix computation
- **Numerical Computing**: NumPy 1.24.3 for matrix operations and coordinate transformations
- **Vector Graphics Processing**: CairoSVG 2.7.0 for SVG-to-raster conversion pipeline
- **Frontend**: Vanilla JavaScript with Socket.IO client library for real-time event handling
- **Data Serialization**: JSON for all data persistence and API communication

## Core Components

### 1. Calibration Engine (`backend/calibration.py`)

#### Calibrator Class
Implements perspective transformation using OpenCV's `cv2.getPerspectiveTransform()` algorithm. The class maintains two coordinate spaces:
- **Projector Space**: Pixel coordinates in the projector's native resolution (source_points)
- **Press Space**: Metric coordinates in millimeters (destination_points)

#### Transformation Matrix Computation
The system computes a 3x3 homogeneous transformation matrix using four-point correspondence:
- Source points: Quadrilateral in projector pixel space (numpy.float32 array)
- Destination points: Rectangular target space in millimeters (numpy.float32 array)
- Matrix computation: `H = cv2.getPerspectiveTransform(source_points, destination_points)`

#### Coordinate Conversion Methods
- `projector_to_press(x, y)`: Applies forward transformation using `cv2.perspectiveTransform()` with homogeneous coordinates
- `press_to_projector(x_mm, y_mm)`: Applies inverse transformation using `np.linalg.inv(H)` and `cv2.perspectiveTransform()`
- `mm_to_pixels()` / `pixels_to_mm()`: Computed from average of width and height scaling factors

#### Calibration Data Structure
```json
{
  "projector_pixels": [[x1,y1], [x2,y2], [x3,y3], [x4,y4]],
  "press_width_mm": float,
  "press_height_mm": float,
  "pixels_per_mm": float
}
```

### 2. Database Abstraction Layer (`backend/database.py`)

#### Abstract Interface (DB_interface)
Defines abstract base class with methods:
- `save_calibration(calibration_data)`: Persist calibration state
- `load_calibration()`: Retrieve calibration state
- `save_job(job_id, job_data)`: Persist job configurations
- `load_job(job_id)`: Retrieve job by identifier
- `list_jobs()`: Enumerate all job identifiers
- `save_configuration(config_name, config_data)`: Persist layout configurations
- `load_configuration(config_name)`: Retrieve named configuration
- `list_configurations()`: Enumerate all configuration names
- `set_last_scene(name)` / `get_last_scene()`: Last-loaded scene persistence

#### FileBasedDB Implementation
JSON-based persistence layer with directory structure:
- `config/calibration.json`: Single calibration state
- `config/jobs/{job_id}.json`: Individual job files
- `config/configurations/{config_name}.json`: Named layout configurations
- `config/last_scene.json`: Last scene metadata

All JSON files include ISO 8601 timestamp metadata for auditing.

### 3. File Management System (`backend/file_manager.py`)

#### FileManager Class
Handles multipart file uploads with validation:
- **Allowed Extensions**: `{'png', 'jpg', 'jpeg', 'svg'}`
- **Size Limit**: 16MB maximum file size
- **Filename Generation**: UUID-based unique identifier with secure filename sanitization via `werkzeug.utils.secure_filename()`
- **Storage Location**: `uploads/` directory at project root

#### SVG Processing
- `process_svg_file()`: Parses SVG content using regex-based extraction
- `create_helping_lines_svg()`: Generates SVG markup for guide lines
- `_extract_svg_elements()`: Extracts geometric primitives (rect, circle, line, polygon, path)
- `_extract_svg_dimensions()`: Parses width/height attributes from SVG root element

### 4. Server Application (`backend/server.py`)

#### Flask Application Initialization
- Static file serving from `frontend/static/`
- Template rendering from `frontend/templates/`
- CORS enabled for all origins via SocketIO configuration
- Logging configured to `debug/press_projector.log` with INFO level

#### State Management
In-memory state dictionary `_layout_state`:
```python
{
  'object_orientation': float,  # Base rotation in degrees
  'center_lines': {
    'horizontal': float | None,  # Y-coordinate in mm
    'vertical': float | None     # X-coordinate in mm
  },
  'elements': List[Dict]  # Drawing elements
}
```

#### Projection Pipeline
1. **SVG Generation**: `pj_generate_svg(width, height)` generates SVG markup with:
   - Base rotation transform applied to root `<g>` element
   - Center line visualization (dashed lines)
   - Drawing elements (rectangles, circles, lines, images, text)
   - Boundary pattern overlay (when enabled)

2. **Rasterization Pipeline**:
   - SVG preprocessing: `adjust_upload_image_heights()` computes aspect ratios from OpenCV image loading
   - Image inlining: `inline_upload_image_links()` converts `/uploads/` URLs to base64 data URLs
   - Rasterization: `cairosvg.svg2png()` with target resolution (2x supersampling implied)
   - Image decoding: `cv2.imdecode()` to numpy array (BGRA format)

3. **Perspective Warping**:
   - Inverse transformation: `H_inv = np.linalg.inv(calibrator.transformation_matrix)`
   - Warping: `cv2.warpPerspective(img, H_inv, (out_w, out_h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT)`
   - Debug bypass: `debug_bypass_warp` flag skips warping for preview

4. **Frame Encoding**:
   - PNG encoding: `cv2.imencode('.png', warped)`
   - Base64 encoding: `base64.b64encode(enc.tobytes()).decode('ascii')`
   - WebSocket emission: `emit('projector_frame', {'image': b64})`

#### Render Coalescing
Implements request throttling to prevent render queue overflow:
- `is_rendering` flag prevents concurrent renders
- `pending_render` stores most recent render request during active render
- Processes pending renders sequentially after each render completes

#### Periodic Update Timer
Timer-based broadcast system (2-second interval) sends layout updates to control interface. Uses `threading.Timer` for scheduling.

### 5. REST API Endpoints

#### Calibration Endpoints
- `POST /api/calibration`: Accepts JSON with `projector_pixels`, `press_width_mm`, `press_height_mm`. Validates input, computes calibration, persists to database, broadcasts via WebSocket.
- `GET /api/calibration`: Returns current calibration data or 404 if absent.

#### Layout Endpoints
- `POST /api/layout`: Accepts JSON with `object_orientation`, `center_lines`, `elements`. Updates in-memory state, generates SVG, broadcasts to control interface.
- `GET /api/layout`: Returns current layout state as JSON.

#### File Management Endpoints
- `POST /api/upload`: Multipart form data with `file` field. Validates file type and size, saves via FileManager, returns file metadata.
- `GET /api/files`: Returns list of uploaded files with metadata.
- `GET /api/files/<filename>/base64`: Returns file as base64-encoded data URL.

#### Configuration Endpoints
- `POST /api/configurations`: Saves named configuration with layout data.
- `GET /api/configurations`: Lists all configuration names.
- `GET /api/configurations/<config_name>`: Loads specific configuration, sets as last scene.
- `GET /api/last-scene`: Returns last loaded scene name.
- `POST /api/last-scene`: Sets last loaded scene name.

### 6. WebSocket Protocol

#### Socket.IO Events (Server → Client)

**Control Room Events**:
- `calibration_updated`: Calibration data payload
- `layout_updated`: `{layout: Dict, svg: str}` - Layout state and SVG markup
- `projector_resolution`: `{width: int, height: int}` - Projector display resolution
- `boundary_pattern_toggled`: `{visible: bool, svg: str}` - Boundary pattern state
- `update_calibration_points`: Calibration point updates during interactive calibration
- `calibration_point_dragged`: Point drag events
- `calibration_point_selected`: Point selection events

**Projector Room Events**:
- `calibration_updated`: Calibration data payload
- `projector_frame`: `{image: str}` - Base64-encoded PNG frame
- `start_calibration`: `{points: List[Dict], press_width_mm, press_height_mm}` - Interactive calibration mode
- `update_calibration_points`: Calibration point updates
- `stop_calibration`: Stops calibration overlay
- `boundary_pattern_toggled`: Boundary pattern visibility
- `set_projection_mode`: `{mode: 'svg' | 'frames'}` - Switches projection rendering mode

#### Socket.IO Events (Client → Server)

- `join_room`: `{room: 'control' | 'projector'}` - Joins client to named room
- `leave_room`: `{room: 'control' | 'projector'}` - Leaves named room
- `request_update`: Requests current state synchronization
- `layout_update`: `{object_orientation?, center_lines?, elements?}` - Layout modification
- `show_validation_pattern`: Enables boundary pattern and calibration overlay
- `hide_validation_pattern`: Disables boundary pattern and calibration overlay
- `start_calibration`: Initiates interactive calibration mode
- `update_calibration_points`: Updates calibration point positions
- `calibration_point_dragged`: Reports point drag events
- `calibration_point_selected`: Reports point selection
- `projector_resolution`: `{width: int, height: int}` - Reports projector resolution
- `set_debug_mode`: `{bypass_warp: bool}` - Toggles debug rendering mode
- `render_svg`: `{svg: str, target_width: int, target_height: int}` - Triggers rasterization pipeline

### 7. Frontend Architecture

#### Control Interface (`frontend/templates/control.html`)
- Tab-based UI with sections: Calibration, Layout Editor, Files, Configurations, Jobs
- SVG canvas for preview rendering
- Interactive calibration point markers with drag handles
- Drawing tools: lines (horizontal/vertical/rotated), rectangles, circles, images
- Form inputs for metric dimensions (mm)
- Configuration save/load interface
- Setup & Maintenance tab (hidden by default, toggleable via button)

#### Projector Interface (`frontend/templates/projector.html`)
- Fullscreen SVG container or canvas-based frame rendering
- WebSocket client for real-time updates
- Status indicator (connection state)
- Calibration overlay mode (interactive point markers)
- Boundary pattern visualization
- No user interaction controls (display-only)

#### Common JavaScript (`frontend/static/common.js`)
- `WebSocketClient`: Socket.IO wrapper with auto-reconnect logic (exponential backoff, max 10 attempts)
- `SVGUtils`: DOM manipulation utilities for SVG element creation
- `CoordinateConverter`: Converts between coordinate spaces using calibration data

### 8. Data Flow

#### Calibration Flow
1. User marks 4 corner points on projector view
2. Control interface sends `POST /api/calibration` with point coordinates
3. Server computes transformation matrix via `Calibrator.set_calibration_from_target()`
4. Calibration persisted via `FileBasedDB.save_calibration()`
5. WebSocket broadcast: `calibration_updated` to both rooms
6. Projector view applies calibration to all subsequent renders

#### Layout Update Flow
1. User modifies layout in control interface (adds element, changes orientation, etc.)
2. Control sends `layout_update` WebSocket event or `POST /api/layout`
3. Server updates `_layout_state` dictionary
4. Server generates SVG via `pj_generate_svg()`
5. SVG saved to `debug/renders/control_latest.svg` for debugging
6. WebSocket broadcast: `layout_updated` to control room (for preview)
7. Projector requests render via `render_svg` WebSocket event
8. Server rasterizes SVG, applies perspective warp, encodes as PNG
9. WebSocket broadcast: `projector_frame` to projector room

#### Configuration Persistence Flow
1. User saves configuration with name
2. `POST /api/configurations` with `{name: str, data: Dict}`
3. Server persists via `FileBasedDB.save_configuration()`
4. Configuration stored as `config/configurations/{name}.json`
5. Loading: `GET /api/configurations/{name}` returns configuration data
6. Server sets last scene via `FileBasedDB.set_last_scene(name)`

### 9. Coordinate System Transformations

#### Transformation Chain
1. **Design Space (mm)**: User-defined metric coordinates
2. **Press Space (mm)**: Calibrated press area coordinates (0,0) to (width_mm, height_mm)
3. **Target Pixel Space**: Rectangular raster target derived from press dimensions (`press_width_mm` × `press_height_mm` × fixed px/mm)
4. **Projector Pixel Space**: Warped projector coordinates via inverse perspective transform

#### Element Rendering Pipeline
- Element defined in press space (mm): `{position: [x_mm, y_mm], width_mm, height_mm, rotation}`
- Convert to target pixel space: `calibrator.press_to_projector(x_mm, y_mm)` → pixel coordinates
- Generate SVG element with pixel coordinates
- Apply base rotation transform if `object_orientation != 0`
- Rasterize SVG to target resolution
- Apply inverse perspective warp to projector space

### 10. File Structure

```
press_projector/
├── backend/
│   ├── server.py              # Flask app, WebSocket handlers, REST API
│   ├── calibration.py         # Calibrator class, perspective transforms
│   ├── database.py            # DB_interface, FileBasedDB
│   └── file_manager.py        # FileManager, upload handling, SVG processing
├── frontend/
│   ├── templates/
│   │   ├── control.html       # Control interface (tablet)
│   │   └── projector.html     # Projector view (fullscreen)
│   └── static/
│       ├── common.js           # WebSocket client, SVG utilities
│       ├── favicon.*           # Favicon assets
│       └── site.webmanifest    # PWA manifest
├── config/
│   ├── calibration.json       # Current calibration state
│   ├── settings.json           # System configuration
│   ├── projector_resolution.json  # Cached projector resolution
│   ├── last_scene.json        # Last loaded scene name
│   ├── jobs/                  # Job storage directory
│   └── configurations/       # Named configuration storage
├── uploads/                   # Uploaded file storage
├── debug/
│   ├── press_projector.log    # Application log
│   └── renders/              # Debug render outputs
│       ├── latest.svg        # Latest SVG before rasterization
│       ├── latest_unwarped.png  # Raster before perspective warp
│       └── latest.png         # Final warped frame
├── start_server.py           # Application entry point
├── requirements.txt          # Python dependencies
├── install.sh               # Installation script
└── test_system.py           # Test suite
```

### 11. Key Algorithms

#### Perspective Transformation
- Uses homogeneous coordinates: `[x, y, 1]` for 2D points
- Matrix multiplication: `[x', y', w'] = H @ [x, y, 1]`
- Normalization: `x_final = x' / w'`, `y_final = y' / w'`
- OpenCV handles normalization internally in `cv2.perspectiveTransform()`


#### Aspect Ratio Preservation
- Image elements: `aspect_ratio = img_height / img_width` (from OpenCV `cv2.imread()`)
- Height calculation: `height_mm = width_mm * aspect_ratio`
- Pixel conversion uses calibration for metric-to-pixel scaling

### 12. Error Handling

#### Calibration Validation
- `validate_calibration_quality()`: Round-trip conversion test
- Computes error at 4 corner points
- Returns metrics: `{valid: bool, max_error_mm: float, avg_error_mm: float}`
- Threshold: `max_error < 1.0` mm for valid calibration

#### Render Error Handling
- SVG parsing errors: Falls back to empty SVG
- Image loading errors: Uses default aspect ratio (1:1)
- Warp errors: Falls back to linear resize if calibration invalid
- Base64 encoding errors: Logs exception, skips frame emission

#### WebSocket Error Handling
- Reconnection logic with exponential backoff
- Event emission guards: Checks connection state before emitting
- Room-based error isolation: Errors in one room don't affect other room

### 13. Performance Characteristics

#### Render Pipeline Latency
- SVG generation: <10ms (string concatenation)
- Rasterization: ~50-200ms (CairoSVG, depends on complexity)
- Perspective warp: ~20-50ms (OpenCV, depends on resolution)
- PNG encoding: ~10-30ms (OpenCV imencode)
- Base64 encoding: ~5-10ms
- Total: ~100-300ms per frame

#### Memory Usage
- SVG strings: ~10-100KB depending on element count
- Raster images: `width * height * 4` bytes (BGRA) for unwarped, same for warped
- Example: 1920x1080 = ~8MB per frame (unwarped + warped = 16MB peak)

#### Concurrency Model
- Eventlet greenlets for WebSocket handling (non-blocking I/O)
- Threading.Timer for periodic updates (separate thread)
- Render coalescing prevents queue buildup (single render at a time)

### 14. Configuration Schema

#### Settings (`config/settings.json`)
```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 5000,
    "debug": false
  },
  "projector": {
    "default_width": 1920,
    "default_height": 1080
  },
  "calibration": {
    "max_error_mm": 1.0
  }
}
```

#### Layout Configuration Schema
```json
{
  "object_orientation": 0.0,
  "center_lines": {
    "horizontal": null | float,
    "vertical": null | float
  },
  "elements": [
    {
      "type": "rectangle" | "circle" | "line" | "image" | "text",
      "position": [x_mm, y_mm],
      "width": float,      // for rectangle, image
      "height": float,     // for rectangle
      "radius": float,     // for circle
      "start": [x, y],    // for line
      "end": [x, y],      // for line
      "rotation": float,
      "color": "#hex",
      "text": string,     // for text
      "font_size": int,   // for text
      "image_url": string, // for image
      "name": string,     // optional display name (non-text elements)
      "label": string     // optional label
    }
  ]
}
```

### 15. Dependencies and Versioning

#### Python Dependencies
- Flask==2.3.3: Web framework
- Flask-SocketIO==5.3.6: WebSocket support
- opencv-python==4.8.1.78: Computer vision library
- numpy==1.24.3: Numerical computing
- python-socketio==5.8.0: Socket.IO protocol implementation
- eventlet==0.33.3: Async networking
- cairosvg==2.7.0: SVG rasterization

#### Frontend Dependencies
- Socket.IO client library (loaded via CDN in HTML templates)
- No build system required (vanilla JavaScript)

### 16. Initialization Sequence

1. **Environment Setup** (`start_server.py`):
   - Creates directories: `config/`, `jobs/`, `uploads/`, `frontend/templates/`, `frontend/static/`
   - Generates default `settings.json` if absent
   - Adds `backend/` to Python path

2. **Server Initialization** (`backend/server.py`):
   - Initializes Flask app with static/template folders
   - Creates SocketIO instance with CORS enabled
   - Instantiates `FileBasedDB`, `Calibrator`, `FileManager`
   - Loads existing calibration from database if available
   - Starts periodic update timer (2-second interval)

3. **Client Connection**:
   - Client connects via Socket.IO
   - Client emits `join_room` with room identifier
   - Server sends current state: calibration, layout, projector resolution

4. **Operation Mode**:
   - Control interface: User interactions → REST/WebSocket events → Server updates
   - Projector interface: Receives frame updates via WebSocket → Renders on canvas

### 17. Testing Infrastructure

#### Test Suite (`test_system.py`)
Tests cover:
- Database operations (save/load calibration, jobs, configurations)
- Calibration system (coordinate conversion, scaling, validation)
- Projector management (layout state, SVG generation)
- File management (validation, upload simulation)

#### Test Configuration
- Uses `test_config/` directory for test data isolation
- Test calibration data with known transformation
- Mock file uploads for file manager testing

### 18. Debug and Logging

#### Logging Configuration
- File: `debug/press_projector.log`
- Level: INFO
- Format: `%(asctime)s %(levelname)s %(name)s %(message)s`
- Rotation: Append mode (manual cleanup required)

#### Debug Outputs
- SVG renders: `debug/renders/control_latest.svg` (pretty-printed)
- Unwarped raster: `debug/renders/latest_unwarped.png`
- Warped frame: `debug/renders/latest.png`
- Projector resolution: `config/projector_resolution.json`

#### Debug Mode
- `debug_bypass_warp`: Skips perspective transformation for preview
- Enabled via WebSocket: `set_debug_mode` event
- Useful for debugging calibration issues

---

## Summary

This system implements a real-time computer vision-based positioning system for industrial sublimation press operations. The architecture combines traditional REST APIs with WebSocket-based real-time communication, computer vision algorithms for perspective correction, and a file-based persistence layer. The system supports dual-client architecture (control + display), metric-based coordinate systems, and dynamic layout generation with SVG-based visualization that is rasterized and warped for accurate projector projection.


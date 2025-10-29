# Press Projector Positioning System

## Architecture Overview

A web-based system with a Python backend providing:
- Local HTTP server for serving web interfaces
- WebSocket server for real-time communication between control UI (tablet) and projector view
- OpenCV-based perspective transformation using 4-point calibration
- SVG-based visualization layer
- JSON file storage with abstract database interface
- Setup & Maintenance mode for projector alignment verification
- Layout editor with drawing tools for positioning guides

## Technology Stack

- **Backend**: Python with Flask/FastAPI, OpenCV, WebSocket support
- **Frontend**: HTML/JavaScript with SVG rendering
- **Communication**: WebSocket (local network)
- **Storage**: JSON files via abstract `DB_interface` with `FileBasedDB` implementation

## Key Components

### Backend (`backend/`)

1. **`server.py`** - Main HTTP/WebSocket server
   - Serves static files for both UI instances
   - WebSocket endpoints for bidirectional communication
   - REST API endpoints for file operations

2. **`calibration.py`** - OpenCV perspective transformation
   - `Calibrator` class for 4-point calibration
   - Stores source points (projector space) and destination points (press space)
   - Computes and applies perspective transformation matrix
   - Handles metric scaling (user provides dimensions)
   - Generates press boundary pattern (rectangle outline matching calibrated press area with corner markers)

3. **`projector.py`** - Projection management
   - Applies calibration to design images/guides
   - Manages SVG overlay generation (grids, rulers, guides)
   - Handles design positioning and scaling
   - Generates press boundary pattern SVG for alignment verification
   - Applies base rotation transform for object orientation
   - Converts mm measurements to SVG coordinates using calibration data

4. **`database.py`** - Abstract storage interface
   - `DB_interface` abstract base class
   - `FileBasedDB` implementation using JSON files
   - Stores: jobs, positions, temperature/time settings, calibration data, layout configurations
   - Configuration storage: object orientation, center lines, drawing elements (lines, rectangles, circles, images), process info

5. **`file_manager.py`** - Design file handling
   - Accepts image files (PNG, JPEG) and SVG files
   - Pre-processes SVG files for helping lines
   - File upload/storage management

### Frontend (`frontend/`)

1. **`control.html`** - Tablet control interface
   - Design selection and upload
   - Calibration interface (4-point marking)
   - **Object Orientation & Layout Tools**
     - Object orientation angle setting (rotates all items via base SVG transform)
     - Horizontal center line definition
     - Vertical center line definition
     - Horizontal/vertical line tool (drag from edge, set distance in mm from center line)
     - Rotated line tool
     - Rectangle tool with text labels (define rotation, width, height in mm)
     - Circle tool with text labels (define radius in mm)
     - Image tool (define width in mm, proportional height, moveable/rotatable)
     - Process information (temperature and duration) - display format TBD
   - Configuration management (save/load named configurations)
   - Job management (save/load)
   - **Setup & Maintenance tab** (hidden by default, toggleable with button/gesture)
     - Press boundary pattern display toggle
     - Quick calibration check/test pattern
     - System diagnostics and calibration status

2. **`projector.html`** - Projector visualization view
   - Full-screen SVG display
   - Receives WebSocket updates for visualization
   - Shows grids, guides, design outlines
   - Base rotation transform for object orientation
   - Center lines visualization
   - Drawing elements (lines, rectangles, circles with labels)
   - Image overlays
   - Shows press boundary pattern when activated from Setup & Maintenance
   - Process information display (format TBD)
   - No controls, display-only

3. **`common.js`** - Shared utilities
   - WebSocket client wrapper
   - SVG manipulation utilities
   - Common UI components
   - Press boundary pattern generator (rectangle outline with corner markers)
   - Coordinate conversion utilities (mm to SVG pixels)
   - Drawing element managers (lines, rectangles, circles, images)

### Configuration (`config/`)
- `settings.json` - System configuration
- `calibration.json` - Current calibration data
- `jobs/` - Job storage directory

## Implementation Steps

1. **Project Structure Setup**
   - Create directory structure
   - Initialize Python project with dependencies (requirements.txt)
   - Setup basic Flask/FastAPI server

2. **Database Abstraction Layer**
   - Implement `DB_interface` abstract class
   - Implement `FileBasedDB` with JSON storage
   - Methods: save_job(), load_job(), list_jobs(), save_calibration(), save_configuration(), load_configuration(), list_configurations()

3. **Calibration System**
   - OpenCV perspective transform using 4 corner points
   - Metric dimension input for scaling
   - Store calibration matrix and apply to coordinates
   - Generate press boundary pattern (rectangle matching calibrated press dimensions)

4. **WebSocket Communication**
   - Local WebSocket server on backend
   - Message protocol: {type, data}
   - Control UI sends: calibration_points, design_selection, position_updates, show_boundary_pattern, layout_configuration, object_orientation, center_lines, drawing_elements, process_info
   - Projector view receives: visualization_updates, boundary_pattern_updates, layout_updates

5. **Design File Handling**
   - Image upload (PNG, JPEG)
   - SVG file parsing and overlay generation
   - Coordinate transformation from design space to projector space

6. **Control Interface**
   - Calibration UI (point marking with visual feedback)
   - Design upload and selection
   - **Layout Editor**
     - Object orientation angle input
     - Center line definition tools (horizontal/vertical)
     - Drawing tools: lines (horizontal, vertical, rotated), rectangles, circles
     - Image import and positioning tools
     - Text labels for shapes
     - Measurement inputs in mm (width, height, radius, distances)
     - Drag-and-drop positioning for elements
     - Rotation controls for elements
   - Process information input (temperature, duration)
   - Configuration save/load interface (named configurations)
   - Job save/load interface
   - Setup & Maintenance tab (hidden by default, toggleable)

7. **Projector Visualization**
   - SVG element for rendering
   - Base rotation transform for object orientation
   - Grid/ruler overlays
   - Design outline projection
   - Center lines visualization
   - Drawing elements (lines, rectangles, circles with labels)
   - Image overlays
   - Press boundary pattern display (rectangle with corner markers)
   - Process information display (format TBD)
   - Real-time updates via WebSocket

8. **Setup & Maintenance Features**
   - Hidden tab in control interface (toggleable button/gesture)
   - Press boundary pattern generator
   - Quick alignment verification (projects rectangle matching press dimensions)
   - Pattern overlays calibration area for visual verification
   - System diagnostics and calibration status display

9. **Testing & Documentation**
   - Test perspective correction accuracy
   - Verify WebSocket communication
   - Test press boundary pattern alignment
   - Test layout editor functionality
   - Document calibration process

## File Structure

```
press_projector/
├── backend/
│   ├── server.py
│   ├── calibration.py
│   ├── projector.py
│   ├── database.py
│   └── file_manager.py
├── frontend/
│   ├── control.html
│   ├── projector.html
│   └── common.js
├── config/
│   ├── settings.json
│   └── calibration.json
├── jobs/
├── uploads/
├── requirements.txt
└── README.md
```

## Key Features

### Object Orientation
- User defines rotation angle for object (may not align with press)
- Applies as base SVG transform to all projected elements
- Stored in configuration

### Center Lines
- Horizontal center line definition
- Vertical center line definition
- Used as reference for positioning other elements

### Drawing Tools
- **Horizontal/Vertical Lines**: Drag from outside drawing area, set distance in mm from corresponding center line
- **Rotated Lines**: Define angle and position
- **Rectangles**: Define rotation, width, height in mm, with text label
- **Circles**: Define radius in mm, with text label
- **Images**: Define width in mm (height scales proportionally), moveable and rotatable

### Process Information
- Temperature and duration settings
- Display format TBD (to be determined later)

### Configuration Management
- Save entire layout configuration (orientation, center lines, all drawing elements)
- Load named configurations
- List available configurations


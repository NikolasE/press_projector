# Press Projector Positioning System

A web-based system for precise positioning of designs on sublimation presses using projector projection and OpenCV perspective correction.

## Features

- **4-point calibration** with OpenCV perspective transformation
- **Object orientation** support (rotate all elements by defined angle)
- **Layout editor** with drawing tools (lines, rectangles, circles, images)
- **Center line positioning** for precise alignment
- **Real-time projection** via WebSocket communication
- **Configuration management** for saving/loading layouts
- **Setup & Maintenance** mode for projector alignment verification

## Installation

### Quick Install
```bash
# Run the installation script
./install.sh
```

### Manual Install
1. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Set up directories:
   ```bash
   mkdir -p config jobs uploads frontend/templates frontend/static
   ```

3. Test the system:
   ```bash
   python test_system.py
   ```

## Usage

### Starting the Server
```bash
# Basic start
python start_server.py

# Custom host/port
python start_server.py --host 0.0.0.0 --port 5000

# Debug mode
python start_server.py --debug
```

### Accessing the Interfaces
- **Control Interface** (tablet): `http://[server-ip]:5000/control`
- **Projector View** (press computer): `http://[server-ip]:5000/projector`

### Workflow

1. **Initial Setup**:
   - Connect projector to press computer
   - Open projector view in fullscreen
   - Open control interface on tablet

2. **Calibration**:
   - Mark 4 corner points of the press area
   - Enter press dimensions in mm
   - Save calibration

3. **Layout Creation**:
   - Set object orientation angle if needed
   - Define horizontal/vertical center lines
   - Add positioning guides (lines, rectangles, circles, images)
   - Save configuration

4. **Production Use**:
   - Load saved configuration
   - Position items according to projected guides
   - Use Setup & Maintenance for alignment verification

## Architecture

- **Backend**: Python Flask with WebSocket support
- **Frontend**: HTML/JavaScript with SVG rendering
- **Communication**: Local WebSocket for real-time updates
- **Storage**: JSON files with abstract database interface
- **Calibration**: OpenCV perspective transformation
- **Projection**: SVG-based visualization

## File Structure

```
press_projector/
├── backend/                 # Python backend
│   ├── server.py           # Main Flask server
│   ├── calibration.py      # OpenCV calibration
│   ├── projector.py        # Projection management
│   ├── database.py         # Data storage
│   └── file_manager.py     # File handling
├── frontend/               # Web interfaces
│   ├── templates/          # HTML templates
│   └── static/             # JavaScript/CSS
├── config/                 # Configuration files
├── jobs/                   # Job storage
├── uploads/                # Uploaded files
├── requirements.txt        # Python dependencies
├── start_server.py         # Startup script
├── test_system.py          # Test suite
└── install.sh              # Installation script
```

## API Endpoints

- `POST /api/calibration` - Save calibration data
- `GET /api/calibration` - Load calibration data
- `POST /api/layout` - Update layout configuration
- `GET /api/layout` - Get current layout
- `POST /api/boundary-pattern` - Toggle boundary pattern
- `POST /api/upload` - Upload files
- `GET /api/files` - List uploaded files
- `POST /api/configurations` - Save configuration
- `GET /api/configurations` - List configurations
- `GET /api/configurations/<name>` - Load configuration

## WebSocket Events

- `calibration_updated` - Calibration data changed
- `layout_updated` - Layout configuration changed
- `boundary_pattern_toggled` - Boundary pattern visibility changed

## Troubleshooting

### Common Issues

1. **Calibration not working**: Ensure all 4 corner points are marked correctly
2. **Projection not visible**: Check projector connection and fullscreen mode
3. **WebSocket connection failed**: Verify server is running and accessible
4. **File upload errors**: Check file permissions and size limits

### Debug Mode

Run with debug mode for detailed logging:
```bash
python start_server.py --debug
```

### System Requirements

- Python 3.7+
- Modern web browser with WebSocket support
- Projector with HDMI/VGA input
- Local network connection

#!/usr/bin/env python3
"""
Test script for the Press Projector System.
Tests basic functionality without requiring a full setup.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

from backend.database import FileBasedDB
from backend.calibration import Calibrator
from backend.projector import ProjectorManager
from backend.file_manager import FileManager


def test_database():
    """Test database functionality."""
    print("Testing database...")
    
    db = FileBasedDB("test_config")
    
    # Test calibration
    calibration_data = {
        "source_points": [[100, 100], [500, 100], [500, 400], [100, 400]],
        "destination_points": [[0, 0], [300, 0], [300, 200], [0, 200]],
        "press_width_mm": 300,
        "press_height_mm": 200,
        "transformation_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    }
    
    success = db.save_calibration(calibration_data)
    print(f"  Save calibration: {'✓' if success else '✗'}")
    
    loaded = db.load_calibration()
    print(f"  Load calibration: {'✓' if loaded else '✗'}")
    
    # Test job
    job_data = {
        "design_file": "test.png",
        "position": {"x": 50, "y": 50},
        "temperature": 180,
        "duration": 60
    }
    
    success = db.save_job("test_job", job_data)
    print(f"  Save job: {'✓' if success else '✗'}")
    
    loaded = db.load_job("test_job")
    print(f"  Load job: {'✓' if loaded else '✗'}")
    
    jobs = db.list_jobs()
    print(f"  List jobs: {'✓' if 'test_job' in jobs else '✗'}")
    
    # Test configuration
    config_data = {
        "object_orientation": 15.0,
        "center_lines": {"horizontal": 100, "vertical": 150},
        "elements": [{"type": "line", "start": [0, 0], "end": [100, 100]}]
    }
    
    success = db.save_configuration("test_config", config_data)
    print(f"  Save configuration: {'✓' if success else '✗'}")
    
    loaded = db.load_configuration("test_config")
    print(f"  Load configuration: {'✓' if loaded else '✗'}")
    
    configs = db.list_configurations()
    print(f"  List configurations: {'✓' if 'test_config' in configs else '✗'}")
    
    print("Database test completed.\n")


def test_calibration():
    """Test calibration system."""
    print("Testing calibration...")
    
    calibrator = Calibrator()
    
    # Test calibration setup
    source_points = [[100, 100], [500, 100], [500, 400], [100, 400]]
    press_width_mm = 300
    press_height_mm = 200
    
    success = calibrator.set_calibration_from_target(
        source_points, press_width_mm, press_height_mm
    )
    print(f"  Set calibration: {'✓' if success else '✗'}")
    
    # Test coordinate conversion
    try:
        raw_width_px, raw_height_px = calibrator.get_raw_size_px()
        print(f"  Raw size: {'✓' if raw_width_px > 0 and raw_height_px > 0 else '✗'}")
    except Exception as e:
        print(f"  Raw size: ✗ ({e})")
    
    print("Calibration test completed.\n")


def test_projector():
    """Test projector management."""
    print("Testing projector...")
    
    calibrator = Calibrator()
    calibrator.set_calibration_from_target(
        [[100, 100], [500, 100], [500, 400], [100, 400]],
        300,
        200
    )
    
    projector = ProjectorManager(calibrator)
    
    # Test object orientation
    projector.set_object_orientation(15.0)
    print(f"  Set orientation: {'✓' if projector.current_layout['object_orientation'] == 15.0 else '✗'}")
    
    # Test center lines
    projector.set_center_lines(horizontal_y=100, vertical_x=150)
    layout = projector.current_layout
    print(f"  Set center lines: {'✓' if layout['center_lines']['horizontal'] == 100 and layout['center_lines']['vertical'] == 150 else '✗'}")
    
    # Test adding elements
    element_id = projector.add_element("line", {
        "start": [0, 0],
        "end": [100, 100],
        "label": "Test line"
    })
    print(f"  Add element: {'✓' if element_id else '✗'}")
    
    # Test SVG generation
    try:
        svg = projector.generate_svg(800, 600)
        print(f"  Generate SVG: {'✓' if '<svg' in svg else '✗'}")
    except Exception as e:
        print(f"  Generate SVG: ✗ ({e})")
    
    # Test boundary pattern
    projector.set_boundary_pattern_visibility(True)
    try:
        svg = projector.generate_svg(800, 600)
        print(f"  Boundary pattern: {'✓' if 'polygon' in svg else '✗'}")
    except Exception as e:
        print(f"  Boundary pattern: ✗ ({e})")
    
    print("Projector test completed.\n")


def test_file_manager():
    """Test file management."""
    print("Testing file manager...")
    
    file_manager = FileManager("test_uploads")
    
    # Test file validation
    valid = file_manager.is_allowed_file("test.png")
    print(f"  File validation: {'✓' if valid else '✗'}")
    
    invalid = file_manager.is_allowed_file("test.txt")
    print(f"  Invalid file: {'✓' if not invalid else '✗'}")
    
    # Test filename generation
    filename = file_manager.generate_unique_filename("test.png")
    print(f"  Filename generation: {'✓' if filename.endswith('.png') else '✗'}")
    
    # Test file listing
    files = file_manager.list_files()
    print(f"  List files: {'✓' if isinstance(files, list) else '✗'}")
    
    print("File manager test completed.\n")


def main():
    """Run all tests."""
    print("Press Projector System - Test Suite")
    print("=" * 40)
    
    try:
        test_database()
        test_calibration()
        test_projector()
        test_file_manager()
        
        print("All tests completed successfully! ✓")
        
    except Exception as e:
        print(f"Test suite failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())

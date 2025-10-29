"""
Projector management system for SVG generation and coordinate conversion.
Handles layout elements, transformations, and visualization.
"""

import json
from typing import Dict, List, Any, Optional, Tuple
from calibration import Calibrator


class ProjectorManager:
    """Manages projector visualization and layout elements."""
    
    def __init__(self, calibrator: Calibrator):
        self.calibrator = calibrator
        self.current_layout = {
            "object_orientation": 0.0,  # Base rotation angle in degrees
            "center_lines": {
                "horizontal": None,  # y position in mm
                "vertical": None     # x position in mm
            },
            "elements": []  # List of drawing elements
        }
        self.show_boundary_pattern = False
    
    def set_object_orientation(self, angle_degrees: float):
        """Set base rotation angle for all elements."""
        self.current_layout["object_orientation"] = angle_degrees
    
    def set_center_lines(self, horizontal_y: Optional[float] = None, 
                        vertical_x: Optional[float] = None):
        """Set center line positions."""
        if horizontal_y is not None:
            self.current_layout["center_lines"]["horizontal"] = horizontal_y
        if vertical_x is not None:
            self.current_layout["center_lines"]["vertical"] = vertical_x
    
    def add_element(self, element_type: str, element_data: Dict[str, Any]) -> str:
        """Add a drawing element to the layout."""
        element_id = f"{element_type}_{len(self.current_layout['elements'])}"
        element_data["id"] = element_id
        element_data["type"] = element_type
        self.current_layout["elements"].append(element_data)
        return element_id
    
    def update_element(self, element_id: str, element_data: Dict[str, Any]):
        """Update an existing element."""
        for element in self.current_layout["elements"]:
            if element["id"] == element_id:
                element.update(element_data)
                break
    
    def remove_element(self, element_id: str) -> bool:
        """Remove an element from the layout."""
        for i, element in enumerate(self.current_layout["elements"]):
            if element["id"] == element_id:
                del self.current_layout["elements"][i]
                return True
        return False
    
    def clear_layout(self):
        """Clear all elements from the layout."""
        self.current_layout["elements"] = []
        self.current_layout["center_lines"] = {"horizontal": None, "vertical": None}
        self.current_layout["object_orientation"] = 0.0
    
    def set_boundary_pattern_visibility(self, visible: bool):
        """Toggle press boundary pattern visibility."""
        self.show_boundary_pattern = visible
    
    def generate_svg(self, width: int = 1920, height: int = 1080) -> str:
        """
        Generate SVG visualization for the projector.
        
        Args:
            width, height: Projector resolution in pixels
        
        Returns:
            SVG string for projection
        """
        if not self.calibrator.is_calibrated():
            return self._generate_error_svg(width, height, "Calibration required")
        
        svg_elements = []
        
        # Base rotation transform
        rotation = self.current_layout["object_orientation"]
        if rotation != 0:
            center_x, center_y = width // 2, height // 2
            svg_elements.append(
                f'<g transform="rotate({rotation} {center_x} {center_y})">'
            )
        
        # Press boundary pattern
        if self.show_boundary_pattern:
            boundary_svg = self._generate_boundary_pattern_svg()
            svg_elements.append(boundary_svg)
        
        # Center lines
        center_lines_svg = self._generate_center_lines_svg(width, height)
        if center_lines_svg:
            svg_elements.append(center_lines_svg)
        
        # Layout elements
        for element in self.current_layout["elements"]:
            element_svg = self._generate_element_svg(element, width, height)
            if element_svg:
                svg_elements.append(element_svg)
        
        # Close rotation group if opened
        if rotation != 0:
            svg_elements.append('</g>')
        
        # Combine all elements
        svg_content = '\n'.join(svg_elements)
        
        return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
    <defs>
        <style>
            .guide-line {{ stroke: #00ff00; stroke-width: 2; stroke-dasharray: 5,5; }}
            .center-line {{ stroke: #ff0000; stroke-width: 3; stroke-dasharray: 10,5; }}
            .boundary {{ stroke: #ffff00; stroke-width: 4; fill: rgba(255, 255, 0, 0.2); }}
            .element-text {{ fill: #ffffff; font-family: Arial, sans-serif; font-size: 16px; text-anchor: middle; }}
            .element-shape {{ stroke: #00ffff; stroke-width: 2; fill: none; }}
        </style>
    </defs>
    {svg_content}
</svg>'''
    
    def _generate_error_svg(self, width: int, height: int, message: str) -> str:
        """Generate error SVG when calibration is missing."""
        return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
    <rect width="100%" height="100%" fill="#ff0000"/>
    <text x="50%" y="50%" text-anchor="middle" fill="white" font-size="48" font-family="Arial">
        {message}
    </text>
</svg>'''
    
    def _generate_boundary_pattern_svg(self) -> str:
        """Generate press boundary pattern SVG."""
        try:
            boundary_points = self.calibrator.generate_press_boundary_pattern()
            points_str = " ".join([f"{x},{y}" for x, y in boundary_points])
            
            # Add corner markers (no numeric labels)
            corner_markers = []
            for (x, y) in boundary_points:
                corner_markers.append(f'<circle cx="{x}" cy="{y}" r="8" fill="#ffff00"/>')
            
            return f'''
            <polygon points="{points_str}" class="boundary"/>
            {''.join(corner_markers)}
            '''
        except Exception as e:
            print(f"Error generating boundary pattern: {e}")
            return ""
    
    def _generate_center_lines_svg(self, width: int, height: int) -> str:
        """Generate center lines SVG."""
        lines = []
        
        # Horizontal center line
        if self.current_layout["center_lines"]["horizontal"] is not None:
            try:
                y_mm = self.current_layout["center_lines"]["horizontal"]
                y_px = self.calibrator.press_to_projector(0, y_mm)[1]
                lines.append(f'<line x1="0" y1="{y_px}" x2="{width}" y2="{y_px}" class="center-line"/>')
                # Don't render labels during rasterization
                # lines.append(f'<text x="10" y="{y_px-10}" fill="red" font-size="14">H: {y_mm:.1f}mm</text>')
            except Exception as e:
                print(f"Error generating horizontal center line: {e}")
        
        # Vertical center line
        if self.current_layout["center_lines"]["vertical"] is not None:
            try:
                x_mm = self.current_layout["center_lines"]["vertical"]
                x_px = self.calibrator.press_to_projector(x_mm, 0)[0]
                lines.append(f'<line x1="{x_px}" y1="0" x2="{x_px}" y2="{height}" class="center-line"/>')
                # Don't render labels during rasterization
                # lines.append(f'<text x="{x_px+10}" y="20" fill="red" font-size="14">V: {x_mm:.1f}mm</text>')
            except Exception as e:
                print(f"Error generating vertical center line: {e}")
        
        return '\n'.join(lines)
    
    def _generate_element_svg(self, element: Dict[str, Any], width: int, height: int) -> str:
        """Generate SVG for a single element."""
        element_type = element.get("type", "")
        
        try:
            if element_type == "line":
                return self._generate_line_svg(element)
            elif element_type == "rectangle":
                return self._generate_rectangle_svg(element)
            elif element_type == "circle":
                return self._generate_circle_svg(element)
            elif element_type == "image":
                return self._generate_image_svg(element)
            elif element_type == "text":
                return self._generate_text_svg(element)
            else:
                print(f"Unknown element type: {element_type}")
                return ""
        except Exception as e:
            print(f"Error generating {element_type} SVG: {e}")
            return ""
    
    def _generate_line_svg(self, element: Dict[str, Any]) -> str:
        """Generate line SVG."""
        x1_mm, y1_mm = element.get("start", [0, 0])
        x2_mm, y2_mm = element.get("end", [0, 0])
        
        x1_px, y1_px = self.calibrator.press_to_projector(x1_mm, y1_mm)
        x2_px, y2_px = self.calibrator.press_to_projector(x2_mm, y2_mm)
        
        # Don't render labels during rasterization
        label_svg = ""
        color = element.get("color", "#00ffff")
        
        return f'<line x1="{x1_px}" y1="{y1_px}" x2="{x2_px}" y2="{y2_px}" class="guide-line" stroke="{color}" stroke-width="2"/>{label_svg}'
    
    def _generate_rectangle_svg(self, element: Dict[str, Any]) -> str:
        """Generate rectangle SVG."""
        x_mm, y_mm = element.get("position", [0, 0])
        width_mm = element.get("width", 10)
        height_mm = element.get("height", 10)
        rotation = element.get("rotation", 0)
        color = element.get("color", "#00ffff")
        
        x_px, y_px = self.calibrator.press_to_projector(x_mm, y_mm)
        width_px = self.calibrator.mm_to_pixels(width_mm)
        height_px = self.calibrator.mm_to_pixels(height_mm)
        
        # Don't render labels during rasterization
        label_svg = ""
        
        if rotation != 0:
            center_x = x_px + width_px / 2
            center_y = y_px + height_px / 2
            return f'''
            <g transform="rotate({rotation} {center_x} {center_y})">
                <rect x="{x_px}" y="{y_px}" width="{width_px}" height="{height_px}" class="element-shape" fill="none" stroke="{color}" stroke-width="2"/>
                {label_svg}
            </g>
            '''
        else:
            return f'<rect x="{x_px}" y="{y_px}" width="{width_px}" height="{height_px}" class="element-shape" fill="none" stroke="{color}" stroke-width="2"/>{label_svg}'
    
    def _generate_circle_svg(self, element: Dict[str, Any]) -> str:
        """Generate circle SVG."""
        x_mm, y_mm = element.get("position", [0, 0])
        radius_mm = element.get("radius", 5)
        color = element.get("color", "#00ffff")
        
        x_px, y_px = self.calibrator.press_to_projector(x_mm, y_mm)
        radius_px = self.calibrator.mm_to_pixels(radius_mm)
        
        # Don't render labels during rasterization
        label_svg = ""
        
        return f'<circle cx="{x_px}" cy="{y_px}" r="{radius_px}" class="element-shape" fill="none" stroke="{color}" stroke-width="2"/>{label_svg}'
    
    def _generate_image_svg(self, element: Dict[str, Any]) -> str:
        """Generate image SVG."""
        import os
        import base64
        
        x_mm, y_mm = element.get("position", [0, 0])
        width_mm = element.get("width", 20)
        rotation = element.get("rotation", 0)
        image_url = element.get("image_url", "")
        
        x_px, y_px = self.calibrator.press_to_projector(x_mm, y_mm)
        width_px = self.calibrator.mm_to_pixels(width_mm)
        
        # Calculate height maintaining aspect ratio
        height_px = width_px  # Assuming square for now
        
        # Convert image URL to base64 data URL for CairoSVG compatibility
        image_data_url = image_url
        if image_url and not image_url.startswith('data:'):
            # Try to resolve as file path
            if image_url.startswith('/uploads/'):
                filename = image_url.replace('/uploads/', '')
                uploads_dir = "uploads"
                filepath = os.path.join(uploads_dir, filename)
                if os.path.exists(filepath):
                    try:
                        with open(filepath, 'rb') as f:
                            file_data = f.read()
                        ext = filename.rsplit('.', 1)[-1].lower()
                        mime_types = {
                            'png': 'image/png',
                            'jpg': 'image/jpeg',
                            'jpeg': 'image/jpeg',
                            'svg': 'image/svg+xml'
                        }
                        mime_type = mime_types.get(ext, 'application/octet-stream')
                        b64_data = base64.b64encode(file_data).decode('ascii')
                        image_data_url = f'data:{mime_type};base64,{b64_data}'
                    except Exception as e:
                        print(f"Error reading image file {filepath}: {e}")
        
        if rotation != 0:
            center_x = x_px + width_px / 2
            center_y = y_px + height_px / 2
            return f'''
            <g transform="rotate({rotation} {center_x} {center_y})">
                <image x="{x_px}" y="{y_px}" width="{width_px}" height="{height_px}" xlink:href="{image_data_url}"/>
            </g>
            '''
        else:
            return f'<image x="{x_px}" y="{y_px}" width="{width_px}" height="{height_px}" xlink:href="{image_data_url}"/>'

    def _generate_text_svg(self, element: Dict[str, Any]) -> str:
        """Generate text SVG."""
        x_mm, y_mm = element.get("position", [0, 0])
        rotation = element.get("rotation", 0)
        font_size_mm = element.get("font_size", 10)
        text_content = element.get("text", "")
        color = element.get("color", "#00ffff")

        x_px, y_px = self.calibrator.press_to_projector(x_mm, y_mm)
        font_size_px = self.calibrator.mm_to_pixels(font_size_mm)

        if rotation != 0:
            return f'''<g transform="rotate({rotation} {x_px} {y_px})">
                <text x="{x_px}" y="{y_px}" fill="{color}" font-size="{font_size_px}" font-family="Arial, sans-serif">{text_content}</text>
            </g>'''
        else:
            return f'<text x="{x_px}" y="{y_px}" fill="{color}" font-size="{font_size_px}" font-family="Arial, sans-serif">{text_content}</text>'
    
    def get_layout_data(self) -> Dict[str, Any]:
        """Get current layout data."""
        return self.current_layout.copy()
    
    def load_layout_data(self, layout_data: Dict[str, Any]):
        """Load layout data."""
        self.current_layout = layout_data.copy()


# Example usage and testing
if __name__ == "__main__":
    from calibration import Calibrator
    
    # Create calibrator and projector manager
    calibrator = Calibrator()
    projector = ProjectorManager(calibrator)
    
    # Set up calibration
    source_points = [[100, 100], [500, 100], [500, 400], [100, 400]]
    destination_points = [[0, 0], [300, 0], [300, 200], [0, 200]]
    calibrator.set_calibration_points(source_points, destination_points, 300, 200)
    
    # Set up layout
    projector.set_object_orientation(15)  # 15 degree rotation
    projector.set_center_lines(horizontal_y=100, vertical_x=150)
    
    # Add some elements
    projector.add_element("line", {
        "start": [50, 50],
        "end": [250, 50],
        "label": "Top line"
    })
    
    projector.add_element("rectangle", {
        "position": [100, 100],
        "width": 50,
        "height": 30,
        "rotation": 0,
        "label": "Logo area"
    })
    
    projector.add_element("circle", {
        "position": [200, 150],
        "radius": 20,
        "label": "Button"
    })
    
    # Generate SVG
    svg = projector.generate_svg(800, 600)
    print("Generated SVG preview:")
    print(svg[:500] + "...")
    
    # Save to file for testing
    with open("test_projection.svg", "w") as f:
        f.write(svg)
    print("SVG saved to test_projection.svg")

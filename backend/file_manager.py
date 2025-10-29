"""
File management system for handling design files and uploads.
Supports image files (PNG, JPEG) and SVG files.
"""

import os
import uuid
from typing import List, Dict, Any, Optional
from werkzeug.utils import secure_filename
import json


class FileManager:
    """Handles file uploads, storage, and processing."""
    
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'svg'}
    MAX_FILE_SIZE = 16 * 1024 * 1024  # 16MB
    
    def __init__(self, upload_dir: str = "uploads"):
        self.upload_dir = upload_dir
        os.makedirs(upload_dir, exist_ok=True)
    
    def is_allowed_file(self, filename: str) -> bool:
        """Check if file extension is allowed."""
        return ('.' in filename and 
                filename.rsplit('.', 1)[1].lower() in self.ALLOWED_EXTENSIONS)
    
    def generate_unique_filename(self, original_filename: str) -> str:
        """Generate unique filename to avoid conflicts."""
        name, ext = os.path.splitext(original_filename)
        unique_id = str(uuid.uuid4())[:8]
        return f"{secure_filename(name)}_{unique_id}{ext}"
    
    def save_uploaded_file(self, file, filename: str = None) -> Dict[str, Any]:
        """
        Save uploaded file and return file info.
        
        Args:
            file: Uploaded file object
            filename: Optional custom filename
        
        Returns:
            Dict with file information
        """
        if not file or not self.is_allowed_file(file.filename):
            raise ValueError("Invalid file type")
        
        if file.content_length and file.content_length > self.MAX_FILE_SIZE:
            raise ValueError("File too large")
        
        # Generate filename
        if not filename:
            filename = self.generate_unique_filename(file.filename)
        
        # Ensure filename is secure
        filename = secure_filename(filename)
        
        # Save file
        filepath = os.path.join(self.upload_dir, filename)
        file.save(filepath)
        
        # Get file info
        file_size = os.path.getsize(filepath)
        file_ext = filename.rsplit('.', 1)[1].lower()
        
        return {
            "filename": filename,
            "filepath": filepath,
            "original_name": file.filename,
            "size": file_size,
            "extension": file_ext,
            "url": f"/uploads/{filename}"
        }
    
    def delete_file(self, filename: str) -> bool:
        """Delete a file."""
        try:
            filepath = os.path.join(self.upload_dir, filename)
            if os.path.exists(filepath):
                os.remove(filepath)
                return True
            return False
        except Exception as e:
            print(f"Error deleting file {filename}: {e}")
            return False
    
    def list_files(self) -> List[Dict[str, Any]]:
        """List all uploaded files."""
        files = []
        try:
            for filename in os.listdir(self.upload_dir):
                filepath = os.path.join(self.upload_dir, filename)
                if os.path.isfile(filepath):
                    file_size = os.path.getsize(filepath)
                    file_ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
                    
                    files.append({
                        "filename": filename,
                        "size": file_size,
                        "extension": file_ext,
                        "url": f"/uploads/{filename}"
                    })
        except Exception as e:
            print(f"Error listing files: {e}")
        
        return files
    
    def get_file_info(self, filename: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific file."""
        try:
            filepath = os.path.join(self.upload_dir, filename)
            if os.path.exists(filepath):
                file_size = os.path.getsize(filepath)
                file_ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
                
                return {
                    "filename": filename,
                    "filepath": filepath,
                    "size": file_size,
                    "extension": file_ext,
                    "url": f"/uploads/{filename}"
                }
        except Exception as e:
            print(f"Error getting file info for {filename}: {e}")
        
        return None
    
    def process_svg_file(self, filepath: str) -> Dict[str, Any]:
        """
        Process SVG file to extract useful information.
        
        Args:
            filepath: Path to SVG file
        
        Returns:
            Dict with SVG processing results
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            
            # Basic SVG analysis
            result = {
                "valid": True,
                "content": svg_content,
                "elements": self._extract_svg_elements(svg_content),
                "dimensions": self._extract_svg_dimensions(svg_content)
            }
            
            return result
            
        except Exception as e:
            print(f"Error processing SVG file {filepath}: {e}")
            return {
                "valid": False,
                "error": str(e),
                "content": "",
                "elements": [],
                "dimensions": {"width": 0, "height": 0}
            }
    
    def _extract_svg_elements(self, svg_content: str) -> List[Dict[str, Any]]:
        """Extract basic elements from SVG content."""
        elements = []
        
        # Simple regex-based extraction (could be improved with proper XML parsing)
        import re
        
        # Find all basic shapes
        shapes = [
            (r'<rect[^>]*>', 'rectangle'),
            (r'<circle[^>]*>', 'circle'),
            (r'<line[^>]*>', 'line'),
            (r'<polygon[^>]*>', 'polygon'),
            (r'<path[^>]*>', 'path')
        ]
        
        for pattern, shape_type in shapes:
            matches = re.findall(pattern, svg_content, re.IGNORECASE)
            for match in matches:
                elements.append({
                    "type": shape_type,
                    "content": match
                })
        
        return elements
    
    def _extract_svg_dimensions(self, svg_content: str) -> Dict[str, float]:
        """Extract width and height from SVG."""
        import re
        
        width_match = re.search(r'width="([^"]*)"', svg_content, re.IGNORECASE)
        height_match = re.search(r'height="([^"]*)"', svg_content, re.IGNORECASE)
        
        width = 0
        height = 0
        
        if width_match:
            try:
                width = float(width_match.group(1).replace('px', ''))
            except ValueError:
                width = 0
        
        if height_match:
            try:
                height = float(height_match.group(1).replace('px', ''))
            except ValueError:
                height = 0
        
        return {"width": width, "height": height}
    
    def create_helping_lines_svg(self, lines_data: List[Dict[str, Any]]) -> str:
        """
        Create SVG with helping lines based on design.
        
        Args:
            lines_data: List of line definitions
        
        Returns:
            SVG string with helping lines
        """
        svg_lines = []
        
        for line in lines_data:
            x1 = line.get("x1", 0)
            y1 = line.get("y1", 0)
            x2 = line.get("x2", 0)
            y2 = line.get("y2", 0)
            stroke = line.get("stroke", "#00ff00")
            stroke_width = line.get("stroke_width", 2)
            dash_array = line.get("dash_array", "5,5")
            
            svg_lines.append(
                f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                f'stroke="{stroke}" stroke-width="{stroke_width}" '
                f'stroke-dasharray="{dash_array}"/>'
            )
        
        return '\n'.join(svg_lines)
    
    def cleanup_old_files(self, max_age_days: int = 30):
        """Clean up files older than specified days."""
        import time
        
        current_time = time.time()
        cutoff_time = current_time - (max_age_days * 24 * 60 * 60)
        
        cleaned_count = 0
        try:
            for filename in os.listdir(self.upload_dir):
                filepath = os.path.join(self.upload_dir, filename)
                if os.path.isfile(filepath):
                    file_time = os.path.getmtime(filepath)
                    if file_time < cutoff_time:
                        os.remove(filepath)
                        cleaned_count += 1
        except Exception as e:
            print(f"Error during cleanup: {e}")
        
        return cleaned_count


# Example usage and testing
if __name__ == "__main__":
    file_manager = FileManager()
    
    # Test file listing
    files = file_manager.list_files()
    print(f"Found {len(files)} files:")
    for file_info in files:
        print(f"  {file_info['filename']} ({file_info['size']} bytes)")
    
    # Test SVG processing
    test_svg = '''<?xml version="1.0" encoding="UTF-8"?>
<svg width="200" height="100" xmlns="http://www.w3.org/2000/svg">
    <rect x="10" y="10" width="50" height="30" fill="red"/>
    <circle cx="100" cy="50" r="20" fill="blue"/>
    <line x1="150" y1="20" x2="180" y2="80" stroke="green" stroke-width="2"/>
</svg>'''
    
    # Save test SVG
    test_file = "test_design.svg"
    with open(os.path.join(file_manager.upload_dir, test_file), 'w') as f:
        f.write(test_svg)
    
    # Process it
    result = file_manager.process_svg_file(os.path.join(file_manager.upload_dir, test_file))
    print(f"\nSVG processing result:")
    print(f"  Valid: {result['valid']}")
    print(f"  Elements: {len(result['elements'])}")
    print(f"  Dimensions: {result['dimensions']}")
    
    # Test helping lines
    lines_data = [
        {"x1": 0, "y1": 50, "x2": 200, "y2": 50, "stroke": "#ff0000"},
        {"x1": 100, "y1": 0, "x2": 100, "y2": 100, "stroke": "#00ff00"}
    ]
    
    helping_lines_svg = file_manager.create_helping_lines_svg(lines_data)
    print(f"\nHelping lines SVG:\n{helping_lines_svg}")

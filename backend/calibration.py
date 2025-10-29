"""
OpenCV-based calibration system for perspective transformation.
Handles 4-point calibration and coordinate conversion.
"""

import cv2
import numpy as np
from typing import List, Tuple, Optional, Dict, Any
import json


class Calibrator:
    """Handles perspective transformation calibration and coordinate conversion."""
    
    def __init__(self):
        self.source_points = None  # Points in projector space
        self.destination_points = None  # Points in press space (mm)
        self.transformation_matrix = None
        self.press_width_mm = None
        self.press_height_mm = None
        self.pixels_per_mm = None

    
    
    def set_calibration_points(self, source_points: List[List[float]], 
                              destination_points: List[List[float]],
                              press_width_mm: float, press_height_mm: float) -> bool:
        """
        Set calibration points and compute transformation matrix.
        
        Args:
            source_points: 4 points in projector space (pixels) [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            destination_points: 4 corresponding points in press space (mm) [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            press_width_mm: Width of press area in mm
            press_height_mm: Height of press area in mm
        
        Returns:
            bool: True if calibration successful
        """
        if len(source_points) != 4 or len(destination_points) != 4:
            print("Error: Exactly 4 points required for calibration")
            return False
        
        self.source_points = np.array(source_points, dtype=np.float32)
        self.destination_points = np.array(destination_points, dtype=np.float32)
        self.press_width_mm = press_width_mm
        self.press_height_mm = press_height_mm
        
        # Compute matrix and pixels_per_mm using current factor
        self._recompute_matrix_and_ppm()
        print(f"Calibration successful. Pixels per mm: {self.pixels_per_mm:.2f}")
        return True

    def set_calibration_from_target(self, source_points: List[List[float]],
                                    target_width_px: int, target_height_px: int,
                                    press_width_mm: float, press_height_mm: float) -> bool:
        """Convenience: build destination rectangle from target raster size."""
        destination_points = [
            [0.0, 0.0],
            [float(target_width_px), 0.0],
            [float(target_width_px), float(target_height_px)],
            [0.0, float(target_height_px)]
        ]
        return self.set_calibration_points(source_points, destination_points, press_width_mm, press_height_mm)
    
    def is_calibrated(self) -> bool:
        """Check if calibration is complete."""
        return (self.transformation_matrix is not None and 
                self.pixels_per_mm is not None)
    
    def projector_to_press(self, x: float, y: float) -> Tuple[float, float]:
        """
        Convert projector coordinates to press coordinates (mm).
        
        Args:
            x, y: Coordinates in projector space (pixels)
        
        Returns:
            Tuple of (x, y) coordinates in press space (mm)
        """
        if not self.is_calibrated():
            raise ValueError("Calibration not complete")
        
        # Apply perspective transformation
        point = np.array([[[x, y]]], dtype=np.float32)
        transformed = cv2.perspectiveTransform(point, self.transformation_matrix)
        return float(transformed[0][0][0]), float(transformed[0][0][1])
    
    def press_to_projector(self, x_mm: float, y_mm: float) -> Tuple[float, float]:
        """
        Convert press coordinates to projector coordinates (pixels).
        
        Args:
            x_mm, y_mm: Coordinates in press space (mm)
        
        Returns:
            Tuple of (x, y) coordinates in projector space (pixels)
        """
        if not self.is_calibrated():
            raise ValueError("Calibration not complete")
        
        # Apply inverse perspective transformation
        inv_matrix = np.linalg.inv(self.transformation_matrix)
        point = np.array([[[x_mm, y_mm]]], dtype=np.float32)
        transformed = cv2.perspectiveTransform(point, inv_matrix)
        return float(transformed[0][0][0]), float(transformed[0][0][1])
    
    def mm_to_pixels(self, mm_value: float) -> float:
        """Convert mm to pixels using calibration data."""
        if not self.is_calibrated():
            raise ValueError("Calibration not complete")
        return mm_value * self.pixels_per_mm
    
    def pixels_to_mm(self, pixel_value: float) -> float:
        """Convert pixels to mm using calibration data."""
        if not self.is_calibrated():
            raise ValueError("Calibration not complete")
        return pixel_value / self.pixels_per_mm
    
    def generate_press_boundary_pattern(self, margin_mm: float = 5.0) -> List[List[float]]:
        """
        Generate press boundary pattern for alignment verification.
        
        Args:
            margin_mm: Margin around press area in mm
        
        Returns:
            List of 4 corner points in projector space (pixels)
        """
        if not self.is_calibrated():
            raise ValueError("Calibration not complete")
        
        # Define press area corners with margin
        corners_mm = [
            [-margin_mm, -margin_mm],
            [self.press_width_mm + margin_mm, -margin_mm],
            [self.press_width_mm + margin_mm, self.press_height_mm + margin_mm],
            [-margin_mm, self.press_height_mm + margin_mm]
        ]
        
        # Convert to projector coordinates
        projector_corners = []
        for x_mm, y_mm in corners_mm:
            x_px, y_px = self.press_to_projector(x_mm, y_mm)
            projector_corners.append([x_px, y_px])
        
        return projector_corners
    
    def get_calibration_data(self) -> Dict[str, Any]:
        """Get calibration data for saving."""
        if not self.is_calibrated():
            return {}
        
        # Derive target pixel size from destination rectangle
        try:
            dw = float(self.destination_points[1][0] - self.destination_points[0][0])
            dh = float(self.destination_points[2][1] - self.destination_points[1][1])
        except Exception:
            dw, dh = 0.0, 0.0

        return {
            "projector_pixels": self.source_points.tolist(),
            "target_pixels": {"width": int(round(dw)), "height": int(round(dh))},
            "press_width_mm": self.press_width_mm,
            "press_height_mm": self.press_height_mm,
            # Do not persist transformation_matrix
            "pixels_per_mm": round(self.pixels_per_mm, 3)
        }
    
    def load_calibration_data(self, data: Dict[str, Any]) -> bool:
        """Load calibration data from saved data."""
        try:
            # Require new key 'projector_pixels'
            self.source_points = np.array(data["projector_pixels"], dtype=np.float32)
            # Require new target_pixels format
            tp = data["target_pixels"]
            tw = int(tp.get("width", 0))
            th = int(tp.get("height", 0))
            self.destination_points = np.array([[0,0],[tw,0],[tw,th],[0,th]], dtype=np.float32)
            self.press_width_mm = data["press_width_mm"]
            self.press_height_mm = data["press_height_mm"]
            # Recompute matrix and pixels_per_mm from points and sizes
            self._recompute_matrix_and_ppm()
            return True
        except KeyError as e:
            print(f"Error loading calibration data: missing key {e}")
            return False

    def _recompute_matrix_and_ppm(self) -> None:
        """Recompute perspective matrix and pixels_per_mm using current state."""
        if self.source_points is None or self.destination_points is None:
            self.transformation_matrix = None
            self.pixels_per_mm = None
            return
        # Compute transformation matrix using raw source points
        self.transformation_matrix = cv2.getPerspectiveTransform(
            self.source_points, self.destination_points
        )
        # Compute pixels_per_mm based on projector pixel space (unscaled)
        try:
            src_width = np.linalg.norm(self.source_points[1] - self.source_points[0])
            src_height = np.linalg.norm(self.source_points[2] - self.source_points[1])
            if self.press_width_mm and self.press_height_mm and self.press_width_mm > 0 and self.press_height_mm > 0:
                ppm_w = src_width / float(self.press_width_mm)
                ppm_h = src_height / float(self.press_height_mm)
                self.pixels_per_mm = (ppm_w + ppm_h) / 2.0
            else:
                self.pixels_per_mm = 1.0
        except Exception:
            self.pixels_per_mm = 1.0
    
    def validate_calibration_quality(self) -> Dict[str, Any]:
        """
        Validate calibration quality and return metrics.
        
        Returns:
            Dict with validation results
        """
        if not self.is_calibrated():
            return {"valid": False, "error": "No calibration data"}
        
        # Test transformation accuracy by round-trip conversion
        test_points = [
            [0, 0],
            [self.press_width_mm, 0],
            [self.press_width_mm, self.press_height_mm],
            [0, self.press_height_mm]
        ]
        
        errors = []
        for x_mm, y_mm in test_points:
            x_px, y_px = self.press_to_projector(x_mm, y_mm)
            x_mm_back, y_mm_back = self.projector_to_press(x_px, y_px)
            
            error = np.sqrt((x_mm - x_mm_back)**2 + (y_mm - y_mm_back)**2)
            errors.append(error)
        
        max_error = max(errors)
        avg_error = sum(errors) / len(errors)
        
        return {
            "valid": max_error < 1.0,  # Less than 1mm error
            "max_error_mm": max_error,
            "avg_error_mm": avg_error,
            "pixels_per_mm": self.pixels_per_mm
        }


# Example usage and testing
if __name__ == "__main__":
    calibrator = Calibrator()
    
    # Example calibration points
    source_points = [[100, 100], [500, 100], [500, 400], [100, 400]]
    destination_points = [[0, 0], [300, 0], [300, 200], [0, 200]]
    
    success = calibrator.set_calibration_points(
        source_points, destination_points, 300, 200
    )
    
    if success:
        print("Calibration successful!")
        
        # Test coordinate conversion
        test_x, test_y = calibrator.press_to_projector(150, 100)
        print(f"Press (150, 100) -> Projector ({test_x:.1f}, {test_y:.1f})")
        
        test_x_back, test_y_back = calibrator.projector_to_press(test_x, test_y)
        print(f"Projector ({test_x:.1f}, {test_y:.1f}) -> Press ({test_x_back:.1f}, {test_y_back:.1f})")
        
        # Test scaling
        print(f"10mm = {calibrator.mm_to_pixels(10):.1f} pixels")
        print(f"100 pixels = {calibrator.pixels_to_mm(100):.1f}mm")
        
        # Generate boundary pattern
        boundary = calibrator.generate_press_boundary_pattern()
        print(f"Press boundary pattern: {boundary}")
        
        # Validate calibration
        validation = calibrator.validate_calibration_quality()
        print(f"Calibration validation: {validation}")

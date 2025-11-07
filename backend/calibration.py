"""
OpenCV-based calibration system for perspective transformation.
Handles 4-point calibration and coordinate conversion.
"""

import cv2
import numpy as np
from typing import List, Tuple, Dict, Any





class Calibrator:
    """Handles perspective transformation calibration and coordinate conversion."""
    
    # Default raster density when converting press dimensions to pixels for raw renders
    PIXELS_PER_MM = 10

    def __init__(self):
        self.source_points = None  # Points in projector space
        self.destination_points = None  # Points in press raster space (pixels)
        self.transformation_matrix = None
        self.press_width_mm = None
        self.press_height_mm = None

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
            return False
        
        self.source_points = np.array(source_points, dtype=np.float32)
        self.destination_points = np.array(destination_points, dtype=np.float32)
        self.press_width_mm = press_width_mm
        self.press_height_mm = press_height_mm
        
        self._recompute_warp_matrix()
        return True


    @property
    def raw_width_px(self) -> int:
        if self.press_width_mm is None:
            raise ValueError("press_width_mm not set")
        return int(round(float(self.press_width_mm) * self.PIXELS_PER_MM))

    @property
    def raw_height_px(self) -> int:
        if self.press_height_mm is None:
            raise ValueError("press_height_mm not set")
        return int(round(float(self.press_height_mm) * self.PIXELS_PER_MM))

    def set_calibration_from_target(self, source_points: List[List[float]],
                                    press_width_mm: float, press_height_mm: float) -> bool:
        """Convenience: build destination rectangle from target raster size."""

        self.press_width_mm = press_width_mm
        self.press_height_mm = press_height_mm

        destination_points = [
            [0.0, 0.0],
            [float(self.raw_width_px), 0.0],
            [float(self.raw_width_px), float(self.raw_height_px)],
            [0.0, float(self.raw_height_px)]
        ]
        return self.set_calibration_points(source_points, destination_points, press_width_mm, press_height_mm)
    
    def is_calibrated(self) -> bool:
        """Check if calibration is complete."""
        return self.transformation_matrix is not None
    

    def get_calibration_data(self) -> Dict[str, Any]:
        """Get calibration data for saving."""
        if not self.is_calibrated():
            return {}
        
        return {
            "projector_pixels": self.source_points.tolist(),
            "press_width_mm": self.press_width_mm,
            "press_height_mm": self.press_height_mm,
        }
    
    def get_raw_size_px(self) -> Tuple[int, int]:
        """Get raw size in pixels."""
        return self.raw_width_px, self.raw_height_px
    
    def load_calibration_data(self, data: Dict[str, Any]) -> bool:
        """Load calibration data from saved data."""

        self.press_width_mm = data["press_width_mm"]
        self.press_height_mm = data["press_height_mm"]
        self.source_points = np.array(data["projector_pixels"], dtype=np.float32)
        self.destination_points = np.array([[0,0],[self.raw_width_px,0],[self.raw_width_px,self.raw_height_px],[0,self.raw_height_px]], dtype=np.float32)

        self._recompute_warp_matrix()

        return True

    def _recompute_warp_matrix(self) -> None:
        """Recompute perspective warp matrix using current state."""
        if self.source_points is None or self.destination_points is None:
            self.transformation_matrix = None
            return
        # Compute transformation matrix using raw source points
        self.transformation_matrix = cv2.getPerspectiveTransform(
            self.source_points, self.destination_points
        )



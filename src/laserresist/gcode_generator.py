"""G-code generation from fill patterns."""

from typing import List, TextIO, Optional
from shapely.geometry import LineString


class GCodeGenerator:
    """Generate G-code for laser exposure."""

    def __init__(
        self,
        laser_power: float = 2.0,
        feed_rate: float = 1400.0,
        travel_rate: float = 6000.0,
        laser_max_power: int = 255,
        x_offset: float = 0.0,
        y_offset: float = 0.0,
        z_height: float = 20.0,
        normalize_origin: bool = True,
        bed_mesh_calibrate: bool = False,
        mesh_offset: float = 3.0,
        probe_count: tuple = (3, 3),
        laser_arm_command: Optional[str] = None,
        laser_disarm_command: Optional[str] = None,
    ):
        """Initialize the G-code generator.

        Args:
            laser_power: Laser power percentage (0-100), default 2%
            feed_rate: Feed rate for laser moves in mm/min, default 1400
            travel_rate: Rapid travel rate in mm/min, default 6000
            laser_max_power: Maximum S value for M3 command (usually 255), default 255
            x_offset: Additional X offset in mm (after normalization), default 0
            y_offset: Additional Y offset in mm (after normalization), default 0
            z_height: Z height for laser focus in mm, default 20
            normalize_origin: If True, shift coordinates so min becomes (0,0), default True
            bed_mesh_calibrate: If True, run bed mesh calibration before exposure, default False
            mesh_offset: Offset from board edges for mesh calibration in mm, default 3
            probe_count: Number of probe points (x, y) for mesh calibration, default (3, 3)
            laser_arm_command: Optional command to arm/enable laser (e.g., "ARM_LASER"), default None
            laser_disarm_command: Optional command to disarm/disable laser (e.g., "DISARM_LASER"), default None
        """
        self.laser_power = laser_power
        self.feed_rate = feed_rate
        self.travel_rate = travel_rate
        self.laser_max_power = laser_max_power
        self.x_offset = x_offset
        self.y_offset = y_offset
        self.z_height = z_height
        self.normalize_origin = normalize_origin
        self.bed_mesh_calibrate = bed_mesh_calibrate
        self.mesh_offset = mesh_offset
        self.probe_count = probe_count
        self.laser_arm_command = laser_arm_command
        self.laser_disarm_command = laser_disarm_command

        # Calculate S parameter for M3 command (0-255 scale)
        self.laser_s_value = int((laser_power / 100.0) * laser_max_power)

    def generate(self, paths: List[LineString], output_file: TextIO, bounds: tuple = None, board_outline_bounds: tuple = None):
        """Generate G-code from fill paths.

        Args:
            paths: List of LineString paths to trace
            output_file: File handle to write G-code to
            bounds: Optional bounding box of copper geometry (min_x, min_y, max_x, max_y)
            board_outline_bounds: Optional board outline bounds for coordinate normalization
        """
        if not paths:
            raise ValueError("No paths provided for G-code generation")

        # Calculate coordinate transformation
        if bounds:
            min_x, min_y, max_x, max_y = bounds
        else:
            # Calculate bounds from paths if not provided
            all_coords = [coord for path in paths for coord in path.coords]
            min_x = min(x for x, y in all_coords)
            min_y = min(y for x, y in all_coords)
            max_x = max(x for x, y in all_coords)
            max_y = max(y for x, y in all_coords)
            bounds = (min_x, min_y, max_x, max_y)

        # Use board outline for normalization if provided, otherwise use copper bounds
        if board_outline_bounds:
            norm_min_x, norm_min_y, norm_max_x, norm_max_y = board_outline_bounds
        else:
            norm_min_x, norm_min_y, norm_max_x, norm_max_y = min_x, min_y, max_x, max_y

        # Calculate transformation offsets
        if self.normalize_origin:
            self.transform_x = -norm_min_x + self.x_offset
            self.transform_y = -norm_min_y + self.y_offset
        else:
            self.transform_x = self.x_offset
            self.transform_y = self.y_offset

        # Calculate transformed bounds for header
        transformed_bounds = (
            min_x + self.transform_x,
            min_y + self.transform_y,
            max_x + self.transform_x,
            max_y + self.transform_y
        )

        # Store board outline bounds for bed mesh calculation
        self.board_outline_bounds = board_outline_bounds

        # TODO: Calculate time estimate
        # TODO: Add custom start G-code support
        # TODO: Add M73 progress reporting

        self._write_header(output_file, bounds, transformed_bounds, board_outline_bounds)
        self._write_paths(output_file, paths)
        self._write_footer(output_file)

    def _write_header(self, f: TextIO, original_bounds: Optional[tuple] = None, transformed_bounds: Optional[tuple] = None, board_outline_bounds: Optional[tuple] = None):
        """Write G-code header with initialization commands.

        Args:
            f: File handle
            original_bounds: Original bounding box from copper Gerber
            transformed_bounds: Transformed bounding box after offset
            board_outline_bounds: Board outline bounding box
        """
        f.write("; G-code generated by LaserResist\n")
        f.write("; Laser PCB photoresist exposure\n")
        f.write(";\n")
        f.write(f"; Laser power: {self.laser_power}% (S{self.laser_s_value})\n")
        f.write(f"; Feed rate: {self.feed_rate} mm/min\n")
        f.write(f"; Travel rate: {self.travel_rate} mm/min\n")
        f.write(f"; Z height (focus): {self.z_height} mm\n")

        if board_outline_bounds:
            b_min_x, b_min_y, b_max_x, b_max_y = board_outline_bounds
            width = b_max_x - b_min_x
            height = b_max_y - b_min_y
            f.write(";\n")
            f.write(f"; Board outline bounds: ({b_min_x:.2f}, {b_min_y:.2f}) to ({b_max_x:.2f}, {b_max_y:.2f}) mm\n")
            f.write(f"; Board dimensions: {width:.2f} x {height:.2f} mm\n")

        if original_bounds:
            min_x, min_y, max_x, max_y = original_bounds
            width = max_x - min_x
            height = max_y - min_y
            f.write(";\n")
            f.write(f"; Copper layer bounds: ({min_x:.2f}, {min_y:.2f}) to ({max_x:.2f}, {max_y:.2f}) mm\n")
            f.write(f"; Copper dimensions: {width:.2f} x {height:.2f} mm\n")

        if transformed_bounds:
            t_min_x, t_min_y, t_max_x, t_max_y = transformed_bounds
            f.write(";\n")
            f.write(f"; Coordinate transformation:\n")
            f.write(f";   Normalize origin: {self.normalize_origin}\n")
            if board_outline_bounds:
                f.write(f";   Reference: Board outline\n")
            else:
                f.write(f";   Reference: Copper bounds\n")
            f.write(f";   X offset: {self.x_offset:.2f} mm\n")
            f.write(f";   Y offset: {self.y_offset:.2f} mm\n")
            f.write(f";   Applied transform: X{self.transform_x:+.2f}, Y{self.transform_y:+.2f}\n")
            f.write(f"; Output copper bounds: ({t_min_x:.2f}, {t_min_y:.2f}) to ({t_max_x:.2f}, {t_max_y:.2f}) mm\n")

        f.write(";\n")
        f.write("; TODO: Time estimate will be displayed here\n")
        f.write(";\n\n")

        # TODO: Custom start G-code will be inserted here

        # Standard initialization
        f.write("; Initialization\n")
        f.write("G28         ; Home all axes\n")
        f.write("G21         ; Set units to millimeters\n")
        f.write("G90         ; Absolute positioning\n")
        f.write("M83         ; Relative extruder mode\n")
        f.write("M5          ; Ensure laser is off\n")

        # Bed mesh calibration (optional)
        if self.bed_mesh_calibrate and board_outline_bounds:
            self._write_bed_mesh_calibration(f, board_outline_bounds)

        f.write(f"G0 F{self.travel_rate}  ; Set travel speed\n")
        f.write(f"G0 Z{self.z_height}  ; Move to focus height\n")

        # Arm laser (optional)
        if self.laser_arm_command:
            f.write("\n")
            f.write("; Arm laser (enable relay)\n")
            f.write(f"{self.laser_arm_command}\n")

        f.write("\n")

    def _write_paths(self, f: TextIO, paths: List[LineString]):
        """Write G-code for all laser paths.

        Args:
            f: File handle
            paths: List of paths to trace
        """
        f.write("; Begin laser exposure\n")
        f.write(f"G1 F{self.feed_rate}  ; Set exposure speed\n\n")

        total_paths = len(paths)

        for i, path in enumerate(paths):
            # TODO: Add M73 progress reporting every N paths

            coords = list(path.coords)
            if len(coords) < 2:
                continue  # Skip degenerate paths

            # Comment with path info
            f.write(f"; Path {i+1}/{total_paths} (length: {path.length:.2f}mm)\n")

            # Apply coordinate transformation
            start_x, start_y = coords[0]
            start_x_transformed = start_x + self.transform_x
            start_y_transformed = start_y + self.transform_y

            # Rapid to start position with laser off
            f.write(f"G0 X{start_x_transformed:.4f} Y{start_y_transformed:.4f}  ; Move to start\n")

            # Turn laser on
            f.write(f"M3 S{self.laser_s_value}  ; Laser on\n")

            # Trace the path with transformed coordinates
            for x, y in coords[1:]:
                x_transformed = x + self.transform_x
                y_transformed = y + self.transform_y
                f.write(f"G1 X{x_transformed:.4f} Y{y_transformed:.4f}\n")

            # Turn laser off
            f.write("M5  ; Laser off\n")
            f.write("\n")

    def _write_bed_mesh_calibration(self, f: TextIO, board_outline_bounds: tuple):
        """Write bed mesh calibration command.

        Args:
            f: File handle
            board_outline_bounds: Board outline bounds in original coordinates
        """
        # Calculate board dimensions
        b_min_x, b_min_y, b_max_x, b_max_y = board_outline_bounds
        board_width = b_max_x - b_min_x
        board_height = b_max_y - b_min_y

        # Calculate mesh bounds with offset from edges
        # Since we normalize to (0, 0), the board spans from (0, 0) to (board_width, board_height)
        mesh_min_x = 0 + self.mesh_offset
        mesh_min_y = 0 + self.mesh_offset
        mesh_max_x = board_width - self.mesh_offset
        mesh_max_y = board_height - self.mesh_offset

        # Validate mesh bounds
        if mesh_max_x <= mesh_min_x or mesh_max_y <= mesh_min_y:
            f.write("; WARNING: Mesh offset too large for board size, skipping bed mesh calibration\n")
            return

        f.write("\n")
        f.write("; Bed mesh calibration\n")
        f.write(f"BED_MESH_CALIBRATE MESH_MIN={mesh_min_x:.2f},{mesh_min_y:.2f} MESH_MAX={mesh_max_x:.2f},{mesh_max_y:.2f} PROBE_COUNT={self.probe_count[0]},{self.probe_count[1]}\n")
        f.write("\n")

    def _write_footer(self, f: TextIO):
        """Write G-code footer with shutdown commands.

        Args:
            f: File handle
        """
        f.write("; End of exposure\n")
        f.write("M5          ; Ensure laser is off\n")

        # Disarm laser (optional)
        if self.laser_disarm_command:
            f.write(f"{self.laser_disarm_command}  ; Disarm laser (disable relay)\n")

        f.write("G0 X0 Y0    ; Return to origin\n")
        f.write("\n")

        # TODO: Custom end G-code will be inserted here

        f.write("; Program complete\n")
        f.write("M84         ; Disable motors\n")

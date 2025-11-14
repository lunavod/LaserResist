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
        flip_horizontal: bool = False,
        bed_mesh_calibrate: bool = False,
        mesh_offset: float = 3.0,
        probe_count: tuple = (3, 3),
        laser_arm_command: Optional[str] = None,
        laser_disarm_command: Optional[str] = None,
        draw_outline: bool = False,
        outline_offset_count: int = 0,
        outline_offset_spacing: float = 0.1,
        pin_transform: Optional[dict] = None,
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
            flip_horizontal: If True, flip board horizontally (mirror X axis), typically used for bottom layer, default False
            bed_mesh_calibrate: If True, run bed mesh calibration before exposure, default False
            mesh_offset: Offset from board edges for mesh calibration in mm, default 3
            probe_count: Number of probe points (x, y) for mesh calibration, default (3, 3)
            laser_arm_command: Optional command to arm/enable laser (e.g., "ARM_LASER"), default None
            laser_disarm_command: Optional command to disarm/disable laser (e.g., "DISARM_LASER"), default None
            draw_outline: If True, draw board outline before exposure (for positioning), default False
            outline_offset_count: Number of offset copies: 0=single outline, -1=one outward copy, +1=one inward copy, etc.
            outline_offset_spacing: Spacing between offset copies in mm, default 0.1
            pin_transform: Optional pin alignment transformation dict with keys: rotate_180, translate_x, translate_y, origin_x, origin_y
        """
        self.laser_power = laser_power
        self.feed_rate = feed_rate
        self.travel_rate = travel_rate
        self.laser_max_power = laser_max_power
        self.x_offset = x_offset
        self.y_offset = y_offset
        self.z_height = z_height
        self.normalize_origin = normalize_origin
        self.flip_horizontal = flip_horizontal
        self.bed_mesh_calibrate = bed_mesh_calibrate
        self.mesh_offset = mesh_offset
        self.probe_count = probe_count
        self.laser_arm_command = laser_arm_command
        self.laser_disarm_command = laser_disarm_command
        self.draw_outline = draw_outline
        self.outline_offset_count = outline_offset_count
        self.outline_offset_spacing = outline_offset_spacing
        self.pin_transform = pin_transform

        # Calculate S parameter for M3 command (0-255 scale)
        self.laser_s_value = int((laser_power / 100.0) * laser_max_power)

    def generate(self, paths: List[LineString], output_file: TextIO, bounds: tuple = None, board_outline_bounds: tuple = None, isolated_paths: List[LineString] = None):
        """Generate G-code from fill paths.

        Args:
            paths: List of LineString paths to trace
            output_file: File handle to write G-code to
            bounds: Optional bounding box of copper geometry (min_x, min_y, max_x, max_y)
            board_outline_bounds: Optional board outline bounds for coordinate normalization
            isolated_paths: Optional list of isolated paths to be exposed twice (drawn after main paths)
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

        # Calculate flip center (use board outline center for consistent flipping)
        if self.flip_horizontal:
            if board_outline_bounds:
                self.flip_center_x = (board_outline_bounds[0] + board_outline_bounds[2]) / 2
            else:
                self.flip_center_x = (min_x + max_x) / 2
        else:
            self.flip_center_x = 0  # Not used

        # Calculate transformation offsets
        # Pin alignment takes precedence over normal normalization
        if self.pin_transform:
            # Pin alignment mode - apply rotation and translation
            self.transform_x = self.pin_transform['translate_x'] + self.x_offset
            self.transform_y = self.pin_transform['translate_y'] + self.y_offset
            self.rotate_180 = self.pin_transform['rotate_180']

            # Calculate center point for 180° rotation (around the pin origin)
            self.rotation_center_x = self.pin_transform['origin_x']
            self.rotation_center_y = self.pin_transform['origin_y']
        elif self.normalize_origin:
            self.transform_x = -norm_min_x + self.x_offset
            self.transform_y = -norm_min_y + self.y_offset
            self.rotate_180 = False
        else:
            self.transform_x = self.x_offset
            self.transform_y = self.y_offset
            self.rotate_180 = False

        # Calculate transformed bounds for header
        # Apply flip first if enabled
        if self.flip_horizontal:
            # Flip swaps min_x and max_x
            flipped_min_x = 2 * self.flip_center_x - max_x
            flipped_max_x = 2 * self.flip_center_x - min_x
            min_x, max_x = flipped_min_x, flipped_max_x

        if self.rotate_180:
            # After 180° rotation around center, bounds swap and invert relative to center
            cx, cy = self.rotation_center_x, self.rotation_center_y
            # Transform: rotate 180° around center, then translate
            # Point (x, y) -> (2*cx - x, 2*cy - y) -> (2*cx - x + tx, 2*cy - y + ty)
            transformed_bounds = (
                2*cx - max_x + self.transform_x,
                2*cy - max_y + self.transform_y,
                2*cx - min_x + self.transform_x,
                2*cy - min_y + self.transform_y
            )
        else:
            transformed_bounds = (
                min_x + self.transform_x,
                min_y + self.transform_y,
                max_x + self.transform_x,
                max_y + self.transform_y
            )

        # Store board outline bounds for bed mesh calculation
        self.board_outline_bounds = board_outline_bounds

        # Validate negative outline offsets (outward expansion)
        if self.draw_outline and self.outline_offset_count < 0:
            required_offset = abs(self.outline_offset_count) * self.outline_offset_spacing
            if self.x_offset < required_offset or self.y_offset < required_offset:
                print(f"\nWARNING: Negative outline offsets draw OUTSIDE the board!")
                print(f"  You specified {abs(self.outline_offset_count)} outward copies ({required_offset:.2f}mm)")
                print(f"  But x_offset={self.x_offset}mm, y_offset={self.y_offset}mm")
                print(f"  The board origin will shift by the outline offset!")
                print(f"  Set x_offset and y_offset to at least {required_offset:.2f}mm to avoid issues.")
                print(f"  Note: Negative offsets move the effective board position!")

        # Store isolated paths for use in _write_paths
        self.isolated_paths = isolated_paths

        # Calculate time estimate (including isolated paths if provided)
        all_paths_for_time = paths.copy()
        if isolated_paths:
            all_paths_for_time.extend(isolated_paths)
        self.time_estimate_minutes = self._calculate_time_estimate(all_paths_for_time)

        # TODO: Add custom start G-code support

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

            if self.pin_transform:
                f.write(f";   Mode: PIN ALIGNMENT\n")
                f.write(f";   Pin 1 origin: ({self.rotation_center_x:.2f}, {self.rotation_center_y:.2f}) mm\n")
                if self.flip_horizontal:
                    f.write(f";   Flip: Horizontal (mirrored for bottom layer)\n")
                if self.rotate_180:
                    f.write(f";   Rotation: 180° (board upside down)\n")
                else:
                    f.write(f";   Rotation: None (board normal orientation)\n")
                f.write(f";   X offset: {self.x_offset:.2f} mm (additional)\n")
                f.write(f";   Y offset: {self.y_offset:.2f} mm (additional)\n")
                f.write(f";   Applied transform: X{self.transform_x:+.2f}, Y{self.transform_y:+.2f}\n")
            else:
                f.write(f";   Normalize origin: {self.normalize_origin}\n")
                if board_outline_bounds:
                    f.write(f";   Reference: Board outline\n")
                else:
                    f.write(f";   Reference: Copper bounds\n")
                if self.flip_horizontal:
                    f.write(f";   Flip: Horizontal (mirrored for bottom layer)\n")
                f.write(f";   X offset: {self.x_offset:.2f} mm\n")
                f.write(f";   Y offset: {self.y_offset:.2f} mm\n")
                f.write(f";   Applied transform: X{self.transform_x:+.2f}, Y{self.transform_y:+.2f}\n")

            f.write(f"; Output copper bounds: ({t_min_x:.2f}, {t_min_y:.2f}) to ({t_max_x:.2f}, {t_max_y:.2f}) mm\n")

        f.write(";\n")
        # Format time estimate
        hours = int(self.time_estimate_minutes // 60)
        minutes = int(self.time_estimate_minutes % 60)
        seconds = int((self.time_estimate_minutes % 1) * 60)
        if hours > 0:
            f.write(f"; Estimated time: {hours}h {minutes}m {seconds}s ({self.time_estimate_minutes:.1f} minutes)\n")
        elif minutes > 0:
            f.write(f"; Estimated time: {minutes}m {seconds}s ({self.time_estimate_minutes:.1f} minutes)\n")
        else:
            f.write(f"; Estimated time: {seconds}s ({self.time_estimate_minutes:.2f} minutes)\n")
        f.write(";\n\n")

        # TODO: Custom start G-code will be inserted here

        # Check if using macro-based pin alignment
        use_macro = self.pin_transform and self.pin_transform.get('use_macro', False)

        # Initialization
        f.write("; Initialization\n")
        f.write("G21         ; Set units to millimeters\n")
        f.write("G90         ; Absolute positioning\n")
        f.write("M83         ; Relative extruder mode\n")
        f.write("M5          ; Ensure laser is off\n")
        f.write("\n")

        if use_macro:
            # Macro-based pin alignment using SETUP_PCB_SPACE
            f.write("; PCB coordinate system setup with macro\n")

            # Calculate board bounds relative to pin origin
            pin_x = self.pin_transform['origin_x']
            pin_y = self.pin_transform['origin_y']

            # Board outline bounds relative to pin
            if board_outline_bounds:
                b_min_x, b_min_y, b_max_x, b_max_y = board_outline_bounds
                bottom_left_x = b_min_x - pin_x
                bottom_left_y = b_min_y - pin_y
                top_right_x = b_max_x - pin_x
                top_right_y = b_max_y - pin_y

                f.write(f"; Board bounds relative to pin: BL=({bottom_left_x:.2f},{bottom_left_y:.2f}) TR=({top_right_x:.2f},{top_right_y:.2f})\n")

                # Call SETUP_PCB_SPACE macro
                f.write(f"SETUP_PCB_SPACE BOTTOM_LEFT_X={bottom_left_x:.2f} BOTTOM_LEFT_Y={bottom_left_y:.2f} ")
                f.write(f"TOP_RIGHT_X={top_right_x:.2f} TOP_RIGHT_Y={top_right_y:.2f} ")
                f.write(f"WORK_Z={self.z_height} ")
                if self.bed_mesh_calibrate:
                    f.write(f"MESH_OFFSET={self.mesh_offset} ")
                    f.write(f"PROBE_COUNT_X={self.probe_count[0]} PROBE_COUNT_Y={self.probe_count[1]}")
                f.write("\n")
            else:
                # No board outline, just basic setup
                f.write("; Warning: No board outline available, using defaults\n")
                f.write(f"SETUP_PCB_SPACE WORK_Z={self.z_height}\n")

            f.write("\n")
            f.write(f"G0 F{self.travel_rate}  ; Set travel speed\n")
            f.write("; PCB space ready - origin at pin center\n")
        else:
            # Standard homing
            f.write("G28         ; Home all axes\n")

            # Bed mesh calibration (optional)
            if self.bed_mesh_calibrate and board_outline_bounds:
                self._write_bed_mesh_calibration(f, board_outline_bounds, use_macro=False)

            f.write(f"G0 F{self.travel_rate}  ; Set travel speed\n")
            f.write(f"G0 Z{self.z_height}  ; Move to focus height\n")

        f.write("\n")

        # Arm laser (optional)
        if self.laser_arm_command:
            f.write("\n")
            f.write("; Arm laser (enable relay)\n")
            f.write(f"{self.laser_arm_command}\n")

        # Draw outline (optional)
        if self.draw_outline and board_outline_bounds:
            self._write_outline(f, board_outline_bounds)

        f.write("\n")

    def _write_paths(self, f: TextIO, paths: List[LineString]):
        """Write G-code for all laser paths.

        Args:
            f: File handle
            paths: List of paths to trace
        """
        f.write("; Begin laser exposure\n")
        f.write(f"G1 F{self.feed_rate}  ; Set exposure speed\n")
        f.write("M73 P0 R{:.0f}  ; Progress 0%, estimated time remaining\n\n".format(self.time_estimate_minutes))

        total_paths = len(paths)
        cumulative_time = 0.0  # Track elapsed time in minutes
        last_m73_time = 0.0  # Track when we last emitted M73
        m73_interval = 3.0 / 60.0  # 3 seconds in minutes (respects Klipper 5s timeout)
        prev_end_pos = None  # Track previous path end position for travel distance

        for i, path in enumerate(paths):
            coords = list(path.coords)
            if len(coords) < 2:
                continue  # Skip degenerate paths

            # Emit M73 if we've accumulated 3+ seconds since last update, or first/last path
            time_since_last_m73 = cumulative_time - last_m73_time
            if time_since_last_m73 >= m73_interval or i == 0 or i == total_paths - 1:
                current_progress_percent = min(100.0, (cumulative_time / self.time_estimate_minutes) * 100.0)
                remaining_minutes = max(0, self.time_estimate_minutes - cumulative_time)
                f.write(f"M73 P{current_progress_percent:.1f} R{int(remaining_minutes)}  ; Progress {current_progress_percent:.1f}%\n")
                last_m73_time = cumulative_time

            # Comment with path info
            f.write(f"; Path {i+1}/{total_paths} (length: {path.length:.2f}mm)\n")

            # Apply coordinate transformation (flip, rotate, translate)
            start_x, start_y = coords[0]

            # Step 1: Flip horizontal if enabled (mirror X around center)
            if self.flip_horizontal:
                start_x = 2 * self.flip_center_x - start_x

            # Step 2: Rotate 180° if enabled (pin alignment)
            if self.rotate_180:
                # Rotate 180° around center point, then translate
                cx, cy = self.rotation_center_x, self.rotation_center_y
                start_x_transformed = 2*cx - start_x + self.transform_x
                start_y_transformed = 2*cy - start_y + self.transform_y
            else:
                # Step 3: Just translate
                start_x_transformed = start_x + self.transform_x
                start_y_transformed = start_y + self.transform_y

            # Add travel time if not first path
            if prev_end_pos is not None:
                dx = start_x - prev_end_pos[0]
                dy = start_y - prev_end_pos[1]
                travel_distance = (dx**2 + dy**2) ** 0.5
                travel_time = travel_distance / self.travel_rate
                cumulative_time += travel_time

            # Rapid to start position with laser off
            f.write(f"G0 X{start_x_transformed:.4f} Y{start_y_transformed:.4f}  ; Move to start\n")

            # Turn laser on
            f.write(f"M3 S{self.laser_s_value}  ; Laser on\n")

            # Update cumulative time with path exposure time
            path_time = path.length / self.feed_rate
            cumulative_time += path_time

            # Trace the path with transformed coordinates
            for x, y in coords[1:]:
                # Step 1: Flip horizontal if enabled (mirror X around center)
                if self.flip_horizontal:
                    x = 2 * self.flip_center_x - x

                # Step 2: Rotate 180° if enabled (pin alignment)
                if self.rotate_180:
                    cx, cy = self.rotation_center_x, self.rotation_center_y
                    x_transformed = 2*cx - x + self.transform_x
                    y_transformed = 2*cy - y + self.transform_y
                else:
                    # Step 3: Just translate
                    x_transformed = x + self.transform_x
                    y_transformed = y + self.transform_y
                f.write(f"G1 X{x_transformed:.4f} Y{y_transformed:.4f}\n")

            # Turn laser off
            f.write("M5  ; Laser off\n")
            f.write("\n")

            # Store end position for next travel calculation
            prev_end_pos = coords[-1]

        # Write second pass for isolated features if provided
        if self.isolated_paths and len(self.isolated_paths) > 0:
            f.write("\n")
            f.write("; ==================================================\n")
            f.write("; SECOND PASS - Isolated features (blooming compensation)\n")
            f.write("; These paths are exposed twice for better coverage\n")
            f.write("; ==================================================\n")
            f.write("\n")
            f.write("G1 F{:.1f}  ; Set exposure speed\n".format(self.feed_rate))

            total_isolated = len(self.isolated_paths)
            for i, path in enumerate(self.isolated_paths):
                coords = list(path.coords)
                if len(coords) < 2:
                    continue

                # Update progress for isolated paths
                isolated_progress = ((total_paths + i) / (total_paths + total_isolated)) * 100.0
                isolated_remaining = max(0, self.time_estimate_minutes - cumulative_time)

                # Emit M73 for progress tracking
                time_since_last_m73 = cumulative_time - last_m73_time
                if time_since_last_m73 >= m73_interval or i == 0 or i == total_isolated - 1:
                    f.write(f"M73 P{isolated_progress:.1f} R{int(isolated_remaining)}  ; Isolated pass progress {isolated_progress:.1f}%\n")
                    last_m73_time = cumulative_time

                f.write(f"; Isolated path {i+1}/{total_isolated} (length: {path.length:.2f}mm)\n")

                # Transform start position
                start_x, start_y = coords[0]
                if self.flip_horizontal:
                    start_x = 2 * self.flip_center_x - start_x
                if self.rotate_180:
                    cx, cy = self.rotation_center_x, self.rotation_center_y
                    start_x_transformed = 2*cx - start_x + self.transform_x
                    start_y_transformed = 2*cy - start_y + self.transform_y
                else:
                    start_x_transformed = start_x + self.transform_x
                    start_y_transformed = start_y + self.transform_y

                # Add travel time
                if prev_end_pos is not None:
                    dx = start_x - prev_end_pos[0]
                    dy = start_y - prev_end_pos[1]
                    travel_distance = (dx**2 + dy**2) ** 0.5
                    travel_time = travel_distance / self.travel_rate
                    cumulative_time += travel_time

                f.write(f"G0 X{start_x_transformed:.4f} Y{start_y_transformed:.4f}  ; Move to start\n")
                f.write(f"M3 S{self.laser_s_value}  ; Laser on\n")

                # Update cumulative time
                path_time = path.length / self.feed_rate
                cumulative_time += path_time

                # Trace the path
                for x, y in coords[1:]:
                    if self.flip_horizontal:
                        x = 2 * self.flip_center_x - x
                    if self.rotate_180:
                        cx, cy = self.rotation_center_x, self.rotation_center_y
                        x_transformed = 2*cx - x + self.transform_x
                        y_transformed = 2*cy - y + self.transform_y
                    else:
                        x_transformed = x + self.transform_x
                        y_transformed = y + self.transform_y
                    f.write(f"G1 X{x_transformed:.4f} Y{y_transformed:.4f}\n")

                f.write("M5  ; Laser off\n")
                f.write("\n")
                prev_end_pos = coords[-1]

    def _write_bed_mesh_calibration(self, f: TextIO, board_outline_bounds: tuple, use_macro: bool = False,
                                    probe_to_nozzle: str = None, nozzle_to_probe: str = None):
        """Write bed mesh calibration command.

        Args:
            f: File handle
            board_outline_bounds: Board outline bounds in original coordinates
            use_macro: If True, use macro-based coordinate system (relative to pin)
            probe_to_nozzle: Macro to move probe to nozzle position
            nozzle_to_probe: Macro to move nozzle to probe position
        """
        # Calculate board dimensions
        b_min_x, b_min_y, b_max_x, b_max_y = board_outline_bounds
        board_width = b_max_x - b_min_x
        board_height = b_max_y - b_min_y

        if use_macro:
            # Macro mode: coordinates are relative to pin (origin set by G92)
            # Pin is at pin_transform origin, board outline is relative to that
            pin_x = self.pin_transform['origin_x']
            pin_y = self.pin_transform['origin_y']

            # Board bounds in pin-relative coordinates
            board_rel_min_x = b_min_x - pin_x
            board_rel_min_y = b_min_y - pin_y
            board_rel_max_x = b_max_x - pin_x
            board_rel_max_y = b_max_y - pin_y

            # Mesh bounds with offset
            mesh_min_x = board_rel_min_x + self.mesh_offset
            mesh_min_y = board_rel_min_y + self.mesh_offset
            mesh_max_x = board_rel_max_x - self.mesh_offset
            mesh_max_y = board_rel_max_y - self.mesh_offset

            # Validate mesh bounds
            if mesh_max_x <= mesh_min_x or mesh_max_y <= mesh_min_y:
                f.write("; WARNING: Mesh offset too large for board size, skipping bed mesh calibration\n")
                return

            f.write("; Bed mesh calibration (relative to pin origin)\n")
            f.write(f"{probe_to_nozzle}  ; Shift to probe for meshing\n")
            f.write(f"BED_MESH_CALIBRATE MESH_MIN={mesh_min_x:.2f},{mesh_min_y:.2f} MESH_MAX={mesh_max_x:.2f},{mesh_max_y:.2f} PROBE_COUNT={self.probe_count[0]},{self.probe_count[1]}\n")
            f.write(f"{nozzle_to_probe}  ; Shift back to nozzle\n")
            f.write("\n")
        else:
            # Standard mode: absolute coordinates
            # Calculate board position (respecting normalization and offsets)
            if self.normalize_origin:
                board_x = self.x_offset
                board_y = self.y_offset
            else:
                board_x = b_min_x + self.x_offset
                board_y = b_min_y + self.y_offset

            # Calculate mesh bounds with offset from edges (relative to board position)
            mesh_min_x = board_x + self.mesh_offset
            mesh_min_y = board_y + self.mesh_offset
            mesh_max_x = board_x + board_width - self.mesh_offset
            mesh_max_y = board_y + board_height - self.mesh_offset

            # Validate mesh bounds
            if mesh_max_x <= mesh_min_x or mesh_max_y <= mesh_min_y:
                f.write("; WARNING: Mesh offset too large for board size, skipping bed mesh calibration\n")
                return

            f.write("\n")
            f.write("; Bed mesh calibration\n")
            f.write(f"BED_MESH_CALIBRATE MESH_MIN={mesh_min_x:.2f},{mesh_min_y:.2f} MESH_MAX={mesh_max_x:.2f},{mesh_max_y:.2f} PROBE_COUNT={self.probe_count[0]},{self.probe_count[1]}\n")
            f.write("\n")

    def _write_outline(self, f: TextIO, board_outline_bounds: tuple):
        """Write board outline drawing for positioning verification.

        Args:
            f: File handle
            board_outline_bounds: Board outline bounds in original coordinates
        """
        # Calculate board dimensions
        b_min_x, b_min_y, b_max_x, b_max_y = board_outline_bounds

        f.write("\n")
        if self.outline_offset_count == 0:
            f.write("; Draw board outline (for positioning verification)\n")
        else:
            offset_dir = "outward" if self.outline_offset_count < 0 else "inward"
            f.write(f"; Draw board outline with {abs(self.outline_offset_count)} {offset_dir} offset copies\n")
        f.write(f"G1 F{self.feed_rate}  ; Set outline drawing speed\n")

        # Determine how many outlines to draw and offset direction
        num_outlines = abs(self.outline_offset_count) + 1  # +1 for the base outline
        offset_direction = -1 if self.outline_offset_count < 0 else 1  # -1 = outward, +1 = inward

        for i in range(num_outlines):
            # Calculate offset for this iteration
            # i=0 is the base outline, i>0 are offset copies
            if i == 0:
                offset_amount = 0
            else:
                offset_amount = i * self.outline_offset_spacing * offset_direction

            # Start with ORIGINAL outline coordinates and apply offset
            orig_x1 = b_min_x - offset_amount
            orig_y1 = b_min_y - offset_amount
            orig_x2 = b_max_x + offset_amount
            orig_y2 = b_max_y + offset_amount

            # Apply the SAME transformation we use for paths (flip, rotate, translate)
            # This ensures outline matches the actual board position

            # Step 1: Flip if enabled
            if self.flip_horizontal:
                orig_x1_flipped = 2 * self.flip_center_x - orig_x1
                orig_x2_flipped = 2 * self.flip_center_x - orig_x2
                # After flip, x1 and x2 swap
                orig_x1, orig_x2 = orig_x2_flipped, orig_x1_flipped

            # Step 2: Rotate if enabled
            if self.rotate_180:
                # Rotate 180° around center point, then translate
                cx, cy = self.rotation_center_x, self.rotation_center_y
                corner_x1 = 2*cx - orig_x1 + self.transform_x
                corner_y1 = 2*cy - orig_y1 + self.transform_y
                corner_x2 = 2*cx - orig_x2 + self.transform_x
                corner_y2 = 2*cy - orig_y2 + self.transform_y
                # After rotation, corners swap positions
                corner_x1, corner_x2 = corner_x2, corner_x1
                corner_y1, corner_y2 = corner_y2, corner_y1
            else:
                # Step 3: Just apply translation
                corner_x1 = orig_x1 + self.transform_x
                corner_y1 = orig_y1 + self.transform_y
                corner_x2 = orig_x2 + self.transform_x
                corner_y2 = orig_y2 + self.transform_y

            # Draw rectangle: start at corner 1, go clockwise
            if i == 0:
                f.write(f"; Base outline\n")
            else:
                f.write(f"; Offset copy {i} ({abs(offset_amount):.2f}mm {offset_dir})\n")

            f.write(f"G0 X{corner_x1:.4f} Y{corner_y1:.4f}  ; Move to corner 1\n")
            f.write(f"M3 S{self.laser_s_value}  ; Laser on\n")
            f.write(f"G1 X{corner_x2:.4f} Y{corner_y1:.4f}  ; Draw to corner 2\n")
            f.write(f"G1 X{corner_x2:.4f} Y{corner_y2:.4f}  ; Draw to corner 3\n")
            f.write(f"G1 X{corner_x1:.4f} Y{corner_y2:.4f}  ; Draw to corner 4\n")
            f.write(f"G1 X{corner_x1:.4f} Y{corner_y1:.4f}  ; Draw back to corner 1\n")
            f.write("M5  ; Laser off\n")
            f.write("\n")

        f.write("\n")

    def _calculate_time_estimate(self, paths: List[LineString]) -> float:
        """Calculate estimated time for exposure in minutes.

        Args:
            paths: List of paths to trace

        Returns:
            Estimated time in minutes
        """
        if not paths:
            return 0.0

        # Calculate exposure time (path lengths at feed rate)
        total_exposure_length = sum(path.length for path in paths)
        exposure_time_minutes = total_exposure_length / self.feed_rate

        # Estimate travel distance (between paths)
        # Approximate as distance between end of one path and start of next
        travel_distance = 0.0
        for i in range(len(paths) - 1):
            current_end = paths[i].coords[-1]
            next_start = paths[i + 1].coords[0]
            # Euclidean distance
            dx = next_start[0] - current_end[0]
            dy = next_start[1] - current_end[1]
            travel_distance += (dx**2 + dy**2) ** 0.5

        travel_time_minutes = travel_distance / self.travel_rate

        # Add overhead for laser on/off operations (assume 0.1 second per path)
        num_paths = len(paths)
        overhead_minutes = (num_paths * 0.1) / 60.0

        # Add small buffer for acceleration/deceleration (5%)
        buffer_factor = 1.05

        total_time = (exposure_time_minutes + travel_time_minutes + overhead_minutes) * buffer_factor

        return total_time

    def _write_footer(self, f: TextIO):
        """Write G-code footer with shutdown commands.

        Args:
            f: File handle
        """
        f.write("; End of exposure\n")
        f.write("M73 P100 R0  ; Progress 100% complete\n")
        f.write("M5          ; Ensure laser is off\n")

        # Disarm laser (optional)
        if self.laser_disarm_command:
            f.write(f"{self.laser_disarm_command}  ; Disarm laser (disable relay)\n")

        f.write("G0 X0 Y0    ; Return to origin\n")
        f.write("\n")

        # TODO: Custom end G-code will be inserted here

        f.write("; Program complete\n")
        f.write("M84         ; Disable motors\n")

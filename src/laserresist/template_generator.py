"""Generate drilling template STL from board geometry."""

from pathlib import Path
from typing import Dict, Optional
import subprocess
import pkg_resources


class TemplateGenerator:
    """Generate OpenSCAD drilling template for PCB pin alignment."""

    def __init__(
        self,
        board_bounds: tuple,
        pin1: Dict,
        pin2: Dict,
        block_height: float = 4.0,
        wall_thickness: float = 2.0,
        wall_extra_height: float = 1.75,
        hole_print_tolerance: float = 0.2,
        pcb_safety_offset: float = 0.0,
    ):
        """Initialize template generator for pin alignment.

        Args:
            board_bounds: Board outline bounds (min_x, min_y, max_x, max_y)
            pin1: First pin dict with x, y, diameter
            pin2: Second pin dict with x, y, diameter
            block_height: Height of the main block in mm (default: 4.0)
            wall_thickness: Thickness of the walls in mm (default: 2.0)
            wall_extra_height: Extra height for walls above block in mm (default: 1.75)
            hole_print_tolerance: Extra diameter for 3D print compensation in mm (default: 0.2)
            pcb_safety_offset: Extra margin around board in mm (default: 0.0)
                             Increases template size on all sides. Example: 1mm offset on 40x40 board = 42x42 template
        """
        self.board_bounds = board_bounds
        self.pin1 = pin1
        self.pin2 = pin2
        self.block_height = block_height
        self.wall_thickness = wall_thickness
        self.wall_extra_height = wall_extra_height
        self.hole_print_tolerance = hole_print_tolerance
        self.pcb_safety_offset = pcb_safety_offset

        # Calculate board dimensions
        min_x, min_y, max_x, max_y = board_bounds
        self.board_width = max_x - min_x
        self.board_height = max_y - min_y
        self.board_min_x = min_x
        self.board_min_y = min_y

    def get_template_path(self) -> Path:
        """Get path to the static OpenSCAD template file.

        Returns:
            Path to drilling_template.scad
        """
        # Template is in the same directory as this module
        module_dir = Path(__file__).parent
        template_path = module_dir / 'drilling_template.scad'

        if not template_path.exists():
            raise FileNotFoundError(f"Template file not found: {template_path}")

        return template_path

    def generate_stl(
        self,
        output_path: Path,
        openscad_binary: str = "openscad",
    ) -> bool:
        """Generate STL file using OpenSCAD with static template.

        Args:
            output_path: Path to output STL file
            openscad_binary: Path to openscad binary (default: "openscad")

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get path to static template
            template_path = self.get_template_path()

            # Apply safety offset to board dimensions (add offset on all sides)
            template_width = self.board_width + (2 * self.pcb_safety_offset)
            template_height = self.board_height + (2 * self.pcb_safety_offset)

            # Calculate pin positions relative to board corner (0,0) and apply safety offset
            pin1_x = self.pin1['x'] - self.board_min_x + self.pcb_safety_offset
            pin1_y = self.pin1['y'] - self.board_min_y + self.pcb_safety_offset
            pin2_x = self.pin2['x'] - self.board_min_x + self.pcb_safety_offset
            pin2_y = self.pin2['y'] - self.board_min_y + self.pcb_safety_offset

            # Build openscad command with -D parameters
            cmd = [openscad_binary]

            # Add all parameters as -D options
            params = {
                'board_width': template_width,
                'board_height': template_height,
                'block_height': self.block_height,
                'wall_thickness': self.wall_thickness,
                'wall_extra_height': self.wall_extra_height,
                'hole_print_tolerance': self.hole_print_tolerance,
                'pin1_x': pin1_x,
                'pin1_y': pin1_y,
                'pin1_diameter': self.pin1['diameter'],
                'pin2_x': pin2_x,
                'pin2_y': pin2_y,
                'pin2_diameter': self.pin2['diameter'],
            }

            for key, value in params.items():
                cmd.extend(['-D', f'{key}={value:.4f}'])

            # Add output and input files
            cmd.extend(['-o', str(output_path), str(template_path)])

            # Calculate final hole diameters
            pin1_final_diameter = self.pin1['diameter'] + self.hole_print_tolerance
            pin2_final_diameter = self.pin2['diameter'] + self.hole_print_tolerance

            # Run OpenSCAD
            print(f"\nGenerating drilling template STL...")
            print(f"  Template: {template_path.name}")
            print(f"  Board: {self.board_width:.2f} x {self.board_height:.2f} mm")
            if self.pcb_safety_offset > 0:
                print(f"  Safety offset: {self.pcb_safety_offset:.2f}mm")
                print(f"  Template size: {template_width:.2f} x {template_height:.2f} mm")
            print(f"  Print tolerance: {self.hole_print_tolerance:.2f}mm")
            print(f"  Pin 1: ({pin1_x:.2f}, {pin1_y:.2f}) Ø{self.pin1['diameter']:.2f}mm → Ø{pin1_final_diameter:.2f}mm")
            print(f"  Pin 2: ({pin2_x:.2f}, {pin2_y:.2f}) Ø{self.pin2['diameter']:.2f}mm → Ø{pin2_final_diameter:.2f}mm")
            print(f"  Output: {output_path}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                print(f"Error running OpenSCAD:")
                print(result.stderr)
                return False

            print(f"✓ STL template generated successfully")
            return True

        except FileNotFoundError as e:
            if 'drilling_template.scad' in str(e):
                print(f"Error: Template file not found: {e}")
            else:
                print(f"Error: OpenSCAD binary not found: {openscad_binary}")
                print("Please ensure OpenSCAD is installed and in your PATH")
                print("Download from: https://openscad.org/downloads.html")
            return False

        except subprocess.TimeoutExpired:
            print("Error: OpenSCAD rendering timed out (>60s)")
            return False

        except Exception as e:
            print(f"Error generating STL: {e}")
            return False

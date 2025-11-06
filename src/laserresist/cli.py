"""Command-line interface for LaserResist."""

import argparse
import json
import sys
import warnings
from pathlib import Path
from typing import Optional, Dict, Any

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

from .gerber_parser import GerberParser
from .fill_generator import FillGenerator
from .gcode_generator import GCodeGenerator


def find_gerber_files(folder: Path) -> Dict[str, Optional[Path]]:
    """Auto-detect Gerber files in a folder.

    Args:
        folder: Path to folder containing Gerber files

    Returns:
        Dictionary with keys: copper, outline, drill_pth, drill_via
    """
    files = {
        'copper': None,
        'outline': None,
        'drill_pth': None,
        'drill_via': None,
    }

    # Common patterns for each file type
    copper_patterns = ['*.gtl', '*.top', '*-F.Cu.gbr', '*F_Cu.gbr', '*.GTL']
    outline_patterns = ['*.gko', '*.gm1', '*-Edge.Cuts.gbr', '*Edge_Cuts.gbr', '*BoardOutline*.gbr', '*.GKO', '*BoardOutline*.GKO']
    drill_pth_patterns = ['*PTH*.drl', '*PTH*.DRL', '*PTH*.txt', '*-PTH*.drl', '*plated*.drl', '*Plated*.drl']
    drill_via_patterns = ['*Via*.drl', '*VIA*.drl', '*via*.drl', '*Via*.DRL', '*VIA*.DRL']

    # Search for copper layer
    for pattern in copper_patterns:
        matches = list(folder.glob(pattern))
        if matches:
            files['copper'] = matches[0]
            break

    # Search for outline
    for pattern in outline_patterns:
        matches = list(folder.glob(pattern))
        if matches:
            files['outline'] = matches[0]
            break

    # Search for drill files - filter out NPTH files
    for pattern in drill_pth_patterns:
        matches = list(folder.glob(pattern))
        # Filter out NPTH (non-plated) files
        matches = [m for m in matches if 'NPTH' not in m.name and 'npth' not in m.name.lower()]
        if matches:
            files['drill_pth'] = matches[0]
            break

    for pattern in drill_via_patterns:
        matches = list(folder.glob(pattern))
        if matches:
            files['drill_via'] = matches[0]
            break

    return files


def load_config(config_path: Path) -> Dict[str, Any]:
    """Load configuration from JSON or YAML file.

    Args:
        config_path: Path to config file

    Returns:
        Dictionary of configuration values
    """
    if not config_path.exists():
        print(f"Error: Config file '{config_path}' not found")
        sys.exit(1)

    suffix = config_path.suffix.lower()

    with open(config_path, 'r') as f:
        if suffix == '.json':
            return json.load(f)
        elif suffix in ['.yaml', '.yml']:
            if not YAML_AVAILABLE:
                print("Error: PyYAML not installed. Install with: pip install pyyaml")
                sys.exit(1)
            return yaml.safe_load(f)
        else:
            print(f"Error: Unsupported config file format '{suffix}'. Use .json or .yaml")
            sys.exit(1)


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="Generate laser exposure G-code from Gerber files for negative photoresist PCB fabrication",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process single Gerber file
  laserresist input.gtl -o output.gcode

  # Auto-detect Gerber files in folder
  laserresist gerber_folder/ -o output.gcode

  # Use config file for settings
  laserresist input.gtl --config my_settings.json

  # Specify all files manually
  laserresist input.gtl --outline board.gko --drill-pth holes.drl -o output.gcode
        """
    )

    # Input files
    parser.add_argument(
        "input",
        type=Path,
        help="Input Gerber file or folder containing Gerber files",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        help="Output G-code file (default: exposure.gcode)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Config file (JSON or YAML) with settings",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show verbose output including Gerber parser warnings",
    )

    # Gerber file options
    gerber_group = parser.add_argument_group('Gerber files')
    gerber_group.add_argument(
        "--outline",
        type=Path,
        help="Board outline Gerber file (.gko, .gm1, etc.)",
    )
    gerber_group.add_argument(
        "--drill-pth",
        type=Path,
        help="PTH drill file (.drl)",
    )
    gerber_group.add_argument(
        "--drill-via",
        type=Path,
        help="Via drill file (.drl)",
    )

    # Fill generation options
    fill_group = parser.add_argument_group('Fill generation')
    fill_group.add_argument(
        "--line-spacing",
        type=float,
        help="Spacing between fill lines in mm (default: 0.1)",
    )
    fill_group.add_argument(
        "--offset-centerlines",
        action="store_true",
        help="Offset trace centerlines from ends (default: False)",
    )

    # G-code generation options
    gcode_group = parser.add_argument_group('G-code generation')
    gcode_group.add_argument(
        "--laser-power",
        type=float,
        help="Laser power percentage 0-100 (default: 2)",
    )
    gcode_group.add_argument(
        "--feed-rate",
        type=float,
        help="Feed rate in mm/min (default: 1400)",
    )
    gcode_group.add_argument(
        "--travel-rate",
        type=float,
        help="Travel rate in mm/min (default: 6000)",
    )
    gcode_group.add_argument(
        "--z-height",
        type=float,
        help="Z height for laser focus in mm (default: 20)",
    )
    gcode_group.add_argument(
        "--x-offset",
        type=float,
        help="X offset in mm (default: 0)",
    )
    gcode_group.add_argument(
        "--y-offset",
        type=float,
        help="Y offset in mm (default: 0)",
    )
    gcode_group.add_argument(
        "--no-normalize",
        action="store_true",
        help="Don't normalize coordinates to origin (default: normalize)",
    )

    # Bed mesh calibration
    mesh_group = parser.add_argument_group('Bed mesh calibration')
    mesh_group.add_argument(
        "--bed-mesh",
        action="store_true",
        help="Enable bed mesh calibration (default: False)",
    )
    mesh_group.add_argument(
        "--mesh-offset",
        type=float,
        help="Mesh offset from board edges in mm (default: 3)",
    )
    mesh_group.add_argument(
        "--probe-count",
        type=str,
        help="Probe count as 'X,Y' (default: '3,3')",
    )

    # Laser control
    laser_group = parser.add_argument_group('Laser control')
    laser_group.add_argument(
        "--laser-arm-command",
        type=str,
        help="Command to arm laser (e.g., 'ARM_LASER')",
    )
    laser_group.add_argument(
        "--laser-disarm-command",
        type=str,
        help="Command to disarm laser (e.g., 'DISARM_LASER')",
    )
    laser_group.add_argument(
        "--draw-outline",
        action="store_true",
        help="Draw board outline before exposure (for positioning verification)",
    )

    args = parser.parse_args()

    # Suppress warnings by default unless verbose is enabled
    if not args.verbose:
        warnings.filterwarnings('ignore')

    # Load config file if specified
    config = {}
    if args.config:
        config = load_config(args.config)
        print(f"Loaded config from: {args.config}")

    # Helper to get value: CLI arg > config > default
    def get_value(arg_name: str, config_key: str = None, default: Any = None) -> Any:
        if config_key is None:
            config_key = arg_name
        arg_val = getattr(args, arg_name, None)
        # Special handling for boolean flags
        if isinstance(arg_val, bool):
            # If it's a boolean action flag that's False, check config
            if not arg_val and config_key in config:
                return config.get(config_key, default)
            return arg_val
        if arg_val is not None:
            return arg_val
        return config.get(config_key, default)

    # Process input path
    input_path = args.input
    if not input_path.exists():
        print(f"Error: Input path '{input_path}' not found")
        return 1

    # Determine Gerber files
    if input_path.is_dir():
        print(f"Auto-detecting Gerber files in: {input_path}")
        detected = find_gerber_files(input_path)

        copper_file = detected['copper']
        outline_file = get_value('outline') or detected['outline']
        drill_pth_file = get_value('drill_pth') or detected['drill_pth']
        drill_via_file = get_value('drill_via') or detected['drill_via']

        if not copper_file:
            print("Error: Could not find copper layer file (.gtl, .top, etc.)")
            return 1

        print(f"  Copper: {copper_file.name}")
        if outline_file:
            print(f"  Outline: {outline_file.name}")
        if drill_pth_file:
            print(f"  Drill PTH: {drill_pth_file.name}")
        if drill_via_file:
            print(f"  Drill Via: {drill_via_file.name}")
    else:
        copper_file = input_path
        outline_file = get_value('outline')
        drill_pth_file = get_value('drill_pth')
        drill_via_file = get_value('drill_via')

        print(f"Copper file: {copper_file}")

    # Set output file
    output_file = args.output if args.output else Path("exposure.gcode")
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Get all settings
    line_spacing = get_value('line_spacing', default=0.1)
    offset_centerlines = get_value('offset_centerlines', default=False)

    laser_power = get_value('laser_power', default=2.0)
    feed_rate = get_value('feed_rate', default=1400.0)
    travel_rate = get_value('travel_rate', default=6000.0)
    z_height = get_value('z_height', default=20.0)
    x_offset = get_value('x_offset', default=0.0)
    y_offset = get_value('y_offset', default=0.0)
    normalize_origin = not args.no_normalize

    bed_mesh = get_value('bed_mesh', default=False)
    mesh_offset = get_value('mesh_offset', default=3.0)
    probe_count_str = get_value('probe_count', default='3,3')
    probe_count = tuple(map(int, probe_count_str.split(',')))

    laser_arm_command = get_value('laser_arm_command')
    laser_disarm_command = get_value('laser_disarm_command')
    draw_outline = get_value('draw_outline', default=False)

    # Print settings summary
    print(f"\nSettings:")
    print(f"  Line spacing: {line_spacing} mm")
    print(f"  Laser power: {laser_power}%")
    print(f"  Feed rate: {feed_rate} mm/min")
    print(f"  Z height: {z_height} mm")
    if bed_mesh:
        print(f"  Bed mesh: enabled (offset={mesh_offset}mm, probe={probe_count[0]}x{probe_count[1]})")

    # Parse Gerber files
    print(f"\nParsing Gerber files...")
    parser_obj = GerberParser(copper_file, drill_pth_file, drill_via_file)
    geometry = parser_obj.parse()
    bounds = parser_obj.get_bounds()
    trace_centerlines = parser_obj.get_trace_centerlines()

    # Parse board outline if available
    board_outline_bounds = None
    if outline_file and outline_file.exists():
        board_outline_bounds = GerberParser.parse_board_outline(outline_file)
        print(f"  Board outline: {board_outline_bounds[2]-board_outline_bounds[0]:.2f} x {board_outline_bounds[3]-board_outline_bounds[1]:.2f} mm")

    # Generate fill
    print(f"\nGenerating fill paths...")
    fill_gen = FillGenerator(line_spacing=line_spacing)
    paths = fill_gen.generate_fill(geometry, trace_centerlines=trace_centerlines, offset_centerlines=offset_centerlines)

    total_length = sum(path.length for path in paths)
    print(f"  Generated {len(paths)} paths")
    print(f"  Total length: {total_length:.2f} mm")

    # Generate G-code
    print(f"\nGenerating G-code...")
    gcode_gen = GCodeGenerator(
        laser_power=laser_power,
        feed_rate=feed_rate,
        travel_rate=travel_rate,
        z_height=z_height,
        x_offset=x_offset,
        y_offset=y_offset,
        normalize_origin=normalize_origin,
        bed_mesh_calibrate=bed_mesh,
        mesh_offset=mesh_offset,
        probe_count=probe_count,
        laser_arm_command=laser_arm_command,
        laser_disarm_command=laser_disarm_command,
        draw_outline=draw_outline,
    )

    with open(output_file, 'w') as f:
        gcode_gen.generate(paths, f, bounds, board_outline_bounds)

    print(f"\n✓ G-code saved to: {output_file}")

    return 0


if __name__ == "__main__":
    exit(main())

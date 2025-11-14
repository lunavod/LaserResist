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
from .pin_alignment import PinAlignmentUI, get_pin_alignment_transform
from .template_generator import TemplateGenerator
from .bloom_compensator import FastBloomSimulator, identify_underexposed_traces, generate_compensation_paths, generate_debug_visualization


def find_gerber_files(folder: Path, side: str = 'front') -> Dict[str, Optional[Path]]:
    """Auto-detect Gerber files in a folder.

    Args:
        folder: Path to folder containing Gerber files
        side: Which copper layer to use ('front', 'back', 'top', 'bottom')

    Returns:
        Dictionary with keys: copper, outline, drill_pth, drill_via
    """
    files = {
        'copper': None,
        'outline': None,
        'drill_pth': None,
        'drill_via': None,
        'drill_npth': None,
    }

    # Normalize side parameter
    side = side.lower()
    if side in ['front', 'top']:
        side = 'front'
    elif side in ['back', 'bottom']:
        side = 'back'
    else:
        raise ValueError(f"Invalid side '{side}'. Must be 'front', 'back', 'top', or 'bottom'")

    # Common patterns for each file type
    if side == 'front':
        copper_patterns = ['*.gtl', '*.top', '*-F.Cu.gbr', '*F_Cu.gbr', '*.GTL']
    else:  # back
        copper_patterns = ['*.gbl', '*.bottom', '*-B.Cu.gbr', '*B_Cu.gbr', '*.GBL']

    outline_patterns = ['*.gko', '*.gm1', '*-Edge.Cuts.gbr', '*Edge_Cuts.gbr', '*BoardOutline*.gbr', '*.GKO', '*BoardOutline*.GKO']
    drill_pth_patterns = ['*PTH*.drl', '*PTH*.DRL', '*PTH*.txt', '*-PTH*.drl', '*plated*.drl', '*Plated*.drl']
    drill_via_patterns = ['*Via*.drl', '*VIA*.drl', '*via*.drl', '*Via*.DRL', '*VIA*.DRL']
    drill_npth_patterns = ['*NPTH*.drl', '*NPTH*.DRL', '*npth*.drl', '*-NPTH*.drl']

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

    for pattern in drill_npth_patterns:
        matches = list(folder.glob(pattern))
        if matches:
            files['drill_npth'] = matches[0]
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
            config = json.load(f)
        elif suffix in ['.yaml', '.yml']:
            if not YAML_AVAILABLE:
                print("Error: PyYAML not installed. Install with: pip install pyyaml")
                sys.exit(1)
            config = yaml.safe_load(f)
        else:
            print(f"Error: Unsupported config file format '{suffix}'. Use .json or .yaml")
            sys.exit(1)

    # Validate config keys
    known_keys = {
        # Fill generation
        'line_spacing', 'initial_offset', 'forced_pad_centerlines', 'offset_centerlines', 'force_trace_centerlines', 'force_trace_centerlines_max_thickness', 'double_expose_isolated', 'isolation_threshold', 'bloom_compensation', 'bloom_resolution', 'bloom_spot_sigma', 'bloom_scatter_sigma', 'bloom_scatter_fraction', 'bloom_threshold_percentile', 'bloom_debug_image',
        # Laser settings
        'laser_power', 'feed_rate', 'travel_rate', 'z_height',
        # Coordinate transformation
        'x_offset', 'y_offset', 'no_normalize', 'flip_horizontal',
        # Bed mesh
        'bed_mesh', 'mesh_offset', 'probe_count',
        # Laser control
        'laser_arm_command', 'laser_disarm_command',
        # Outline
        'draw_outline', 'outline_offset_count',
        # Pin mode
        'pin_mode', 'pin_macro',
        # Template generation
        'generate_template_stl', 'stl_name', 'template_block_height',
        'template_wall_thickness', 'hole_print_tolerance', 'pcb_safety_offset',
        # Gerber file selection
        'side',
    }

    unknown_keys = set(config.keys()) - known_keys
    if unknown_keys:
        print(f"\nWarning: Unknown configuration keys in {config_path.name}:")
        for key in sorted(unknown_keys):
            print(f"  - {key}")
        print("These keys will be ignored. Check for typos or see config_example.yaml for valid keys.\n")

    return config


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
        "--side",
        type=str,
        choices=['front', 'back', 'top', 'bottom'],
        help="PCB side/layer for folder auto-detection: front/top (default) or back/bottom",
    )
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
    gerber_group.add_argument(
        "--drill-npth",
        type=Path,
        help="NPTH (non-plated through hole) drill file (.drl)",
    )

    # Fill generation options
    fill_group = parser.add_argument_group('Fill generation')
    fill_group.add_argument(
        "--line-spacing",
        type=float,
        help="Spacing between fill lines in mm (default: 0.1)",
    )
    fill_group.add_argument(
        "--initial-offset",
        type=float,
        help="Initial inward offset of outer boundaries to compensate for laser dot size in mm (default: 0.05)",
    )
    fill_group.add_argument(
        "--forced-pad-centerlines",
        action="store_true",
        help="Add centerlines to all pads: + for rectangular, circles for round (default: False)",
    )
    fill_group.add_argument(
        "--offset-centerlines",
        action="store_true",
        help="Offset trace centerlines from ends (default: False)",
    )
    fill_group.add_argument(
        "--force-trace-centerlines",
        action="store_true",
        help="Force all trace centerlines without clipping to avoid filled zones (default: False)",
    )
    fill_group.add_argument(
        "--bloom-compensation",
        action="store_true",
        help="Enable bloom compensation for isolated traces (default: False)",
    )
    fill_group.add_argument(
        "--bloom-resolution",
        type=float,
        help="Bloom simulation grid resolution in mm (default: 0.05)",
    )
    fill_group.add_argument(
        "--bloom-scatter-sigma",
        type=float,
        help="Bloom scatter Gaussian sigma in mm (default: 2.0)",
    )
    fill_group.add_argument(
        "--bloom-scatter-fraction",
        type=float,
        help="Fraction of energy in bloom scatter vs tight spot (default: 0.35)",
    )
    fill_group.add_argument(
        "--bloom-threshold-percentile",
        type=float,
        help="Percentile threshold for under-exposure detection (default: 30)",
    )
    fill_group.add_argument(
        "--bloom-debug-image",
        action="store_true",
        help="Generate bloom visualization image alongside G-code (default: False)",
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
    gcode_group.add_argument(
        "--flip-horizontal",
        action="store_true",
        help="Flip board horizontally (mirror X axis) - typically used for bottom layer",
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
    laser_group.add_argument(
        "--outline-offset-count",
        type=int,
        help="Number of offset outline copies: 0=single, -1=one outward, +1=one inward, etc. (default: 0)",
    )

    # Pin alignment mode
    pin_group = parser.add_argument_group('Pin alignment')
    pin_group.add_argument(
        "--pin-mode",
        action="store_true",
        help="Enable interactive pin alignment mode for physical alignment pins",
    )
    pin_group.add_argument(
        "--pin-macro",
        action="store_true",
        help="Use SETUP_PCB_SPACE macro for alignment (requires macro installed on printer)",
    )

    # Template generation
    template_group = parser.add_argument_group('Drilling template')
    template_group.add_argument(
        "--generate-template-stl",
        action="store_true",
        help="Generate drilling template STL file using OpenSCAD",
    )
    template_group.add_argument(
        "--stl-name",
        type=Path,
        help="Output STL filename (default: same as gcode with .stl extension)",
    )
    template_group.add_argument(
        "--template-block-height",
        type=float,
        help="Height of template block in mm (default: 4.0)",
    )
    template_group.add_argument(
        "--template-wall-thickness",
        type=float,
        help="Thickness of template walls in mm (default: 2.0)",
    )
    template_group.add_argument(
        "--hole-print-tolerance",
        type=float,
        help="Extra diameter added to holes for 3D print compensation in mm (default: 0.2)",
    )
    template_group.add_argument(
        "--pcb-safety-offset",
        type=float,
        help="Extra margin around board in mm to make template bigger (default: 0)",
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
        side = get_value('side', default='front')
        side_display = side.capitalize()
        print(f"Auto-detecting Gerber files in: {input_path} (side: {side_display})")
        detected = find_gerber_files(input_path, side=side)

        copper_file = detected['copper']
        outline_file = get_value('outline') or detected['outline']
        drill_pth_file = get_value('drill_pth') or detected['drill_pth']
        drill_via_file = get_value('drill_via') or detected['drill_via']
        drill_npth_file = get_value('drill_npth') or detected['drill_npth']

        if not copper_file:
            layer_type = "top" if side in ['front', 'top'] else "bottom"
            print(f"Error: Could not find {side} copper layer file (.gtl/.gbl, .{layer_type}, etc.)")
            return 1

        print(f"  Copper ({side_display}): {copper_file.name}")
        if outline_file:
            print(f"  Outline: {outline_file.name}")
        if drill_pth_file:
            print(f"  Drill PTH: {drill_pth_file.name}")
        if drill_via_file:
            print(f"  Drill Via: {drill_via_file.name}")
        if drill_npth_file:
            print(f"  Drill NPTH: {drill_npth_file.name}")
    else:
        copper_file = input_path
        outline_file = get_value('outline')
        drill_pth_file = get_value('drill_pth')
        drill_via_file = get_value('drill_via')
        drill_npth_file = get_value('drill_npth')

        print(f"Copper file: {copper_file}")

    # Set output file
    output_file = args.output if args.output else Path("exposure.gcode")
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Get all settings
    line_spacing = get_value('line_spacing', default=0.1)
    initial_offset = get_value('initial_offset', default=0.05)
    forced_pad_centerlines = get_value('forced_pad_centerlines', default=False)
    offset_centerlines = get_value('offset_centerlines', default=False)
    force_trace_centerlines = get_value('force_trace_centerlines', default=False)
    force_trace_centerlines_max_thickness = get_value('force_trace_centerlines_max_thickness', default=0.0)
    double_expose_isolated = get_value('double_expose_isolated', default=False)
    isolation_threshold = get_value('isolation_threshold', default=3.0)

    bloom_compensation = get_value('bloom_compensation', default=False)
    bloom_resolution = get_value('bloom_resolution', default=0.05)
    bloom_spot_sigma = get_value('bloom_spot_sigma', default=0.05)
    bloom_scatter_sigma = get_value('bloom_scatter_sigma', default=2.0)
    bloom_scatter_fraction = get_value('bloom_scatter_fraction', default=0.35)
    bloom_threshold_percentile = get_value('bloom_threshold_percentile', default=30)
    bloom_debug_image = get_value('bloom_debug_image', default=False)

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
    outline_offset_count = get_value('outline_offset_count', default=0)

    pin_mode = get_value('pin_mode', default=False)
    pin_macro = get_value('pin_macro', default=False)
    flip_horizontal = get_value('flip_horizontal', default=False)

    # Validate macro configuration
    if pin_macro and not pin_mode:
        print("Warning: --pin-macro specified but --pin-mode not enabled. Ignoring macro.")
        pin_macro = False

    # Disable negative outline offsets in pin mode (they don't make sense with precise alignment)
    if pin_mode and outline_offset_count < 0:
        print("\nWarning: Negative outline offsets disabled in pin mode (incompatible with precise alignment)")
        outline_offset_count = 0

    # Print settings summary
    print(f"\nSettings:")
    print(f"  Line spacing: {line_spacing} mm")
    print(f"  Initial offset: {initial_offset} mm")
    print(f"  Laser power: {laser_power}%")
    print(f"  Feed rate: {feed_rate} mm/min")
    print(f"  Z height: {z_height} mm")
    if bed_mesh:
        print(f"  Bed mesh: enabled (offset={mesh_offset}mm, probe={probe_count[0]}x{probe_count[1]})")
    if bloom_compensation:
        print(f"  Bloom compensation: enabled (scatter={bloom_scatter_sigma}mm, threshold={bloom_threshold_percentile}%)")

    # Parse Gerber files
    print(f"\nParsing Gerber files...")
    parser_obj = GerberParser(copper_file, drill_pth_file, drill_via_file, drill_npth_file)
    geometry = parser_obj.parse()
    bounds = parser_obj.get_bounds()
    trace_centerlines = parser_obj.get_trace_centerlines()

    # Parse board outline if available
    board_outline_bounds = None
    if outline_file and outline_file.exists():
        board_outline_bounds = GerberParser.parse_board_outline(outline_file)
        print(f"  Board outline: {board_outline_bounds[2]-board_outline_bounds[0]:.2f} x {board_outline_bounds[3]-board_outline_bounds[1]:.2f} mm")

    # Handle pin alignment mode
    pin_transform = None
    if pin_mode:
        print("\n" + "="*60)
        print("PIN ALIGNMENT MODE")
        print("="*60)

        # Get drill holes
        pth_holes = parser_obj.get_drill_holes_pth()
        npth_holes = parser_obj.get_drill_holes_npth()

        if not pth_holes and not npth_holes:
            print("Error: No drill holes found for pin alignment.")
            print("Pin alignment requires PTH or NPTH drill files.")
            return 1

        print(f"Found {len(pth_holes)} PTH holes and {len(npth_holes)} NPTH holes")

        # Use board outline bounds if available (drill holes are positioned relative to board)
        # Otherwise expand copper bounds to include all holes
        if board_outline_bounds:
            display_bounds = board_outline_bounds
            print(f"Using board outline bounds for pin alignment display")
        else:
            # Expand bounds to include all drill holes for visualization
            # This ensures holes outside copper area are visible (e.g., bottom layer NPTH holes)
            min_x, min_y, max_x, max_y = bounds
            all_holes = pth_holes + npth_holes
            if all_holes:
                hole_xs = [h['x'] for h in all_holes]
                hole_ys = [h['y'] for h in all_holes]
                min_x = min(min_x, min(hole_xs))
                min_y = min(min_y, min(hole_ys))
                max_x = max(max_x, max(hole_xs))
                max_y = max(max_y, max(hole_ys))
                display_bounds = (min_x, min_y, max_x, max_y)
            else:
                display_bounds = bounds
            print(f"No board outline - using expanded copper bounds for pin alignment display")

        # Show interactive UI (always need 2 pins for rotation detection)
        ui = PinAlignmentUI()
        selected = ui.show_board(geometry, display_bounds, pth_holes, npth_holes, trace_centerlines)

        if selected is None:
            print("\nPin alignment cancelled. Exiting.")
            return 0

        # Both modes need 2 pins for rotation detection
        pin1, pin2 = selected
        print(f"\n✓ Pin alignment configured:")
        print(f"  Pin 1 (bottom): ({pin1['x']:.2f}, {pin1['y']:.2f}) Ø{pin1['diameter']:.2f}mm")
        print(f"  Pin 2 (top):    ({pin2['x']:.2f}, {pin2['y']:.2f}) Ø{pin2['diameter']:.2f}mm")

        # Calculate rotation based on pin positions
        base_transform = get_pin_alignment_transform(pin1, pin2)

        if pin_macro:
            # Macro mode - printer handles physical positioning, we just need rotation info
            print(f"  Mode: Printer macros for physical alignment")
            print(f"  Macro: {pin_macro}")
            if base_transform['rotate_180']:
                print(f"  Board orientation: Upside down (180° rotation needed)")
            else:
                print(f"  Board orientation: Normal")

            # Create transform with macro info
            pin_transform = {
                'origin_x': pin1['x'],
                'origin_y': pin1['y'],
                'translate_x': -pin1['x'],
                'translate_y': -pin1['y'],
                'rotate_180': base_transform['rotate_180'],  # Preserve rotation detection
                'rotation_center_x': pin1['x'],
                'rotation_center_y': pin1['y'],
                'use_macro': True,
            }
        else:
            # Standard mode - software-based transformation
            pin_transform = base_transform
            pin_transform['use_macro'] = False
            if pin_transform['rotate_180']:
                print(f"  Transformation: Rotate 180° + translate to origin at pin 1")
            else:
                print(f"  Transformation: Translate to origin at pin 1")

    # Generate fill
    print(f"\nGenerating fill paths...")
    pads = parser_obj.get_pads()
    drill_holes = parser_obj.get_drill_holes()
    fill_gen = FillGenerator(line_spacing=line_spacing, initial_offset=initial_offset, forced_pad_centerlines=forced_pad_centerlines, force_trace_centerlines=force_trace_centerlines, force_trace_centerlines_max_thickness=force_trace_centerlines_max_thickness, double_expose_isolated=double_expose_isolated, isolation_threshold=isolation_threshold)
    result = fill_gen.generate_fill(geometry, trace_centerlines=trace_centerlines, offset_centerlines=offset_centerlines, pads=pads, drill_holes=drill_holes)

    # Handle both list and dict return types
    if isinstance(result, dict):
        paths = result['normal']
        isolated_paths = result['isolated']
    else:
        paths = result
        isolated_paths = []

    # Bloom compensation
    bloom_compensation_paths = []
    if bloom_compensation:
        print(f"\nRunning bloom compensation analysis...")

        # Create simulator
        simulator = FastBloomSimulator(
            resolution=bloom_resolution,
            laser_spot_sigma=bloom_spot_sigma,
            bloom_scatter_sigma=bloom_scatter_sigma,
            scatter_fraction=bloom_scatter_fraction
        )

        # Create grid and simulate
        simulator.create_grid(geometry.bounds)
        simulator.simulate(paths, sample_distance=0.05, min_samples=10)

        # Identify under-exposed traces
        normal_traces, underexposed_traces = identify_underexposed_traces(
            simulator,
            trace_centerlines,
            threshold_percentile=bloom_threshold_percentile,
            min_trace_length=0.2,
            verbose=args.verbose
        )

        # Generate compensation paths
        if underexposed_traces:
            print(f"  Identified {len(underexposed_traces)} under-exposed traces")
            bloom_compensation_paths = generate_compensation_paths(
                underexposed_traces,
                fill_gen
            )
            print(f"  Generated {len(bloom_compensation_paths)} compensation paths")

            # Generate debug visualization if requested
            if bloom_debug_image:
                debug_image_path = output_file.with_suffix('.bloom.png')
                generate_debug_visualization(
                    simulator, geometry, normal_traces, underexposed_traces,
                    bloom_compensation_paths, debug_image_path,
                    verbose=args.verbose
                )

    total_length = sum(path.length for path in paths)
    isolated_length = sum(path.length for path in isolated_paths)
    bloom_length = sum(path.length for path in bloom_compensation_paths)

    print(f"  Generated {len(paths)} normal paths", end='')
    if isolated_paths:
        print(f", {len(isolated_paths)} isolated paths", end='')
    if bloom_compensation_paths:
        print(f", {len(bloom_compensation_paths)} bloom compensation paths", end='')
    print()

    if isolated_paths or bloom_compensation_paths:
        print(f"  Total length: {total_length:.2f}mm normal", end='')
        if isolated_paths:
            print(f" + {isolated_length:.2f}mm isolated (2x)", end='')
        if bloom_compensation_paths:
            print(f" + {bloom_length:.2f}mm bloom comp (2x)", end='')
        print()
    else:
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
        flip_horizontal=flip_horizontal,
        bed_mesh_calibrate=bed_mesh,
        mesh_offset=mesh_offset,
        probe_count=probe_count,
        laser_arm_command=laser_arm_command,
        laser_disarm_command=laser_disarm_command,
        draw_outline=draw_outline,
        outline_offset_count=outline_offset_count,
        outline_offset_spacing=line_spacing,
        pin_transform=pin_transform,
    )

    # Combine isolated paths and bloom compensation paths
    double_expose_paths = isolated_paths if isolated_paths else []
    if bloom_compensation_paths:
        double_expose_paths.extend(bloom_compensation_paths)

    with open(output_file, 'w') as f:
        gcode_gen.generate(paths, f, bounds, board_outline_bounds,
                         isolated_paths=double_expose_paths if double_expose_paths else None)

    # Format and display time estimate
    time_minutes = gcode_gen.time_estimate_minutes
    hours = int(time_minutes // 60)
    minutes = int(time_minutes % 60)
    seconds = int((time_minutes % 1) * 60)

    if hours > 0:
        time_str = f"{hours}h {minutes}m {seconds}s"
    elif minutes > 0:
        time_str = f"{minutes}m {seconds}s"
    else:
        time_str = f"{seconds}s"

    print(f"\n✓ G-code saved to: {output_file}")
    print(f"  Estimated exposure time: {time_str}")

    # Generate drilling template STL if requested
    generate_template_stl = get_value('generate_template_stl', default=False)
    if generate_template_stl:
        # Template requires pin mode to be enabled
        if not pin_mode or not pin_transform:
            print("\nWarning: Drilling template requires --pin-mode")
            print("The template needs two pin holes for alignment.")
        else:
            # Determine output STL filename
            stl_name = get_value('stl_name')
            if not stl_name:
                # Use same base name as gcode file
                stl_name = output_file.with_suffix('.stl')

            # Get template parameters
            block_height = get_value('template_block_height', default=4.0)
            wall_thickness = get_value('template_wall_thickness', default=2.0)
            hole_print_tolerance = get_value('hole_print_tolerance', default=0.2)
            pcb_safety_offset = get_value('pcb_safety_offset', default=0.0)

            # Use board outline bounds if available, otherwise copper bounds
            template_bounds = board_outline_bounds if board_outline_bounds else bounds

            # Create template generator with selected pins
            template_gen = TemplateGenerator(
                board_bounds=template_bounds,
                pin1=pin1,
                pin2=pin2,
                block_height=block_height,
                wall_thickness=wall_thickness,
                hole_print_tolerance=hole_print_tolerance,
                pcb_safety_offset=pcb_safety_offset,
            )

            # Generate STL
            success = template_gen.generate_stl(stl_name)
            if success:
                print(f"✓ Drilling template STL saved to: {stl_name}")

    return 0


if __name__ == "__main__":
    exit(main())

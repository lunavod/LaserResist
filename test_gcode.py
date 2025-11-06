"""Test script for G-code generation."""

from pathlib import Path
from src.laserresist.gerber_parser import GerberParser
from src.laserresist.fill_generator import FillGenerator
from src.laserresist.gcode_generator import GCodeGenerator


def main():
    """Test the G-code generator."""
    gerber_file = Path("examples/test.gtl")
    drill_pth_file = Path("examples/Drill_PTH_Through.DRL")
    drill_via_file = Path("examples/Drill_PTH_Through_Via.DRL")
    board_outline_file = Path("examples/Gerber_BoardOutlineLayer.GKO")

    print(f"Loading Gerber file: {gerber_file}")
    parser = GerberParser(gerber_file, drill_pth_file, drill_via_file)

    print("Parsing geometry...")
    geometry = parser.parse()
    bounds = parser.get_bounds()
    trace_centerlines = parser.get_trace_centerlines()

    # Parse board outline
    print(f"Parsing board outline: {board_outline_file}")
    board_outline_bounds = GerberParser.parse_board_outline(board_outline_file)
    print(f"  Board outline: ({board_outline_bounds[0]:.2f}, {board_outline_bounds[1]:.2f}) to ({board_outline_bounds[2]:.2f}, {board_outline_bounds[3]:.2f}) mm")

    print(f"Parsed geometry:")
    if hasattr(geometry, 'geoms'):
        print(f"  Number of polygons: {len(geometry.geoms)}")
        total_area = sum(poly.area for poly in geometry.geoms)
        print(f"  Total area: {total_area:.2f} mm²")
    else:
        print(f"  Single polygon area: {geometry.area:.2f} mm²")

    # Generate fill paths
    print("\nGenerating fill paths...")
    fill_gen = FillGenerator(line_spacing=0.1)
    paths = fill_gen.generate_fill(geometry, trace_centerlines=trace_centerlines)

    print(f"Generated {len(paths)} fill paths")
    total_length = sum(path.length for path in paths)
    print(f"Total path length: {total_length:.2f} mm")

    # Generate G-code
    print("\nGenerating G-code...")
    output_file = Path("output/exposure.gcode")
    output_file.parent.mkdir(exist_ok=True)

    gcode_gen = GCodeGenerator(
        laser_power=6.0,                    # 6% power
        feed_rate=1400.0,                   # 1400 mm/min
        travel_rate=6000.0,                 # 6000 mm/min for rapids
        z_height=20.0,                      # 20mm focus height
        bed_mesh_calibrate=True,            # Enable bed mesh calibration
        mesh_offset=3.0,                    # 3mm offset from board edges
        probe_count=(3, 3),                 # 3x3 probe grid
        laser_arm_command="ARM_LASER",      # Arm laser before exposure
        laser_disarm_command="DISARM_LASER" # Disarm laser after exposure
    )

    with open(output_file, 'w') as f:
        gcode_gen.generate(paths, f, bounds, board_outline_bounds)

    print(f"G-code saved to: {output_file}")

    # Show first and last few lines
    with open(output_file, 'r') as f:
        lines = f.readlines()

    print(f"\nGenerated {len(lines)} lines of G-code")
    print("\nFirst 20 lines:")
    print("=" * 60)
    for line in lines[:20]:
        print(line.rstrip())

    print("\n...")
    print("\nLast 10 lines:")
    print("=" * 60)
    for line in lines[-10:]:
        print(line.rstrip())


if __name__ == "__main__":
    main()

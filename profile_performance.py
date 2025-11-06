"""Quick performance profiling script."""

import time
from pathlib import Path
from src.laserresist.gerber_parser import GerberParser
from src.laserresist.fill_generator import FillGenerator
from src.laserresist.gcode_generator import GCodeGenerator


def profile_step(name, func):
    """Time a function execution."""
    start = time.time()
    result = func()
    elapsed = time.time() - start
    print(f"{name}: {elapsed:.2f}s")
    return result


def main():
    gerber_file = Path("examples/test.gtl")
    drill_pth_file = Path("examples/Drill_PTH_Through.DRL")
    drill_via_file = Path("examples/Drill_PTH_Through_Via.DRL")
    board_outline_file = Path("examples/Gerber_BoardOutlineLayer.GKO")

    print("Profiling LaserResist performance...\n")

    # Parse Gerber
    parser = GerberParser(gerber_file, drill_pth_file, drill_via_file)
    geometry = profile_step("1. Parse Gerber", lambda: parser.parse())
    bounds = parser.get_bounds()
    trace_centerlines = parser.get_trace_centerlines()
    board_outline_bounds = profile_step("2. Parse outline", lambda: GerberParser.parse_board_outline(board_outline_file))

    # Generate fill
    fill_gen = FillGenerator(line_spacing=0.1)
    paths = profile_step("3. Generate fill", lambda: fill_gen.generate_fill(geometry, trace_centerlines=trace_centerlines))

    # Generate G-code
    def gen_gcode():
        gcode_gen = GCodeGenerator(laser_power=6.0, feed_rate=1400.0)
        output = Path("output/profile_test.gcode")
        with open(output, 'w') as f:
            gcode_gen.generate(paths, f, bounds, board_outline_bounds)

    profile_step("4. Generate G-code", gen_gcode)

    print(f"\nTotal paths: {len(paths)}")
    print(f"Total length: {sum(p.length for p in paths):.2f} mm")


if __name__ == "__main__":
    main()

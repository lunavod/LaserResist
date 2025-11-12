"""Quick test of pin alignment matplotlib UI."""

from pathlib import Path
from src.laserresist.gerber_parser import GerberParser
from src.laserresist.pin_alignment import PinAlignmentUI

# Parse example files
examples_dir = Path("examples")
copper_file = examples_dir / "test.gtl"
drill_pth = examples_dir / "Drill_PTH_Through.DRL"
drill_npth = examples_dir / "Drill_NPTH_Through.DRL"

print("Parsing Gerber files...")
parser = GerberParser(copper_file, drill_pth, None, drill_npth)
geometry = parser.parse()
bounds = parser.get_bounds()
trace_centerlines = parser.get_trace_centerlines()

pth_holes = parser.get_drill_holes_pth()
npth_holes = parser.get_drill_holes_npth()

print(f"Found {len(pth_holes)} PTH holes and {len(npth_holes)} NPTH holes")
print(f"Bounds: {bounds}")

# Show UI
ui = PinAlignmentUI()
selected = ui.show_board(geometry, bounds, pth_holes, npth_holes, trace_centerlines)

if selected:
    pin1, pin2 = selected
    print(f"\n✓ Pins selected:")
    print(f"  Pin 1: ({pin1['x']:.2f}, {pin1['y']:.2f}) Ø{pin1['diameter']:.2f}mm - {pin1['type']}")
    print(f"  Pin 2: ({pin2['x']:.2f}, {pin2['y']:.2f}) Ø{pin2['diameter']:.2f}mm - {pin2['type']}")
else:
    print("\n✗ Selection cancelled")

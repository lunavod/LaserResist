"""Debug script to verify junction fills are in final paths."""

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from laserresist.gerber_parser import GerberParser
from laserresist.fill_generator import FillGenerator

# Parse the Gerber file
gerber_path = Path(r"C:\Users\yegor\Downloads\Gerber_PCB1_1_2025-11-13\Gerber_TopLayer.GTL")
drill_path = Path(r"C:\Users\yegor\Downloads\Gerber_PCB1_1_2025-11-13\Drill_PTH_Through.DRL")

print(f"Parsing {gerber_path.name}...")
parser = GerberParser(gerber_path, drill_path)
geometry = parser.parse()
trace_centerlines = parser.get_trace_centerlines()
pads = parser.get_pads()
drill_holes = parser.get_drill_holes()

print(f"\nGenerating fill paths...")
fill_gen = FillGenerator(line_spacing=0.1, initial_offset=0.05)

# Store junction fills separately first
from shapely.geometry import Polygon, MultiPolygon
geom_multi = MultiPolygon([geometry]) if isinstance(geometry, Polygon) else geometry
junction_fills = fill_gen._detect_and_fill_junction_polygons(geom_multi)
print(f"Junction fills detected: {len(junction_fills)}")

# Generate complete paths
paths = fill_gen.generate_fill(geometry, trace_centerlines=trace_centerlines, offset_centerlines=False, pads=pads, drill_holes=drill_holes)

print(f"\nTotal paths generated: {len(paths)}")

# Check if junction fills are in the final paths
junction_in_paths = 0
for junction_fill in junction_fills:
    for path in paths:
        # Check if this path is the same as a junction fill (by identity or equality)
        if path is junction_fill or path.equals(junction_fill):
            junction_in_paths += 1
            break

print(f"Junction fills found in final paths: {junction_in_paths} / {len(junction_fills)}")

if junction_in_paths < len(junction_fills):
    print(f"\n⚠ WARNING: {len(junction_fills) - junction_in_paths} junction fills are MISSING from final paths!")
    print("This means they're being filtered out somewhere in the fill generation process.")
else:
    print(f"\n✓ All junction fills are present in final paths")

# Show some details about junction fills
if junction_fills:
    print(f"\nJunction fill details:")
    for i, fill in enumerate(junction_fills[:3]):  # Show first 3
        coords = list(fill.coords)
        print(f"  Junction {i+1}: {len(coords)} points, length {fill.length:.3f}mm")
        print(f"    Start: ({coords[0][0]:.2f}, {coords[0][1]:.2f})")
        print(f"    End: ({coords[-1][0]:.2f}, {coords[-1][1]:.2f})")

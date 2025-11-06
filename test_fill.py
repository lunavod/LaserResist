"""Test script for fill generation and visualization."""

from pathlib import Path
from src.laserresist.gerber_parser import GerberParser
from src.laserresist.fill_generator import FillGenerator
from src.laserresist.visualizer import PCBVisualizer


def main():
    """Test the fill generator with visualization."""
    gerber_file = Path("examples/test.gtl")
    drill_pth_file = Path("examples/Drill_PTH_Through.DRL")
    drill_via_file = Path("examples/Drill_PTH_Through_Via.DRL")

    print(f"Loading Gerber file: {gerber_file}")
    parser = GerberParser(gerber_file, drill_pth_file, drill_via_file)

    print("Parsing geometry...")
    geometry = parser.parse()

    print(f"Parsed geometry:")
    if hasattr(geometry, 'geoms'):
        print(f"  Number of polygons: {len(geometry.geoms)}")
        total_area = sum(poly.area for poly in geometry.geoms)
        print(f"  Total area: {total_area:.2f} mm²")
    else:
        print(f"  Single polygon area: {geometry.area:.2f} mm²")

    bounds = parser.get_bounds()

    # Get trace centerlines
    trace_centerlines = parser.get_trace_centerlines()
    print(f"  Found {len(trace_centerlines)} trace centerlines")

    # Generate fill paths
    print("\nGenerating fill paths...")
    fill_gen = FillGenerator(line_spacing=0.1)
    paths = fill_gen.generate_fill(geometry, trace_centerlines=trace_centerlines)

    print(f"Generated {len(paths)} fill paths")

    # Count how many are very short (likely centerlines/dots)
    short_paths = [p for p in paths if p.length < 1.0]
    medium_paths = [p for p in paths if 1.0 <= p.length < 5.0]
    long_paths = [p for p in paths if p.length >= 5.0]
    print(f"  Short paths (<1mm): {len(short_paths)}")
    print(f"  Medium paths (1-5mm): {len(medium_paths)}")
    print(f"  Long paths (>=5mm): {len(long_paths)}")

    # Calculate total path length
    total_length = sum(path.length for path in paths)
    print(f"Total path length: {total_length:.2f} mm")

    # Visualize
    print("\nGenerating visualization...")
    output_file = Path("output/fill_visualization.png")
    output_file.parent.mkdir(exist_ok=True)

    viz = PCBVisualizer(figsize=(14, 12))

    # Plot copper geometry (semi-transparent so we can see paths)
    viz.plot_geometry(geometry, color="gold", alpha=0.3, edgecolor="darkgoldenrod", linewidth=0.8)

    # Plot fill paths on top
    viz.plot_paths(paths, color="cyan", alpha=0.8, linewidth=0.5, label="Fill paths")

    viz.set_bounds(*bounds, margin=2.0)
    viz.add_labels(title="PCB Fill Pattern (Contour Method)")
    viz.save(output_file)

    print(f"Visualization saved to: {output_file}")


if __name__ == "__main__":
    main()

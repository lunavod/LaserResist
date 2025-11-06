"""Test script to visualize the effect of initial_offset parameter."""

from pathlib import Path
from src.laserresist.gerber_parser import GerberParser
from src.laserresist.fill_generator import FillGenerator
from src.laserresist.visualizer import PCBVisualizer


def main():
    """Test the initial_offset parameter with visualization."""
    gerber_file = Path("examples/test.gtl")
    drill_pth_file = Path("examples/Drill_PTH_Through.DRL")
    drill_via_file = Path("examples/Drill_PTH_Through_Via.DRL")

    print(f"Loading Gerber file: {gerber_file}")
    parser = GerberParser(gerber_file, drill_pth_file, drill_via_file)

    print("Parsing geometry...")
    geometry = parser.parse()
    bounds = parser.get_bounds()
    trace_centerlines = parser.get_trace_centerlines()

    print(f"\nParsed geometry:")
    if hasattr(geometry, 'geoms'):
        print(f"  Number of polygons: {len(geometry.geoms)}")
        total_area = sum(poly.area for poly in geometry.geoms)
        print(f"  Total area: {total_area:.2f} mm²")
    print(f"  Trace centerlines: {len(trace_centerlines)}")

    # Generate fill paths WITHOUT initial offset
    print("\n" + "="*60)
    print("TEST 1: WITHOUT initial offset (initial_offset=0)")
    print("="*60)
    fill_gen_no_offset = FillGenerator(line_spacing=0.1, initial_offset=0.0)
    paths_no_offset = fill_gen_no_offset.generate_fill(geometry, trace_centerlines=trace_centerlines)

    total_length_no_offset = sum(path.length for path in paths_no_offset)
    print(f"Generated {len(paths_no_offset)} fill paths")
    print(f"Total path length: {total_length_no_offset:.2f} mm")

    # Generate fill paths WITH initial offset (default 0.05mm)
    print("\n" + "="*60)
    print("TEST 2: WITH initial offset (initial_offset=0.05mm)")
    print("="*60)
    fill_gen_with_offset = FillGenerator(line_spacing=0.1, initial_offset=0.05)
    paths_with_offset = fill_gen_with_offset.generate_fill(geometry, trace_centerlines=trace_centerlines)

    total_length_with_offset = sum(path.length for path in paths_with_offset)
    print(f"Generated {len(paths_with_offset)} fill paths")
    print(f"Total path length: {total_length_with_offset:.2f} mm")

    # Calculate differences
    print("\n" + "="*60)
    print("COMPARISON:")
    print("="*60)
    print(f"Path count difference: {len(paths_with_offset) - len(paths_no_offset)} paths")
    print(f"Total length difference: {total_length_with_offset - total_length_no_offset:.2f} mm")
    print(f"Length increase: {((total_length_with_offset / total_length_no_offset - 1) * 100):.2f}%")

    # Visualize both results
    print("\nGenerating visualizations...")
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    # Visualization 1: Without initial offset
    viz1 = PCBVisualizer(figsize=(14, 12))
    viz1.plot_geometry(geometry, color="gold", alpha=0.3, edgecolor="darkgoldenrod", linewidth=0.8)
    viz1.plot_paths(paths_no_offset, color="cyan", alpha=0.8, linewidth=0.5, label="Fill paths")
    viz1.set_bounds(*bounds, margin=2.0)
    viz1.add_labels(title="PCB Fill Pattern - NO Initial Offset (0mm)")
    output_file_1 = output_dir / "fill_no_offset.png"
    viz1.save(output_file_1)
    print(f"  Saved: {output_file_1}")

    # Visualization 2: With initial offset
    viz2 = PCBVisualizer(figsize=(14, 12))
    viz2.plot_geometry(geometry, color="gold", alpha=0.3, edgecolor="darkgoldenrod", linewidth=0.8)
    viz2.plot_paths(paths_with_offset, color="lime", alpha=0.8, linewidth=0.5, label="Fill paths (with offset)")
    viz2.set_bounds(*bounds, margin=2.0)
    viz2.add_labels(title="PCB Fill Pattern - WITH Initial Offset (0.05mm)")
    output_file_2 = output_dir / "fill_with_offset.png"
    viz2.save(output_file_2)
    print(f"  Saved: {output_file_2}")

    # Visualization 3: Side-by-side comparison on zoomed section
    # Let's create an overlay comparison
    viz3 = PCBVisualizer(figsize=(16, 12))
    viz3.plot_geometry(geometry, color="gold", alpha=0.2, edgecolor="darkgoldenrod", linewidth=0.8)
    viz3.plot_paths(paths_no_offset, color="cyan", alpha=0.5, linewidth=0.5, label="No offset (0mm)")
    viz3.plot_paths(paths_with_offset, color="lime", alpha=0.5, linewidth=0.5, label="With offset (0.05mm)")
    viz3.set_bounds(*bounds, margin=2.0)
    viz3.add_labels(title="PCB Fill Pattern - Comparison: No Offset (cyan) vs With Offset (lime)")
    output_file_3 = output_dir / "fill_comparison.png"
    viz3.save(output_file_3)
    print(f"  Saved: {output_file_3}")

    print("\n" + "="*60)
    print("Visualizations complete!")
    print("="*60)
    print("\nThe initial_offset expands the copper geometry outward before filling,")
    print("compensating for the laser dot size. You should see more coverage in the")
    print("offset version (lime) compared to the no-offset version (cyan).")


if __name__ == "__main__":
    main()

"""Quick test script for the Gerber parser."""

from pathlib import Path
from src.laserresist.gerber_parser import GerberParser
from src.laserresist.visualizer import visualize_gerber


def main():
    """Test the parser with the example file."""
    gerber_file = Path("examples/test.gtl")
    drill_pth_file = Path("examples/Drill_PTH_Through.DRL")
    drill_via_file = Path("examples/Drill_PTH_Through_Via.DRL")

    print(f"Loading Gerber file: {gerber_file}")
    print(f"Loading drill files: {drill_pth_file}, {drill_via_file}")
    parser = GerberParser(gerber_file, drill_pth_file, drill_via_file)

    print("Parsing geometry...")
    geometry = parser.parse()

    print(f"\nResults:")
    print(f"  Geometry type: {type(geometry).__name__}")

    if hasattr(geometry, 'geoms'):
        print(f"  Number of polygons: {len(geometry.geoms)}")
        total_area = sum(poly.area for poly in geometry.geoms)
        print(f"  Total area: {total_area:.2f} mm²")
    else:
        print(f"  Single polygon area: {geometry.area:.2f} mm²")

    bounds = parser.get_bounds()
    print(f"  Bounding box: ({bounds[0]:.2f}, {bounds[1]:.2f}) to ({bounds[2]:.2f}, {bounds[3]:.2f}) mm")
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    print(f"  Board dimensions: {width:.2f} x {height:.2f} mm")

    # Visualize the parsed geometry
    print("\nGenerating visualization...")
    output_file = Path("output/parsed_gerber.png")
    output_file.parent.mkdir(exist_ok=True)

    visualize_gerber(
        geometry,
        bounds,
        output_path=output_file,
        title=f"Parsed: {gerber_file.name}",
    )

    print(f"Visualization saved to: {output_file}")


if __name__ == "__main__":
    main()

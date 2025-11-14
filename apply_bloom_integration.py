"""Script to automatically integrate bloom compensation into cli.py"""

import re
from pathlib import Path

CLI_FILE = Path("src/laserresist/cli.py")

def integrate_bloom_compensation():
    """Apply all bloom compensation changes to cli.py"""

    print("Reading cli.py...")
    with open(CLI_FILE, 'r', encoding='utf-8') as f:
        content = f.read()

    original_content = content

    # 1. Add import
    print("1. Adding bloom_compensator import...")
    import_section = "from .template_generator import TemplateGenerator"
    if "from .bloom_compensator import" not in content:
        content = content.replace(
            import_section,
            import_section + "\nfrom .bloom_compensator import FastBloomSimulator, identify_underexposed_traces, generate_compensation_paths"
        )

    # 2. Add config keys
    print("2. Adding bloom config keys...")
    known_keys_pattern = r"(known_keys = \{[^}]+# Fill generation[^}]+)"
    match = re.search(known_keys_pattern, content)
    if match and "'bloom_compensation'" not in content:
        old_text = match.group(0)
        # Add after 'isolation_threshold'
        new_text = old_text.replace(
            "'double_expose_isolated', 'isolation_threshold',",
            "'double_expose_isolated', 'isolation_threshold', 'bloom_compensation', 'bloom_resolution', 'bloom_spot_sigma', 'bloom_scatter_sigma', 'bloom_scatter_fraction', 'bloom_threshold_percentile',"
        )
        content = content.replace(old_text, new_text)

    # 3. Add CLI arguments
    print("3. Adding CLI arguments...")
    force_trace_arg = '''    fill_group.add_argument(
        "--force-trace-centerlines",
        action="store_true",
        help="Force all trace centerlines without clipping to avoid filled zones (default: False)",
    )'''

    bloom_args = '''    fill_group.add_argument(
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
    )'''

    if "--bloom-compensation" not in content:
        content = content.replace(force_trace_arg, bloom_args)

    # 4. Add config value retrieval
    print("4. Adding config value retrieval...")
    isolation_line = "    isolation_threshold = get_value('isolation_threshold', default=3.0)"
    bloom_config = """    isolation_threshold = get_value('isolation_threshold', default=3.0)

    bloom_compensation = get_value('bloom_compensation', default=False)
    bloom_resolution = get_value('bloom_resolution', default=0.05)
    bloom_spot_sigma = get_value('bloom_spot_sigma', default=0.05)
    bloom_scatter_sigma = get_value('bloom_scatter_sigma', default=2.0)
    bloom_scatter_fraction = get_value('bloom_scatter_fraction', default=0.35)
    bloom_threshold_percentile = get_value('bloom_threshold_percentile', default=30)"""

    if "bloom_compensation = get_value" not in content:
        content = content.replace(isolation_line, bloom_config)

    # 5. Add settings print
    print("5. Adding settings print...")
    bed_mesh_print = "    if bed_mesh:\n        print(f\"  Bed mesh: enabled (offset={mesh_offset}mm, probe={probe_count[0]}x{probe_count[1]})\")"
    bloom_print = """    if bed_mesh:
        print(f"  Bed mesh: enabled (offset={mesh_offset}mm, probe={probe_count[0]}x{probe_count[1]})")
    if bloom_compensation:
        print(f"  Bloom compensation: enabled (scatter={bloom_scatter_sigma}mm, threshold={bloom_threshold_percentile}%)")"""

    if "Bloom compensation: enabled" not in content:
        content = content.replace(bed_mesh_print, bloom_print)

    # 6. Add bloom compensation logic after fill generation
    print("6. Adding bloom compensation logic...")

    # Find the section after isolated_paths assignment
    old_section = """    # Handle both list and dict return types
    if isinstance(result, dict):
        paths = result['normal']
        isolated_paths = result['isolated']
    else:
        paths = result
        isolated_paths = []

    total_length = sum(path.length for path in paths)
    isolated_length = sum(path.length for path in isolated_paths)
    print(f"  Generated {len(paths)} normal paths, {len(isolated_paths)} isolated paths")
    if isolated_paths:
        print(f"  Total length: {total_length:.2f}mm normal + {isolated_length:.2f}mm isolated (will be exposed twice)")
    else:
        print(f"  Total length: {total_length:.2f} mm")"""

    new_section = """    # Handle both list and dict return types
    if isinstance(result, dict):
        paths = result['normal']
        isolated_paths = result['isolated']
    else:
        paths = result
        isolated_paths = []

    # Bloom compensation
    bloom_compensation_paths = []
    if bloom_compensation:
        print(f"\\nRunning bloom compensation analysis...")

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
        print(f"  Total length: {total_length:.2f} mm")"""

    if "bloom_compensation_paths = []" not in content:
        content = content.replace(old_section, new_section)

    # 7. Update G-code generation call
    print("7. Updating G-code generation...")
    old_gcode = "    with open(output_file, 'w') as f:\n        gcode_gen.generate(paths, f, bounds, board_outline_bounds, isolated_paths=isolated_paths if isolated_paths else None)"

    new_gcode = """    # Combine isolated paths and bloom compensation paths
    double_expose_paths = isolated_paths if isolated_paths else []
    if bloom_compensation_paths:
        double_expose_paths.extend(bloom_compensation_paths)

    with open(output_file, 'w') as f:
        gcode_gen.generate(paths, f, bounds, board_outline_bounds,
                         isolated_paths=double_expose_paths if double_expose_paths else None)"""

    if "double_expose_paths = " not in content:
        content = content.replace(old_gcode, new_gcode)

    # Write the file if changes were made
    if content != original_content:
        print("\nWriting updated cli.py...")
        with open(CLI_FILE, 'w', encoding='utf-8') as f:
            f.write(content)
        print("✓ Integration complete!")
        return True
    else:
        print("\n✓ All changes already applied!")
        return False

if __name__ == "__main__":
    try:
        integrate_bloom_compensation()
    except Exception as e:
        print(f"\nError: {e}")
        print("\nPlease refer to BLOOM_INTEGRATION_GUIDE.md for manual integration steps.")

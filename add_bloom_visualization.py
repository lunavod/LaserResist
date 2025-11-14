"""Add bloom visualization parameter to CLI"""

import re
from pathlib import Path

CLI_FILE = Path("src/laserresist/cli.py")

def add_visualization_support():
    """Add bloom visualization image parameter"""

    print("Adding bloom visualization support...")
    with open(CLI_FILE, 'r', encoding='utf-8') as f:
        content = f.read()

    original_content = content

    # 1. Update import
    print("1. Updating import...")
    old_import = "from .bloom_compensator import FastBloomSimulator, identify_underexposed_traces, generate_compensation_paths"
    new_import = "from .bloom_compensator import FastBloomSimulator, identify_underexposed_traces, generate_compensation_paths, generate_debug_visualization"
    if old_import in content and "generate_debug_visualization" not in content:
        content = content.replace(old_import, new_import)

    # 2. Add config key
    print("2. Adding config key...")
    if "'bloom_debug_image'" not in content:
        content = content.replace(
            "'bloom_threshold_percentile',",
            "'bloom_threshold_percentile', 'bloom_debug_image',"
        )

    # 3. Add CLI argument
    print("3. Adding CLI argument...")
    bloom_threshold_arg = '''    fill_group.add_argument(
        "--bloom-threshold-percentile",
        type=float,
        help="Percentile threshold for under-exposure detection (default: 30)",
    )'''

    bloom_with_debug = '''    fill_group.add_argument(
        "--bloom-threshold-percentile",
        type=float,
        help="Percentile threshold for under-exposure detection (default: 30)",
    )
    fill_group.add_argument(
        "--bloom-debug-image",
        action="store_true",
        help="Generate bloom visualization image alongside G-code (default: False)",
    )'''

    if "--bloom-debug-image" not in content:
        content = content.replace(bloom_threshold_arg, bloom_with_debug)

    # 4. Add config value retrieval
    print("4. Adding config value retrieval...")
    threshold_line = "    bloom_threshold_percentile = get_value('bloom_threshold_percentile', default=30)"
    debug_line = '''    bloom_threshold_percentile = get_value('bloom_threshold_percentile', default=30)
    bloom_debug_image = get_value('bloom_debug_image', default=False)'''

    if "bloom_debug_image = get_value" not in content:
        content = content.replace(threshold_line, debug_line)

    # 5. Add visualization call in bloom compensation section
    print("5. Adding visualization call...")

    # Find the section where compensation paths are generated
    pattern = r"(bloom_compensation_paths = generate_compensation_paths\(\s+underexposed_traces,\s+fill_gen\s+\))\s+(print\(f\"  Generated \{len\(bloom_compensation_paths\)\} compensation paths\"\))"

    replacement = r'''\1
            \2

            # Generate debug visualization if requested
            if bloom_debug_image:
                debug_image_path = output_file.with_suffix('.bloom.png')
                generate_debug_visualization(
                    simulator, geometry, normal_traces, underexposed_traces,
                    bloom_compensation_paths, debug_image_path,
                    verbose=args.verbose
                )'''

    if "generate_debug_visualization" not in content:
        content = re.sub(pattern, replacement, content)

    if content != original_content:
        print("\nWriting updated cli.py...")
        with open(CLI_FILE, 'w', encoding='utf-8') as f:
            f.write(content)
        print("✓ Visualization support added!")
        return True
    else:
        print("\n✓ Visualization support already present!")
        return False

if __name__ == "__main__":
    try:
        add_visualization_support()
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()

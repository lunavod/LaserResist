"""Command-line interface for LaserResist."""

import argparse
from pathlib import Path


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="Generate laser exposure G-code from Gerber files"
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Input Gerber file (.gbr, .gtl, .gbl, etc.)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output G-code file (default: input.gcode)",
    )
    parser.add_argument(
        "--line-spacing",
        type=float,
        default=0.1,
        help="Spacing between fill lines in mm (default: 0.1)",
    )
    parser.add_argument(
        "--laser-power",
        type=float,
        default=100,
        help="Laser power percentage (default: 100)",
    )
    parser.add_argument(
        "--feed-rate",
        type=float,
        default=1000,
        help="Feed rate in mm/min (default: 1000)",
    )

    args = parser.parse_args()

    # Validate input file exists
    if not args.input.exists():
        print(f"Error: Input file '{args.input}' not found")
        return 1

    # Set default output file if not specified
    if args.output is None:
        args.output = args.input.with_suffix(".gcode")

    print(f"Input: {args.input}")
    print(f"Output: {args.output}")
    print(f"Line spacing: {args.line_spacing}mm")
    print(f"Laser power: {args.laser_power}%")
    print(f"Feed rate: {args.feed_rate}mm/min")

    # TODO: Implement processing pipeline
    print("\nProcessing not yet implemented...")

    return 0


if __name__ == "__main__":
    exit(main())

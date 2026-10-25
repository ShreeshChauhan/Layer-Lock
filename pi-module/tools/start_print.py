"""Start a print without the OctoPrint dashboard.

  python -m tools.start_print --list
  python -m tools.start_print path\\to\\part.gcode
  python -m tools.start_print --remote part.gcode
"""
import argparse
import sys

from hardware import config, OctoPrinter, MockPrinter, PrinterError, PrintBlocked


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?", help="local .gcode file to upload and print")
    ap.add_argument("--remote", help="print a file already stored on OctoPrint")
    ap.add_argument("--list", action="store_true", help="list files stored on OctoPrint")
    ap.add_argument("--yes", action="store_true", help="skip the bed-is-clear confirmation")
    args = ap.parse_args()

    printer = MockPrinter() if config.MOCK else OctoPrinter()

    try:
        if args.list:
            for f in printer.list_files():
                print(f"{f['path']}  ({(f['size'] or 0) // 1024} KB)")
            return 0

        target = args.remote or args.file
        if not target:
            ap.error("give a file, --remote NAME, or --list")

        if not args.yes and input("Is the bed clear and the filament loaded? [y/N] ").lower() != "y":
            print("Aborted.")
            return 1

        if args.remote:
            printer.start_print(args.remote)
        else:
            target = printer.print_file(args.file)
        print(f"Started: {target}")
        return 0
    except PrintBlocked as e:
        print(f"Not started: {e}")
        return 2
    except PrinterError as e:
        print(f"Error: {e}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
"""Run with libpq PGHOST/PGPORT/PGUSER/PGDATABASE/PGPASSFILE environment.

No credentials are printed or placed on the command line. Restores are limited
to a separate database named focus_restore_*; existing databases are refused.
"""
import argparse
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "verify", "restore-drill"])
    parser.add_argument("file", type=Path)
    parser.add_argument("--database")
    args = parser.parse_args()
    if args.action == "backup":
        # Exclusive creation avoids clobbering an earlier backup.
        with args.file.open("xb") as output:
            try:
                os.chmod(args.file, 0o600)
                subprocess.run(["pg_dump", "--format=custom", "--no-owner", "--no-acl"], stdout=output, check=True)
            except BaseException:
                output.close()
                args.file.unlink()
                raise
    elif args.action == "verify":
        subprocess.run(["pg_restore", "--list", str(args.file.resolve())], stdout=subprocess.DEVNULL, check=True)
    else:
        if not args.database or not args.database.startswith("focus_restore_") or not all(c.isalnum() or c == "_" for c in args.database):
            parser.error("Use a NEW database named focus_restore_*")
        subprocess.run(["createdb", args.database], check=True)
        subprocess.run(["pg_restore", "--exit-on-error", "--single-transaction", "--no-owner", "--no-acl", "--dbname", args.database, str(args.file.resolve())], check=True)
        print("Restore complete in the isolated database; inspect it before removing it.")


if __name__ == "__main__":
    main()

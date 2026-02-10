import argparse, subprocess, sys

def run(cmd):
    print("+", " ".join(cmd))
    r = subprocess.run(cmd, check=False)
    if r.returncode != 0:
        sys.exit(r.returncode)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", required=True, choices=["A","B","C","D"])
    ap.add_argument("--date", default=None)
    args = ap.parse_args()

    run(["python", "scripts/pull_snapshot.py"])
    cmd = ["python", "scripts/generate_next.py", "--type", args.type]
    if args.date:
        cmd += ["--date", args.date]
    run(cmd)
    run(["python", "scripts/validate_plan.py"])
    run(["python", "scripts/push_plan.py"])
    print("OK: end-to-end run completed.")

if __name__ == "__main__":
    main()

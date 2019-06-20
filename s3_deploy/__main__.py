from s3_deploy import main
import sys

def console_entry():
    main(None, sys.stdout, sys.stderr)

if __name__ == "__main__":
    main(None, sys.stdout, sys.stderr)

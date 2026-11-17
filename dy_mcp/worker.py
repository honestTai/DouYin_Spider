import argparse
import json

from dotenv import load_dotenv

from .engine import MultiAccountEngine


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("account_id")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--aweme-id", default="")
    args = parser.parse_args(argv)
    load_dotenv()
    result = MultiAccountEngine().run(
        args.account_id, dry_run=not args.live, confirm=args.live,
        aweme_id=args.aweme_id,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

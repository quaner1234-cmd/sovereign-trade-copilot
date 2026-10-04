"""Local operator actions over an explicitly private Company Context ledger."""
import argparse
import json
import sqlite3
import sys
from .private_context import ContextStore
from .natural_updates import apply_text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True, help="Absolute database path outside any Git checkout")
    parser.add_argument("--actor", help="Authorized operator identity for writes")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    record = commands.add_parser("record")
    record.add_argument("--file", required=True, help="Private JSON source and candidate ledger")
    record.add_argument("--authority", choices=["reference", "trusted_company"], default="reference")
    confirm = commands.add_parser("confirm")
    confirm.add_argument("candidate_id")
    edit = commands.add_parser("edit")
    edit.add_argument("text", help="Explicit operator edit, e.g. MOQ 改 300，正常交期 100 天")
    edit.add_argument("--target", action="append", default=None, help="Candidate to adjudicate when ambiguous")
    for command in (confirm, edit):
        command.add_argument("--global", dest="global_scope", action="store_true")
        command.add_argument("--project-id")
        command.add_argument("--product-category", action="append")
        command.add_argument("--market", action="append")
        command.add_argument("--condition", action="append")
        command.add_argument("--quantity-min", type=int)
        command.add_argument("--quantity-max", type=int)
        command.add_argument("--quantity-unit", default="pcs")
    args = parser.parse_args(argv)
    try:
        store = ContextStore(args.store)
        if args.command == "list":
            result = store.view()
        elif args.command == "record":
            with open(args.file, encoding="utf-8") as source:
                result = store.record(json.load(source), authority=args.authority, actor=args.actor)
        else:
            scope = {}
            if args.global_scope:
                scope["global"] = True
            for arg, key in (("project_id", "project_id"), ("product_category", "product_categories"),
                             ("market", "markets"), ("condition", "conditions")):
                if getattr(args, arg):
                    scope[key] = getattr(args, arg)
            if args.quantity_min is not None or args.quantity_max is not None:
                scope["quantity_range"] = {"unit": args.quantity_unit}
                for key, value in (("min", args.quantity_min), ("max", args.quantity_max)):
                    if value is not None:
                        scope["quantity_range"][key] = value
            if args.command == "confirm":
                result = store.confirm(args.candidate_id, actor=args.actor, scope_spec=scope)
            else:
                result = apply_text(store, args.text, actor=args.actor, scope_spec=scope, target_ids=args.target)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except ValueError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except (OSError, sqlite3.Error):
        # No local paths or stored values leak into CLI error diagnostics.
        print('{"error":"private context unavailable"}', file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

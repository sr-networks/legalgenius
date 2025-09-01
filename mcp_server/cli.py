import argparse
import json
import sys
from typing import Any, Dict

from mcp_server import tools


def _print_json(data: Dict[str, Any]) -> None:
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    sys.stdout.flush()


def cmd_search(args: argparse.Namespace) -> None:
    result = tools.elasticsearch_search(
        query=args.query or "",
        document_type=args.document_type,
        max_results=args.max_results,
        context_lines=args.context_lines,
        es_host=args.es_host,
        es_port=args.es_port,
    )
    wrapped = {
        "tool": "elasticsearch_search",
        "args": {
            "query": args.query,
            "document_type": args.document_type,
            "max_results": args.max_results,
            "context_lines": args.context_lines,
            "es_host": args.es_host,
            "es_port": args.es_port,
        },
        "result": result,
    }
    _print_json(wrapped)


def cmd_read(args: argparse.Namespace) -> None:
    result = tools.read_file_range(
        path=args.path,
        start=args.start,
        end=args.end,
        context=args.context,
    )
    wrapped = {
        "tool": "read_file_range",
        "args": {"path": args.path, "start": args.start, "end": args.end, "context": args.context},
        "result": result,
    }
    _print_json(wrapped)


def cmd_list(args: argparse.Namespace) -> None:
    result = tools.list_paths(subdir=args.subdir)
    wrapped = {
        "tool": "list_paths",
        "args": {"subdir": args.subdir},
        "result": result,
    }
    _print_json(wrapped)


def cmd_filesearch(args: argparse.Namespace) -> None:
    result = tools.file_search(
        query=args.query,
        glob=args.glob,
        case_sensitive=args.case_sensitive,
        max_results=args.max_results,
    )
    wrapped = {
        "tool": "file_search",
        "args": {
            "query": args.query,
            "glob": args.glob,
            "case_sensitive": args.case_sensitive,
            "max_results": args.max_results,
        },
        "result": result,
    }
    _print_json(wrapped)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CLI to test mcp_server.tools",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="Elasticsearch full-text search across legal corpus")
    p_search.add_argument("--query", required=True, help="Search terms or phrases (e.g., 'Kündigungsfrist', 'BGB § 573')")
    p_search.add_argument("--document-type", choices=["all", "gesetze", "urteile"], default="all", help="Limit search to document type")
    p_search.add_argument("--max-results", type=int, default=10, help="Max number of results to return (default 10)")
    p_search.add_argument("--context-lines", type=int, default=2, help="Lines of context to include around matches (default 2)")
    p_search.add_argument("--es-host", default="localhost", help="Elasticsearch host (default localhost)")
    p_search.add_argument("--es-port", type=int, default=9200, help="Elasticsearch port (default 9200)")
    p_search.set_defaults(func=cmd_search)

    p_read = sub.add_parser("read", help="Read a byte range from a file with optional context")
    p_read.add_argument("--path", required=True, help="Path relative to legal doc root")
    p_read.add_argument("--start", type=int, required=True, help="Start byte (exclusive of added context)")
    p_read.add_argument("--end", type=int, required=True, help="End byte (exclusive of added context)")
    p_read.add_argument("--context", type=int, default=None, help="Extra bytes of context to include on both sides")
    p_read.set_defaults(func=cmd_read)

    p_list = sub.add_parser("list", help="List allowed files under a subdirectory")
    p_list.add_argument("--subdir", default=".", help="Subdirectory under the legal doc root")
    p_list.set_defaults(func=cmd_list)

    p_fsearch = sub.add_parser("files", help="Return files whose contents match a boolean query (whole-file scope)")
    p_fsearch.add_argument("--query", default=None, help="Boolean expression over path names, e.g. 'bgb AND (index OR 2021)' ")
    p_fsearch.add_argument("--glob", default=None, help="Glob to limit considered files")
    p_fsearch.add_argument("--case-sensitive", action="store_true", help="Enable case-sensitive path matching")
    p_fsearch.add_argument("--max-results", type=int, default=None, help="Max files to return")
    p_fsearch.set_defaults(func=cmd_filesearch)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


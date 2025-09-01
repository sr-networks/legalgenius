#!/usr/bin/env python3
"""
Test CLI script for Elasticsearch-backed search.
Runs full-text queries across laws (gesetze) and court decisions (urteile).
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Add the mcp_server directory to the path
sys.path.insert(0, str(Path(__file__).parent / "mcp_server"))

from tools import elasticsearch_search


def main():
    parser = argparse.ArgumentParser(
        description="Test the Elasticsearch search tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single term
  python test_search.py "Testament"

  # Phrase
  python test_search.py "fristlose Kündigung"

  # Limit to document type
  python test_search.py "BGB § 573" --document-type gesetze

  # Multiple terms
  python test_search.py "Mietrecht Kündigung" --max-results 5
        """
    )
    
    parser.add_argument(
        "query", 
        help="Search query (space-separated keywords for two-phase search)"
    )
    parser.add_argument("--document-type", choices=["all", "gesetze", "urteile"], default="all", help="Type of documents to search")
    parser.add_argument("--max-results", type=int, default=10, help="Maximum number of results (default: 10)")
    parser.add_argument("--context-lines", type=int, default=2, help="Number of context lines per match (default: 2)")
    parser.add_argument("--host", default="localhost", help="Elasticsearch host (default: localhost)")
    parser.add_argument("--port", type=int, default=9200, help="Elasticsearch port (default: 9200)")
    parser.add_argument(
        "--json", 
        action="store_true",
        help="Output raw JSON results"
    )
    
    args = parser.parse_args()
    
    print(f"🔍 Query: '{args.query}' | Type: {args.document_type} | Max: {args.max_results}")
    print(f"🔌 ES: http://{args.host}:{args.port} | Context lines: {args.context_lines}")
    
    print("=" * 70)
    
    try:
        results = elasticsearch_search(
            query=args.query,
            document_type=args.document_type,
            max_results=args.max_results,
            context_lines=args.context_lines,
            es_host=args.host,
            es_port=args.port,
        )
        
        if args.json:
            print(json.dumps(results, indent=2, ensure_ascii=False))
            return
        
        if "error" in results:
            print(f"❌ Error: {results['error']}")
            if "Use more specific keywords" in results['error']:
                print("💡 Tip: Try adding more specific keywords to narrow the search")
            return
        
        matches = results.get("matches", [])
        print(f"📋 Found {len(matches)} results (total_hits={results.get('total_hits')})")
        print()
        for i, match in enumerate(matches, 1):
            title = match.get("title", "Untitled")
            doc_type = match.get("document_type", "?")
            file_path = match.get("file_path", "")
            score = match.get("score", 0.0)
            preview = match.get("content_preview", "")
            print(f"#{i} [{doc_type}] {title} (score={score:.3f})")
            print(f"   ↳ {file_path}")
            if preview:
                print(f"   ✎ {preview}")
            # Show up to one context block with matching lines
            for lm in match.get("line_matches", [])[:1]:
                ctx = lm.get("context", [])
                print("   Context:")
                for row in ctx:
                    ln = row.get("line_number")
                    marker = ">>>" if row.get("is_match") else "   "
                    text = row.get("text", "")
                    print(f"   {marker} {ln:5d}: {text}")
            print("-" * 70)
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        if args.verbose:
            print("\n🔍 Traceback:")
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

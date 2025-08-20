#!/usr/bin/env python3
"""
Test CLI script for the two-phase search_rg tool.
Tests file filtering and keyword segment search.
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Add the mcp_server directory to the path
sys.path.insert(0, str(Path(__file__).parent / "mcp_server"))

from tools import search_rg


def main():
    parser = argparse.ArgumentParser(
        description="Test the two-phase search_rg tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single keyword search
  python test_search.py "Testament" --files urteile_markdown_by_year/
  
  # Two-phase multi-keyword search
  python test_search.py "Testament Geschäftsgebühr" --files urteile_markdown_by_year/
  
  # Test file filtering limits
  python test_search.py "der" --files urteile_markdown_by_year/ --max-files 10
  
  # Search in specific directories
  python test_search.py "gemeinschaftlich Testament" --files gesetze/ urteile_markdown_by_year/
        """
    )
    
    parser.add_argument(
        "query", 
        help="Search query (space-separated keywords for two-phase search)"
    )
    parser.add_argument(
        "--files", 
        nargs="+", 
        default=["./"],
        help="File patterns to search (default: entire corpus)"
    )
    parser.add_argument(
        "--max-results", 
        type=int, 
        default=10,
        help="Maximum number of results (default: 10)"
    )
    parser.add_argument(
        "--context", 
        type=int, 
        default=10,
        help="Number of context lines (default: 10)"
    )
    parser.add_argument(
        "--passage-lines", 
        type=int, 
        default=10,
        help="Number of lines to search for all terms within (default: 10)"
    )
    parser.add_argument(
        "--case-sensitive", 
        action="store_true",
        help="Case-sensitive search"
    )
    parser.add_argument(
        "--json", 
        action="store_true",
        help="Output raw JSON results"
    )
    parser.add_argument(
        "--verbose", 
        action="store_true",
        help="Show detailed phase information"
    )
    
    args = parser.parse_args()
    
    # Parse keywords for phase info
    is_or_query = " OR " in args.query.upper()
    if is_or_query:
        keywords = [part.strip() for part in re.split(r'\s+OR\s+', args.query, flags=re.IGNORECASE)]
        keywords = [kw for kw in keywords if kw and kw.upper() != "OR"]
    else:
        keywords = args.query.split()
    
    print(f"🔍 Query: '{args.query}'")
    print(f"📁 Files: {args.files}")
    print(f"📊 Max results: {args.max_results}, Context: {args.context}")
    
    if args.verbose:
        if len(keywords) > 1:
            print(f"🔄 rg/awk pipeline search:")
            print(f"   rg: Find chunks with OR of keywords: {keywords}")
            print(f"   awk: Filter chunks with all keywords (AND logic)")
        else:
            print(f"🔄 rg/awk pipeline search: single keyword")
    
    print("=" * 70)
    
    try:
        results = search_rg(
            query=args.query,
            file_list=args.files,
            max_results=args.max_results,
            context_lines=args.context,
            case_sensitive=args.case_sensitive
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
        print(f"📋 Found {len(matches)} matches")
        
        if args.verbose and matches:
            # Show file distribution
            files = set(match.get("file", "") for match in matches)
            print(f"📂 Across {len(files)} files")
            for file in sorted(files):
                count = sum(1 for m in matches if m.get("file") == file)
                print(f"   • {file}: {count} match{'es' if count != 1 else ''}")
        
        print()
        
        for i, match in enumerate(matches, 1):
            file_path = match.get("file", "")
            line_num = match.get("line", 0)
            text = match.get("text", "")
            section = match.get("section", "")
            context = match.get("context", [])
            byte_range = match.get("byte_range", [0, 0])
            
            print(f"🎯 Match {i}: {file_path}:{line_num}")
            if section:
                print(f"📖 Section: {section}")
            if args.verbose:
                print(f"📍 Byte range: {byte_range[0]}-{byte_range[1]}")
            
            print("📄 Context:")
            for ctx_line in context:
                line_no = ctx_line.get("line", 0)
                line_text = ctx_line.get("text", "")
                marker = ">>>" if line_no == line_num else "   "
                
                # No truncation - show full lines
                
                print(f"  {marker} {line_no:5d}: {line_text}")
            
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

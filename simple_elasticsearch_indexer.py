#!/usr/bin/env python3
"""
Simple Elasticsearch indexer for legal documents

This script indexes all documents from the data folder into Elasticsearch,
using requests library for better compatibility.
"""

import os
import re
import json
import requests
from pathlib import Path
from typing import Dict, Any, List, Optional
import argparse
from datetime import datetime
import uuid


class SimpleLegalDocumentIndexer:
    def __init__(self, es_host: str = "localhost", es_port: int = 9200):
        self.es_url = f"http://{es_host}:{es_port}"
        
        # Find the data directory - look in current directory first, then parent
        current_dir = Path(".").resolve()
        data_paths_to_check = [
            current_dir / "data",
            current_dir.parent / "data",
            Path(__file__).parent / "data"  # Same directory as script
        ]
        
        self.data_dir = None
        for data_path in data_paths_to_check:
            if data_path.exists() and (data_path / "gesetze").exists():
                self.data_dir = data_path
                break
                
        if self.data_dir is None:
            # Fallback to original behavior
            self.data_dir = Path("data")
        
    def ensure_index_exists(self, index_name: str):
        """Create index if it doesn't exist with appropriate mapping"""
        # Check if index exists
        response = requests.head(f"{self.es_url}/{index_name}")
        
        if response.status_code == 404:
            # Index doesn't exist, create it
            mapping = {
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                    "analysis": {
                        "analyzer": {
                            "german": {
                                "type": "standard",
                                "stopwords": "_german_"
                            }
                        }
                    }
                },
                "mappings": {
                    "properties": {
                        "title": {"type": "text", "analyzer": "german"},
                        "content": {"type": "text", "analyzer": "german"},
                        "jurabk": {"type": "keyword"},
                        "slug": {"type": "keyword"},
                        "document_type": {"type": "keyword"},
                        "file_path": {"type": "keyword"},
                        "date": {"type": "date", "format": "yyyy-MM-dd||epoch_millis"},
                        "fundstelle": {"type": "text"},
                        "court": {"type": "text"},
                        "case_number": {"type": "keyword"},
                        "year": {"type": "integer"},
                        "indexed_at": {"type": "date"}
                    }
                }
            }
            
            response = requests.put(f"{self.es_url}/{index_name}", json=mapping)
            if response.status_code == 200:
                print(f"Created index: {index_name}")
            else:
                print(f"Error creating index: {response.status_code} - {response.text}")
        else:
            print(f"Index {index_name} already exists")

    def parse_frontmatter(self, content: str) -> tuple[Dict[str, Any], str]:
        """Parse YAML frontmatter from markdown content"""
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                frontmatter_text = parts[1].strip()
                remaining_content = parts[2].strip()
                
                # Parse YAML-like frontmatter manually for simple cases
                frontmatter = {}
                for line in frontmatter_text.split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        frontmatter[key.strip()] = value.strip()
                
                return frontmatter, remaining_content
        return {}, content

    def parse_json_frontmatter(self, content: str) -> tuple[Dict[str, Any], str]:
        """Parse JSON frontmatter from markdown content"""
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                frontmatter_text = parts[1].strip()
                remaining_content = parts[2].strip()
                
                try:
                    frontmatter = json.loads(frontmatter_text)
                    return frontmatter, remaining_content
                except json.JSONDecodeError:
                    pass
        return {}, content

    def extract_title_from_content(self, content: str) -> Optional[str]:
        """Extract title from markdown content"""
        lines = content.split('\n')
        for line in lines:
            if line.strip().startswith('# '):
                return line.strip()[2:].strip()
        return None

    def extract_date_from_content(self, content: str) -> Optional[str]:
        """Extract date from content"""
        # Look for date patterns like "Ausfertigungsdatum: 2002-02-15"
        date_pattern = r'Ausfertigungsdatum\s*:?\s*(\d{4}-\d{2}-\d{2})'
        match = re.search(date_pattern, content)
        if match:
            return match.group(1)
        return None

    def process_gesetz_document(self, file_path: Path) -> Dict[str, Any]:
        """Process a Gesetz (law) document"""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        frontmatter, main_content = self.parse_frontmatter(content)
        
        # Extract title from frontmatter or content
        title = frontmatter.get('Title') or frontmatter.get('title')
        if not title:
            title = self.extract_title_from_content(main_content)
        
        # Extract date
        date_str = self.extract_date_from_content(main_content)
        
        doc = {
            "title": title or str(file_path.parent.name).upper(),
            "content": main_content,
            "document_type": "gesetz",
            "file_path": str(file_path),
            "jurabk": frontmatter.get('jurabk', ''),
            "slug": frontmatter.get('slug', ''),
            "date": date_str,
            "indexed_at": datetime.now().isoformat()
        }
        
        # Extract Fundstelle
        fundstelle_match = re.search(r'Fundstelle\s*:?\s*(.+)', main_content)
        if fundstelle_match:
            doc["fundstelle"] = fundstelle_match.group(1).strip()
        
        return doc

    def process_urteil_document(self, file_path: Path) -> List[Dict[str, Any]]:
        """Process a Urteil (court decision) document which may contain multiple cases"""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        frontmatter, main_content = self.parse_json_frontmatter(content)
        
        year = frontmatter.get('year')
        if not year:
            # Extract year from filename
            year_match = re.search(r'(\d{4})', file_path.stem)
            if year_match:
                year = int(year_match.group(1))
        
        documents = []
        
        # Method 1: Split by standard case numbers (### pattern)
        # Track line numbers by splitting content into lines first
        all_lines = content.split('\n')
        
        # Find case boundaries and their line numbers
        case_starts = []
        for line_num, line in enumerate(all_lines):
            if re.match(r'###\s+([^/\n]+/\d+)', line):
                case_match = re.search(r'###\s+([^/\n]+/\d+)', line)
                if case_match:
                    case_starts.append({
                        'line_num': line_num + 1,  # 1-indexed
                        'case_number': case_match.group(1).strip()
                    })
        
        standard_cases = re.split(r'\n###\s+([^/\n]+/\d+)', main_content)
        
        if len(standard_cases) > 1:
            # Process standard format cases
            for i in range(1, len(standard_cases), 2):
                if i + 1 < len(standard_cases):
                    case_number = standard_cases[i].strip()
                    case_content = standard_cases[i + 1].strip()
                    
                    # Find the starting line number for this case
                    content_start_line = None
                    for case_start in case_starts:
                        if case_start['case_number'] == case_number:
                            content_start_line = case_start['line_num']
                            break
                    
                    # Further split this content to handle BGH cases within
                    bgf_docs = self.extract_bgf_cases_from_content(case_content, str(file_path), year)
                    if bgf_docs:
                        documents.extend(bgf_docs)
                    else:
                        # Standard case processing
                        first_line = case_content.split('\n')[0] if case_content else ""
                        court_match = re.search(r'Urteil \| ([^|]+) \|', first_line)
                        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', first_line)
                        
                        doc = {
                            "title": f"Urteil {case_number}",
                            "content": case_content,
                            "document_type": "urteil",
                            "file_path": str(file_path),
                            "case_number": case_number,
                            "court": court_match.group(1).strip() if court_match else "",
                            "date": date_match.group(1) if date_match else None,
                            "year": year,
                            "content_start_line": content_start_line,
                            "indexed_at": datetime.now().isoformat()
                        }
                        documents.append(doc)
        else:
            # Method 2: Look for BGH cases and other patterns in the whole content
            bgf_docs = self.extract_bgf_cases_from_content(main_content, str(file_path), year)
            if bgf_docs:
                documents.extend(bgf_docs)
            else:
                # Single document fallback (for per-decision Markdown files)
                title_fallback = self.extract_title_from_content(main_content) or file_path.stem
                doc = {
                    "title": title_fallback,
                    "content": main_content,
                    "document_type": "urteil",
                    "file_path": str(file_path),
                    "year": year,
                    "content_start_line": 1,  # Starts at line 1 for whole file
                    "indexed_at": datetime.now().isoformat()
                }
                documents.append(doc)
        
        return documents
    
    def extract_bgf_cases_from_content(self, content: str, file_path: str, year: int) -> List[Dict[str, Any]]:
        """Extract BGH and other special case formats from content"""
        documents = []
        
        # Split content into lines to track line numbers
        all_lines = content.split('\n')
        
        # Pattern 1: BGH cases with summary lines like "Der auftragsgemäße Entwurf..."
        # Look for lines that are summaries followed by "Tenor"
        summary_pattern = r'^([^.\n]{50,200}(?:Testament|Gebühr|BGH|Revision)[^.\n]*\.?)$\s*^\s*Tenor\s*$'
        summary_matches = list(re.finditer(summary_pattern, content, re.MULTILINE | re.IGNORECASE))
        
        if summary_matches:
            for i, match in enumerate(summary_matches):
                summary_text = match.group(1).strip()
                start_pos = match.start()
                
                # Find the end of this case (next summary or end of content)
                if i + 1 < len(summary_matches):
                    end_pos = summary_matches[i + 1].start()
                else:
                    end_pos = len(content)
                
                case_content = content[start_pos:end_pos].strip()
                
                # Calculate the starting line number in the original file
                content_before_match = content[:start_pos]
                start_line = content_before_match.count('\n') + 1
                
                # Extract case number from content if available
                case_number_match = re.search(r'(IX|VIII|VII|VI|V|IV|III|II|I)\s+(ZR|AR|BR)\s+(\d+/\d+)', case_content)
                case_number = case_number_match.group(0) if case_number_match else f"BGH-{i+1}"
                
                # Extract court info
                court = "BGH" if "BGH" in case_content or "Bundesgerichtshof" in case_content else "Unbekanntes Gericht"
                
                # Extract date
                date_match = re.search(r'(\d{1,2})\.\s*(\w+)\s+(\d{4})', case_content)
                date_str = None
                if date_match:
                    try:
                        month_names = {
                            'Januar': '01', 'Februar': '02', 'März': '03', 'April': '04',
                            'Mai': '05', 'Juni': '06', 'Juli': '07', 'August': '08',
                            'September': '09', 'Oktober': '10', 'November': '11', 'Dezember': '12'
                        }
                        day = date_match.group(1).zfill(2)
                        month_name = date_match.group(2)
                        year_str = date_match.group(3)
                        if month_name in month_names:
                            date_str = f"{year_str}-{month_names[month_name]}-{day}"
                    except:
                        pass
                
                doc = {
                    "title": summary_text[:100] + "..." if len(summary_text) > 100 else summary_text,
                    "content": case_content,
                    "document_type": "urteil",
                    "file_path": file_path,
                    "case_number": case_number,
                    "court": court,
                    "date": date_str,
                    "year": year,
                    "content_start_line": start_line,  # Store original line offset
                    "indexed_at": datetime.now().isoformat()
                }
                documents.append(doc)
        
        # Pattern 2: Look for other case patterns (e.g., Roman numeral decisions)
        if not documents:
            # Split by major sections that might indicate separate cases
            section_patterns = [
                r'\n(?=Tenor\s*\n)',  # Split at "Tenor"
                r'\n(?=Von Rechts wegen\s*\n)',  # Split at "Von Rechts wegen"  
                r'\n(?=Tatbestand\s*\n)',  # Split at "Tatbestand"
                r'\n(?=Entscheidungsgründe\s*\n)'  # Split at "Entscheidungsgründe"
            ]
            
            for pattern in section_patterns:
                sections = re.split(pattern, content)
                if len(sections) > 2:  # Found meaningful splits
                    for j, section in enumerate(sections):
                        if len(section.strip()) > 500:  # Only process substantial content
                            # Look for key legal terms to determine if this is worth indexing
                            key_terms = ['Testament', 'Gebühr', 'Urteil', 'Beschluss', 'Revision']
                            if any(term in section for term in key_terms):
                                title = self.extract_case_title_from_content(section)
                                
                                # Calculate approximate line offset for this section
                                section_start_pos = content.find(section)
                                content_before_section = content[:section_start_pos] if section_start_pos >= 0 else ""
                                section_start_line = content_before_section.count('\n') + 1
                                
                                doc = {
                                    "title": title or f"Rechtsentscheidung {j+1}",
                                    "content": section.strip(),
                                    "document_type": "urteil",
                                    "file_path": file_path,
                                    "case_number": f"Section-{j+1}",
                                    "court": self.extract_court_from_content(section),
                                    "date": self.extract_date_from_content(section),
                                    "year": year,
                                    "content_start_line": section_start_line,
                                    "indexed_at": datetime.now().isoformat()
                                }
                                documents.append(doc)
                    break  # Use first successful pattern
        
        return documents
    
    def extract_case_title_from_content(self, content: str) -> Optional[str]:
        """Extract a meaningful title from case content"""
        lines = content.strip().split('\n')[:10]  # Check first 10 lines
        
        for line in lines:
            line = line.strip()
            # Skip empty lines, numbers, and formatting
            if not line or line.isdigit() or len(line) < 20:
                continue
            # Look for lines that seem like titles or summaries
            if any(word in line for word in ['Testament', 'Gebühr', 'auftragsgemäße', 'Entwurf']):
                return line[:150] + "..." if len(line) > 150 else line
                
        return None
    
    def extract_court_from_content(self, content: str) -> str:
        """Extract court name from content"""
        court_patterns = [
            r'BGH|Bundesgerichtshof',
            r'OLG\s+\w+|Oberlandesgericht\s+\w+', 
            r'LG\s+\w+|Landgericht\s+\w+',
            r'AG\s+\w+|Amtsgericht\s+\w+'
        ]
        
        for pattern in court_patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return match.group(0)
        
        return "Unbekanntes Gericht"
    
    def extract_date_from_content(self, content: str) -> Optional[str]:
        """Extract date from content - reuse existing method"""
        # Look for date patterns like "Ausfertigungsdatum: 2002-02-15"
        date_pattern = r'Ausfertigungsdatum\s*:?\s*(\d{4}-\d{2}-\d{2})'
        match = re.search(date_pattern, content)
        if match:
            return match.group(1)
        
        # Look for German date format "12. Februar 2018"
        german_date_match = re.search(r'(\d{1,2})\.\s*(\w+)\s+(\d{4})', content)
        if german_date_match:
            try:
                month_names = {
                    'Januar': '01', 'Februar': '02', 'März': '03', 'April': '04',
                    'Mai': '05', 'Juni': '06', 'Juli': '07', 'August': '08',
                    'September': '09', 'Oktober': '10', 'November': '11', 'Dezember': '12'
                }
                day = german_date_match.group(1).zfill(2)
                month_name = german_date_match.group(2)
                year_str = german_date_match.group(3)
                if month_name in month_names:
                    return f"{year_str}-{month_names[month_name]}-{day}"
            except:
                pass
        
        return None

    def bulk_index_documents(self, documents: List[Dict[str, Any]], index_name: str):
        """Bulk index documents to Elasticsearch using requests"""
        if not documents:
            return
            
        # Prepare bulk request body
        bulk_body = []
        for doc in documents:
            # Index action
            bulk_body.append(json.dumps({"index": {"_index": index_name, "_id": str(uuid.uuid4())}}))
            # Document
            bulk_body.append(json.dumps(doc))
        
        bulk_data = '\n'.join(bulk_body) + '\n'
        
        # Debug: Print request size
        request_size_mb = len(bulk_data.encode('utf-8')) / (1024 * 1024)
        print(f"Bulk request size: {request_size_mb:.2f} MB ({len(documents)} docs)")
        
        response = requests.post(
            f"{self.es_url}/_bulk",
            data=bulk_data,
            headers={'Content-Type': 'application/json'}
        )
        
        if response.status_code == 200:
            result = response.json()
            if 'errors' in result and result['errors']:
                print(f"Some errors occurred during bulk indexing")
                for item in result['items']:
                    if 'index' in item and 'error' in item['index']:
                        print(f"Error: {item['index']['error']}")
            else:
                print(f"Successfully indexed {len(documents)} documents to {index_name}")
        else:
            print(f"Error bulk indexing: {response.status_code} - {response.text}")

    def index_gesetze(self, index_name: str = "legal_gesetze"):
        """Index all Gesetze documents"""
        self.ensure_index_exists(index_name)
        
        gesetze_dir = self.data_dir / "gesetze"
        if not gesetze_dir.exists():
            print(f"❌ Gesetze directory not found: {gesetze_dir}")
            print(f"   Current working directory: {os.getcwd()}")
            print(f"   Looking for directory: {gesetze_dir.absolute()}")
            return
        
        documents = []
        processed_count = 0
        
        print(f"Processing Gesetze from {gesetze_dir}...")
        
        # Walk through all subdirectories
        for root, dirs, files in os.walk(gesetze_dir):
            for file in files:
                if file == "index.md":
                    file_path = Path(root) / file
                    try:
                        doc = self.process_gesetz_document(file_path)
                        documents.append(doc)
                        processed_count += 1
                        
                        # Index in batches
                        if len(documents) >= 50:
                            self.bulk_index_documents(documents, index_name)
                            documents = []
                        
                        if processed_count % 100 == 0:
                            print(f"Processed {processed_count} Gesetze documents...")
                            
                    except Exception as e:
                        print(f"Error processing {file_path}: {e}")
        
        # Index remaining documents
        if documents:
            self.bulk_index_documents(documents, index_name)
        
        print(f"Finished processing {processed_count} Gesetze documents")

    def index_urteile(self, index_name: str = "legal_urteile"):
        """Index all Urteile documents"""
        self.ensure_index_exists(index_name)
        
        urteile_dir = self.data_dir / "urteile_markdown_by_year"
        if not urteile_dir.exists():
            print(f"❌ Urteile directory not found: {urteile_dir}")
            print(f"   Current working directory: {os.getcwd()}")
            print(f"   Looking for directory: {urteile_dir.absolute()}")
            return
        
        all_documents = []
        processed_files = 0
        
        print(f"Processing Urteile from {urteile_dir}...")
        
        # Recursively process year folders and per-decision files
        for root, dirs, files in os.walk(urteile_dir):
            for fn in files:
                if not fn.endswith('.md'):
                    continue
                if fn == 'index.md':
                    continue
                file_path = Path(root) / fn
                try:
                    documents = self.process_urteil_document(file_path)
                    processed_files += 1
                    # Index documents in small batches to avoid large requests
                    batch_size = 50
                    for i in range(0, len(documents), batch_size):
                        batch = documents[i:i+batch_size]
                        self.bulk_index_documents(batch, index_name)
                    print(f"Processed {file_path} - extracted {len(documents)} cases")
                except Exception as e:
                    print(f"Error processing {file_path}: {e}")
        
        # Index remaining documents
        if all_documents:
            self.bulk_index_documents(all_documents, index_name)
        
        print(f"Finished processing {processed_files} Urteile files")

    def index_all(self):
        """Index all documents"""
        print("Starting full indexing of legal documents...")
        print("\n" + "="*50)
        print("STEP 1: Indexing Gesetze (Laws and Regulations)")
        print("="*50)
        try:
            self.index_gesetze()
            print("✓ Gesetze indexing completed successfully")
        except Exception as e:
            print(f"✗ Error indexing Gesetze: {e}")
            
        print("\n" + "="*50)
        print("STEP 2: Indexing Urteile (Court Decisions)")
        print("="*50)
        try:
            self.index_urteile()
            print("✓ Urteile indexing completed successfully")
        except Exception as e:
            print(f"✗ Error indexing Urteile: {e}")
            
        print("\n" + "="*50)
        print("INDEXING COMPLETE!")
        print("="*50)
        self.get_index_stats('legal_gesetze')
        self.get_index_stats('legal_urteile')

    def get_index_stats(self, index_name: str):
        """Get statistics about an index"""
        response = requests.get(f"{self.es_url}/{index_name}/_stats")
        if response.status_code == 200:
            stats = response.json()
            if 'indices' in stats and index_name in stats['indices']:
                index_stats = stats['indices'][index_name]
                doc_count = index_stats['total']['docs']['count']
                size_bytes = index_stats['total']['store']['size_in_bytes']
                print(f"Index {index_name}: {doc_count} documents, {size_bytes / 1024 / 1024:.2f} MB")
            else:
                print(f"No stats available for {index_name}")
        else:
            print(f"Error getting stats for {index_name}: {response.status_code}")

    def find_line_numbers(self, content: str, search_terms: List[str], original_file_path: str = None, content_start_line: int = None) -> List[Dict[str, Any]]:
        """Find line numbers where search terms appear"""
        lines = content.split('\n')
        matches = []
        
        for line_num, line in enumerate(lines, 1):
            line_lower = line.lower()
            found_terms = []
            
            for term in search_terms:
                if term.lower() in line_lower:
                    found_terms.append(term)
            
            if found_terms:
                # Calculate actual file line number if we have the offset
                actual_line_num = line_num
                if content_start_line is not None:
                    actual_line_num = content_start_line + line_num - 1
                
                matches.append({
                    'line_number': actual_line_num,
                    'line_content': line.strip(),
                    'matched_terms': found_terms
                })
        
        return matches

    def search(self, index_name: str, keywords: List[str], size: int = 10):
        """Search for documents containing all keywords"""
        # Build query for documents containing all keywords
        must_queries = []
        for keyword in keywords:
            # Check if this is a phrase (contains multiple words)
            if len(keyword.split()) > 1:
                # Use phrase query for multi-word terms
                must_queries.append({
                    "multi_match": {
                        "query": keyword,
                        "fields": ["title^2", "content"],
                        "type": "phrase"
                    }
                })
            else:
                # Use regular match for single words
                must_queries.append({
                    "multi_match": {
                        "query": keyword,
                        "fields": ["title^2", "content"],
                        "type": "best_fields"
                    }
                })
        
        query = {
            "query": {
                "bool": {
                    "must": must_queries
                }
            },
            "highlight": {
                "fields": {
                    "title": {},
                    "content": {
                        "fragment_size": 200,
                        "max_analyzed_offset": 500000  # Limit highlighting for large docs
                    }
                },
                "max_analyzed_offset": 500000
            },
            "size": size
        }
        
        response = requests.post(
            f"{self.es_url}/{index_name}/_search",
            json=query,
            headers={'Content-Type': 'application/json'}
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Search error: {response.status_code} - {response.text}")
            return None


def main():
    parser = argparse.ArgumentParser(description='Index legal documents into Elasticsearch')
    parser.add_argument('--host', default='localhost', help='Elasticsearch host')
    parser.add_argument('--port', type=int, default=9200, help='Elasticsearch port')
    parser.add_argument('--gesetze-only', action='store_true', help='Index only Gesetze documents')
    parser.add_argument('--urteile-only', action='store_true', help='Index only Urteile documents')
    parser.add_argument('--stats', action='store_true', help='Show index statistics')
    parser.add_argument('--search', nargs='+', help='Search for keywords')
    parser.add_argument('--index', default='legal_gesetze,legal_urteile', help='Index to search in (can be comma-separated)')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    
    args = parser.parse_args()
    
    indexer = SimpleLegalDocumentIndexer(args.host, args.port)
    
    if args.debug:
        print(f"🔍 DEBUG: Current working directory: {os.getcwd()}")
        print(f"🔍 DEBUG: Data directory: {indexer.data_dir.absolute()}")
        print(f"🔍 DEBUG: Gesetze directory exists: {(indexer.data_dir / 'gesetze').exists()}")
        print(f"🔍 DEBUG: Urteile directory exists: {(indexer.data_dir / 'urteile_markdown_by_year').exists()}")
        print(f"🔍 DEBUG: Elasticsearch URL: {indexer.es_url}")
        print("🔍 DEBUG: Arguments:", vars(args))
    
    if args.search:
        # Adjust search index based on flags
        search_index = args.index
        if args.urteile_only:
            search_index = 'legal_urteile'
        elif args.gesetze_only:
            search_index = 'legal_gesetze'
            
        print(f"Searching for keywords: {args.search}")
        results = indexer.search(search_index, args.search)
        if results:
            hits = results.get('hits', {}).get('hits', [])
            print(f"Found {results['hits']['total']['value']} results:")
            for hit in hits:
                source = hit['_source']
                print(f"\nTitle: {source['title']}")
                print(f"Type: {source['document_type']}")
                print(f"File: {source.get('file_path', 'N/A')}")
                print(f"Score: {hit['_score']}")
                
                # Find line numbers where keywords appear
                content = source.get('content', '')
                if content:
                    # Get the line offset if available
                    content_start_line = source.get('content_start_line', None)
                    line_matches = indexer.find_line_numbers(content, args.search, source.get('file_path'), content_start_line)
                    if line_matches:
                        print("Matches found at:")
                        for match in line_matches[:3]:  # Show first 3 matches
                            line_content = match['line_content'][:100] + ('...' if len(match['line_content']) > 100 else '')
                            terms_str = ', '.join(match['matched_terms'])
                            print(f"  Line {match['line_number']} ({terms_str}): {line_content}")
                
                # Show highlights
                if 'highlight' in hit:
                    for field, highlights in hit['highlight'].items():
                        print(f"{field}: {highlights[0]}")
                
                print("-" * 50)
    elif args.stats:
        indexer.get_index_stats('legal_gesetze')
        indexer.get_index_stats('legal_urteile')
    elif args.gesetze_only:
        indexer.index_gesetze()
    elif args.urteile_only:
        indexer.index_urteile()
    else:
        indexer.index_all()


if __name__ == "__main__":
    main()

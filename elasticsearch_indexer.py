#!/usr/bin/env python3
"""
Elasticsearch indexer for legal documents

This script indexes all documents from the data folder into Elasticsearch,
supporting both Gesetze (laws) and Urteile (court decisions).
"""

import os
import re
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from elasticsearch import Elasticsearch, helpers
import argparse
from datetime import datetime


class LegalDocumentIndexer:
    def __init__(self, es_host: str = "localhost", es_port: int = 9200):
        self.es = Elasticsearch([f"http://{es_host}:{es_port}"], headers={"accept": "application/json", "content-type": "application/json"})
        self.data_dir = Path("data")
        
    def ensure_index_exists(self, index_name: str):
        """Create index if it doesn't exist with appropriate mapping"""
        try:
            exists = self.es.indices.exists(index=index_name)
        except Exception as e:
            print(f"Error checking if index exists: {e}")
            exists = False
            
        if not exists:
            mapping = {
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
                },
                "settings": {
                    "analysis": {
                        "analyzer": {
                            "german": {
                                "type": "standard",
                                "stopwords": "_german_"
                            }
                        }
                    }
                }
            }
            
            try:
                self.es.indices.create(index=index_name, body=mapping)
                print(f"Created index: {index_name}")
            except Exception as e:
                print(f"Error creating index: {e}")
                # Try with simpler approach
                self.es.indices.create(index=index_name)
                print(f"Created index with default settings: {index_name}")
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
        
        # Split content by case numbers (pattern like "### 13 S 50/70")
        cases = re.split(r'\n###\s+([^/\n]+/\d+)', main_content)
        
        documents = []
        
        if len(cases) > 1:
            # Process individual cases
            for i in range(1, len(cases), 2):
                if i + 1 < len(cases):
                    case_number = cases[i].strip()
                    case_content = cases[i + 1].strip()
                    
                    # Extract court and date info from the first line
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
                        "indexed_at": datetime.now().isoformat()
                    }
                    documents.append(doc)
        else:
            # Single document
            doc = {
                "title": f"Entscheidungen {year}",
                "content": main_content,
                "document_type": "urteil",
                "file_path": str(file_path),
                "year": year,
                "indexed_at": datetime.now().isoformat()
            }
            documents.append(doc)
        
        return documents

    def index_documents(self, documents: List[Dict[str, Any]], index_name: str):
        """Bulk index documents to Elasticsearch"""
        actions = []
        for doc in documents:
            action = {
                "_index": index_name,
                "_source": doc
            }
            actions.append(action)
        
        if actions:
            helpers.bulk(self.es, actions, chunk_size=100, request_timeout=60)
            print(f"Indexed {len(actions)} documents to {index_name}")

    def index_gesetze(self, index_name: str = "legal_gesetze"):
        """Index all Gesetze documents"""
        self.ensure_index_exists(index_name)
        
        gesetze_dir = self.data_dir / "gesetze"
        if not gesetze_dir.exists():
            print(f"Gesetze directory not found: {gesetze_dir}")
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
                        if len(documents) >= 100:
                            self.index_documents(documents, index_name)
                            documents = []
                        
                        if processed_count % 100 == 0:
                            print(f"Processed {processed_count} Gesetze documents...")
                            
                    except Exception as e:
                        print(f"Error processing {file_path}: {e}")
        
        # Index remaining documents
        if documents:
            self.index_documents(documents, index_name)
        
        print(f"Finished processing {processed_count} Gesetze documents")

    def index_urteile(self, index_name: str = "legal_urteile"):
        """Index all Urteile documents"""
        self.ensure_index_exists(index_name)
        
        urteile_dir = self.data_dir / "urteile_markdown_by_year"
        if not urteile_dir.exists():
            print(f"Urteile directory not found: {urteile_dir}")
            return
        
        all_documents = []
        processed_files = 0
        
        print(f"Processing Urteile from {urteile_dir}...")
        
        # Process each year file
        for file_path in urteile_dir.glob("*.md"):
            if file_path.name == "index.md":
                continue
                
            try:
                documents = self.process_urteil_document(file_path)
                all_documents.extend(documents)
                processed_files += 1
                
                # Index in batches
                if len(all_documents) >= 100:
                    self.index_documents(all_documents, index_name)
                    all_documents = []
                
                print(f"Processed {file_path.name} - extracted {len(documents)} cases")
                
            except Exception as e:
                print(f"Error processing {file_path}: {e}")
        
        # Index remaining documents
        if all_documents:
            self.index_documents(all_documents, index_name)
        
        print(f"Finished processing {processed_files} Urteile files")

    def index_all(self):
        """Index all documents"""
        print("Starting full indexing of legal documents...")
        self.index_gesetze()
        self.index_urteile()
        print("Indexing complete!")

    def get_index_stats(self, index_name: str):
        """Get statistics about an index"""
        try:
            stats = self.es.indices.stats(index=index_name)
            doc_count = stats['indices'][index_name]['total']['docs']['count']
            size_bytes = stats['indices'][index_name]['total']['store']['size_in_bytes']
            print(f"Index {index_name}: {doc_count} documents, {size_bytes / 1024 / 1024:.2f} MB")
        except Exception as e:
            print(f"Error getting stats for {index_name}: {e}")


def main():
    parser = argparse.ArgumentParser(description='Index legal documents into Elasticsearch')
    parser.add_argument('--host', default='localhost', help='Elasticsearch host')
    parser.add_argument('--port', type=int, default=9200, help='Elasticsearch port')
    parser.add_argument('--gesetze-only', action='store_true', help='Index only Gesetze documents')
    parser.add_argument('--urteile-only', action='store_true', help='Index only Urteile documents')
    parser.add_argument('--stats', action='store_true', help='Show index statistics')
    
    args = parser.parse_args()
    
    indexer = LegalDocumentIndexer(args.host, args.port)
    
    if args.stats:
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
# Elasticsearch Migration Guide

## Overview
This guide explains how to replace the current `search_rg` function with Elasticsearch for improved search capabilities in the legal document system.

## Current State Analysis

The existing search system in `mcp_server/tools.py` uses ripgrep (`rg`) for searching documents with the following features:
- Boolean queries (AND/OR operations)
- Context lines around matches
- File path filtering
- Regex and literal string search
- Case sensitive/insensitive search
- Result highlighting

## Benefits of Elasticsearch Migration

### Performance Improvements
- **Indexing**: Pre-indexed documents enable much faster searches compared to file system searches
- **Scalability**: Better handling of large document collections (current: 6,636+ Gesetze documents)
- **Caching**: Built-in result caching and optimization
- **Memory Usage**: More efficient memory usage for large search operations

### Enhanced Search Capabilities
- **Full-text search**: Advanced text analysis with German language support
- **Fuzzy matching**: Handle typos and variations in legal terminology
- **Relevance scoring**: Better ranking of search results
- **Aggregations**: Statistics and faceting on document types, dates, courts, etc.
- **Complex queries**: More sophisticated boolean logic and field-specific searches

### Legal Document Specific Features
- **Document structure awareness**: Search within specific document sections (titles, content, metadata)
- **Date range filtering**: Search by publication dates, court decision dates
- **Court and document type filtering**: Filter by specific courts or document types
- **Case number search**: Exact matching on legal case numbers

## Implementation Plan

### Phase 1: Setup and Basic Functionality
1. **Elasticsearch Installation** ✅ Complete
2. **Document Indexing Script** ✅ Complete
3. **Basic Search Function** ✅ Complete

### Phase 2: API Integration
1. Replace `search_rg` function with Elasticsearch equivalent
2. Maintain backward compatibility for existing API consumers
3. Add new search parameters for enhanced features

### Phase 3: Enhanced Features
1. Add aggregations and filtering capabilities
2. Implement search suggestions/autocomplete
3. Add search analytics and logging

## Detailed Implementation

### 1. New Elasticsearch Search Function

Create `elasticsearch_search.py` to replace `search_rg`:

```python
def search_elasticsearch(
    query: str,
    indices: List[str] = ["legal_gesetze", "legal_urteile"],
    max_results: int = 20,
    context_lines: int = 2,
    document_types: List[str] = None,
    date_range: Dict[str, str] = None,
    courts: List[str] = None,
    case_sensitive: bool = False,
    fuzzy: bool = False
) -> dict:
    """
    Search legal documents using Elasticsearch
    
    Parameters:
    - query: Search query (supports boolean operators AND, OR)
    - indices: Elasticsearch indices to search
    - max_results: Maximum number of results
    - context_lines: Lines of context around matches
    - document_types: Filter by document types (gesetz, urteil)
    - date_range: Filter by date range {"from": "2020-01-01", "to": "2023-12-31"}
    - courts: Filter by specific courts
    - case_sensitive: Case sensitive search
    - fuzzy: Enable fuzzy matching for typos
    
    Returns: Compatible format with existing search_rg function
    """
```

### 2. Query Translation

Map existing search patterns to Elasticsearch queries:

| Current search_rg | Elasticsearch equivalent |
|------------------|-------------------------|
| `"term1 OR term2"` | `{"bool": {"should": [{"match": {"content": "term1"}}, {"match": {"content": "term2"}}]}}` |
| `"term1 term2"` (AND) | `{"bool": {"must": [{"match": {"content": "term1"}}, {"match": {"content": "term2"}}]}}` |
| Regex patterns | `{"regexp": {"content": "pattern"}}` |
| File path filtering | `{"term": {"file_path": "path"}}` |

### 3. Result Format Compatibility

Ensure the Elasticsearch search function returns results in the same format as `search_rg`:

```python
{
    "matches": [
        {
            "file": "relative/path/to/file.md",
            "line": 42,
            "text": "highlighted text with **matches**",
            "context": [
                {"line": 40, "text": "context before"},
                {"line": 41, "text": "context before"},
                {"line": 42, "text": "matching line"},
                {"line": 43, "text": "context after"},
                {"line": 44, "text": "context after"}
            ],
            "section": "# Document Section Header",
            "byte_range": [1234, 1289]
        }
    ]
}
```

### 4. Configuration Updates

Update `mcp_server/tools.py` to use Elasticsearch:

```python
# Add to Config class
class Config:
    def __init__(self, path: Path | None = None):
        # Existing config...
        self.elasticsearch_host = "localhost"
        self.elasticsearch_port = 9200
        self.use_elasticsearch = False  # Feature flag for gradual migration
        
        # Load from config file
        if path and path.exists():
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            # ... existing config loading
            self.elasticsearch_host = data.get("elasticsearch_host", self.elasticsearch_host)
            self.elasticsearch_port = data.get("elasticsearch_port", self.elasticsearch_port)
            self.use_elasticsearch = data.get("use_elasticsearch", self.use_elasticsearch)
```

### 5. Migration Strategy

#### Option A: Drop-in Replacement
```python
def search_rg(*args, **kwargs):
    """Backward compatible search function"""
    if _config.use_elasticsearch:
        return search_elasticsearch(*args, **kwargs)
    else:
        return _original_search_rg(*args, **kwargs)
```

#### Option B: Gradual Migration
```python
def search_documents(*args, **kwargs):
    """New unified search interface"""
    return search_elasticsearch(*args, **kwargs)

# Keep original search_rg for compatibility
def search_rg(*args, **kwargs):
    """Legacy search function - deprecated"""
    return _original_search_rg(*args, **kwargs)
```

### 6. Enhanced Search Features

#### Multi-field Search
```python
# Search across title, content, and metadata
{
    "multi_match": {
        "query": "Beitragssätze",
        "fields": ["title^2", "content", "jurabk", "fundstelle"],
        "type": "best_fields"
    }
}
```

#### Date Range Filtering
```python
# Search documents from specific time period
{
    "bool": {
        "must": [
            {"match": {"content": "Rentenversicherung"}},
            {"range": {"date": {"gte": "2020-01-01", "lte": "2023-12-31"}}}
        ]
    }
}
```

#### Aggregations for Analytics
```python
# Get document counts by type and year
{
    "aggs": {
        "by_type": {
            "terms": {"field": "document_type"}
        },
        "by_year": {
            "date_histogram": {
                "field": "date",
                "calendar_interval": "year"
            }
        }
    }
}
```

## Performance Comparison

| Operation | ripgrep (current) | Elasticsearch |
|-----------|------------------|---------------|
| Initial search (cold) | ~2-5 seconds | ~50-200ms |
| Repeated search | ~1-3 seconds | ~10-50ms |
| Complex boolean queries | ~5-10 seconds | ~100-500ms |
| Large result sets | Memory intensive | Paginated, efficient |
| Concurrent searches | Limited by file I/O | Highly concurrent |

## Migration Steps

### Step 1: Index All Documents
```bash
# Index all legal documents
python simple_elasticsearch_indexer.py

# Verify indexing
python simple_elasticsearch_indexer.py --stats
```

### Step 2: Update Configuration
```yaml
# config.yaml
use_elasticsearch: true
elasticsearch_host: localhost
elasticsearch_port: 9200
```

### Step 3: Deploy New Search Function
Replace the search implementation in `mcp_server/tools.py`

### Step 4: Testing
```python
# Test equivalent searches
rg_result = search_rg("Beitragssätze Rentenversicherung")
es_result = search_elasticsearch("Beitragssätze Rentenversicherung")

# Compare results and performance
```

### Step 5: Monitor and Optimize
- Monitor search performance
- Adjust Elasticsearch settings based on usage patterns  
- Update index mappings if needed

## Advanced Features to Consider

### 1. Search Suggestions
Implement autocomplete for legal terms and case numbers.

### 2. Semantic Search
Use Elasticsearch's vector search capabilities for semantic matching.

### 3. Search Analytics
Track search queries and results to improve the system.

### 4. Multi-language Support
Extend beyond German documents if needed.

### 5. Document Versioning
Handle updates to legal documents over time.

## Maintenance Considerations

### Index Updates
- Set up automated reindexing when documents change
- Implement incremental updates for new documents
- Monitor index size and performance

### Backup and Recovery
- Regular Elasticsearch backups
- Document recovery procedures
- Index recreation scripts

### Monitoring
- Search performance metrics
- Index health monitoring  
- Error logging and alerting

## Conclusion

Migrating from ripgrep to Elasticsearch will provide significant improvements in search performance, capabilities, and user experience. The migration can be done gradually with proper feature flagging to ensure system stability during the transition.

The enhanced search capabilities will enable more sophisticated legal research workflows and better support for the large document collection in the system.
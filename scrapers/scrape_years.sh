#!/usr/bin/env bash
set -euo pipefail

# Scrape NEURIS decisions year by year and print per-year counts saved by the scraper.
# Usage: ./scripts/scrape_years.sh [START_YEAR] [END_YEAR]
# Defaults: 2010 2025

START_YEAR="${1:-2010}"
END_YEAR="${2:-2025}"

# Ensure we are in the project root (this script assumes paths relative to repo root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$REPO_ROOT"

# Function to run a single year and extract the saved count from scraper output
run_year() {
  local year="$1"
  local from="${year}-01-01"
  local to="${year}-12-31"

  # Run the scraper; capture stdout+stderr
  # We rely on the final line: "Completed. Total decisions saved: <N>"
  local out
  if ! out=$(python3 scrapers/fetch_neuris_urteile_from_xml.py --date-from "$from" --date-to "$to" 2>&1); then
    echo "${year} 0"  # On failure, print zero
    return 0
  fi

  # Extract the last occurrence of the completion line and print YEAR COUNT
  local count
  count=$(echo "$out" | grep -oE "Completed\. Total decisions saved: [0-9]+" | tail -n1 | grep -oE "[0-9]+" || true)
  if [[ -z "${count:-}" ]]; then
    # Fallback: try counting lines that start with "Saved:" for this run
    count=$(echo "$out" | grep -c "^.*Saved: ")
  fi
  echo "${year} ${count}"
}

# Loop through years
for ((y=START_YEAR; y<=END_YEAR; y++)); do
  run_year "$y"
done

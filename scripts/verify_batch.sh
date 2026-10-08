#!/usr/bin/env bash
# Real-world verification set (results/*.json are event dumps; reruns are free from cache).
set -u
cd "$(dirname "$0")/.."
run() { echo "=== $1 | $2 | $3"; uv run python -m scripts.check "$1" "$2" "$3" --json "results/$4.json" 2>&1 \
  | grep -E "1 credit|\"label\"|CALL INSTEAD|WARNED|SUMMARY|official:|credits:|notice" | cut -c1-400; }
run "DTDC" "+91 9606 911 811" "Delhi" dtdc
run "State Bank of India" "1800 1234" "Mumbai" sbi
run "Airtel" "6290133964" "Kolkata" airtel
run "Amazon" "+91 80 6605 5000" "Bengaluru" amazon
run "Blue Dart" "07016493282" "Delhi" bluedart_techenclave
run "Blue Dart" "6291610240" "Delhi" bluedart
run "Blue Dart" "1860 233 1234" "Delhi" bluedart_official
run "HDFC Bank" "" "Mumbai" hdfc
run "IRCTC" "09002327947" "Delhi" irctc
run "IRCTC" "14646" "Delhi" irctc_14646

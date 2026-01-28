#!/bin/bash

# Script to review all commits not in master
# Usage: ./review_commits.sh [output_file]

OUTPUT_FILE="${1:-review_results/codex_reviews.txt}"
MASTER_BRANCH="master"

# Create output directory if it doesn't exist
mkdir -p "$(dirname "$OUTPUT_FILE")"

# Clear the output file
echo "Codex Code Reviews - $(date)" > "$OUTPUT_FILE"
echo "======================================" >> "$OUTPUT_FILE"
echo "" >> "$OUTPUT_FILE"

# Get all commits not in master (oldest first)
commits=$(git log $MASTER_BRANCH..HEAD --reverse --format='%H')

total=$(echo "$commits" | wc -l | tr -d ' ')
count=0

echo "Found $total commits to review"
echo "Reviews will be saved to: $OUTPUT_FILE"
echo ""

for commit in $commits; do
    count=$((count + 1))
    commit_msg=$(git log -1 --format='%s' "$commit")
    commit_short=$(git rev-parse --short "$commit")

    echo "[$count/$total] Reviewing commit $commit_short: $commit_msg"
    echo ""

    # Add commit header to output
    echo "" >> "$OUTPUT_FILE"
    echo "========================================" >> "$OUTPUT_FILE"
    echo "COMMIT $count/$total: $commit_short" >> "$OUTPUT_FILE"
    echo "Message: $commit_msg" >> "$OUTPUT_FILE"
    echo "Full SHA: $commit" >> "$OUTPUT_FILE"
    echo "========================================" >> "$OUTPUT_FILE"
    echo "" >> "$OUTPUT_FILE"

    # Run codex review and append to file
    codex review --commit "$commit" >> "$OUTPUT_FILE" 2>&1

    echo "" >> "$OUTPUT_FILE"
    echo "--- END OF REVIEW FOR COMMIT $commit_short ---" >> "$OUTPUT_FILE"
    echo "" >> "$OUTPUT_FILE"

    # Small delay to avoid rate limiting
    sleep 1
done

echo ""
echo "========================================"
echo "All reviews completed!"
echo "Output saved to: $OUTPUT_FILE"
echo "========================================"

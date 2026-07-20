#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# AISC Member Lookup
# Usage: ./scripts/lookup-member.sh "W14X30"
#        ./scripts/lookup-member.sh "HSS8X6X1/2"
#        ./scripts/lookup-member.sh "L4X4X3/8"
#        ./scripts/lookup-member.sh "C10X20"
#        ./scripts/lookup-member.sh "PIPE6STD"
#
# Searches the AISC shapes database and returns all properties.
# Designation is case-insensitive, spaces are stripped.
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DB="$SKILL_DIR/assets/aisc-shapes-database.json"

if [ $# -eq 0 ]; then
    echo "Usage: $0 <designation>"
    echo ""
    echo "Examples:"
    echo "  $0 W14X30"
    echo "  $0 HSS8X6X1/2"
    echo "  $0 L4X4X3/8"
    echo "  $0 C10X20"
    echo "  $0 PIPE6STD"
    echo ""
    echo "Search by type:"
    echo "  $0 --type W          # List all W-shapes"
    echo "  $0 --type HSS-RECT   # List all rectangular HSS"
    echo "  $0 --type L          # List all angles"
    exit 1
fi

if [ "$1" = "--type" ]; then
    TYPE="${2:-W}"
    jq -r --arg t "$TYPE" '
        [.[] | select(.type == $t)] |
        sort_by(.weight_per_ft) |
        .[] |
        "\(.designation)\t\(.weight_per_ft) plf\td=\(.d)\"\tA=\(.A) in²\tIx=\(.Ix) in⁴"
    ' "$DB" | column -t -s $'\t'
    exit 0
fi

# Normalize the query: uppercase, strip spaces
QUERY=$(echo "$1" | tr '[:lower:]' '[:upper:]' | tr -d ' ')

# Try exact match first
RESULT=$(jq -r --arg q "$QUERY" '
    .[] | select(.designation == $q) |
    if .type == "W" then
        "\(.designation) | \(.weight_per_ft) plf | d=\(.d)\" | bf=\(.bf)\" | tf=\(.tf)\" | tw=\(.tw)\" | A=\(.A) in² | Ix=\(.Ix) in⁴ | Sx=\(.Sx) in³ | Iy=\(.Iy) in⁴ | Sy=\(.Sy) in³ | ry=\(.ry)\" | Zx=\(.Zx) in³ | Zy=\(.Zy) in³"
    elif .type == "HSS-RECT" then
        "\(.designation) | \(.weight_per_ft) plf | d=\(.d)\" | b=\(.b)\" | t=\(.t)\" | A=\(.A) in² | Ix=\(.Ix) in⁴ | Sx=\(.Sx) in³ | Iy=\(.Iy) in⁴ | Sy=\(.Sy) in³"
    elif .type == "HSS-RND" then
        "\(.designation) | \(.weight_per_ft) plf | d=\(.d)\" | t=\(.t)\" | A=\(.A) in² | Ix=\(.Ix) in⁴ | Sx=\(.Sx) in³"
    elif .type == "C" then
        "\(.designation) | \(.weight_per_ft) plf | d=\(.d)\" | bf=\(.bf)\" | A=\(.A) in² | Ix=\(.Ix) in⁴ | Sx=\(.Sx) in³ | Iy=\(.Iy) in⁴ | Sy=\(.Sy) in³"
    elif .type == "L" then
        "\(.designation) | \(.weight_per_ft) plf | d=\(.d)\" | b=\(.b)\" | t=\(.t)\" | A=\(.A) in² | Ix=\(.Ix) in⁴ | Sx=\(.Sx) in³ | ry=\(.ry)\""
    elif .type == "PIPE" then
        "\(.designation) | \(.weight_per_ft) plf | d=\(.d)\" | t=\(.t)\" | A=\(.A) in² | Ix=\(.Ix) in⁴ | Sx=\(.Sx) in³"
    else
        "\(.designation) | \(.weight_per_ft) plf | A=\(.A) in²"
    end
' "$DB")

if [ -n "$RESULT" ]; then
    echo "$RESULT"
else
    # Try partial/fuzzy match
    echo "No exact match for '$QUERY'. Searching..."
    MATCHES=$(jq -r --arg q "$QUERY" '
        [.[] | select(.designation | test($q; "i"))] |
        sort_by(.weight_per_ft) |
        .[:10] |
        .[] |
        "\(.designation)\t\(.weight_per_ft) plf\t\(.type)"
    ' "$DB")

    if [ -n "$MATCHES" ]; then
        echo "Possible matches:"
        echo "$MATCHES" | column -t -s $'\t'
    else
        echo "No shapes found matching '$QUERY'"
        echo "Available types: W, HSS-RECT, HSS-RND, C, L, PIPE"
    fi
    exit 1
fi

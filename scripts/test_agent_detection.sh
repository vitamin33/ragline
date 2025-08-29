#!/bin/bash

# Test script to debug agent detection

# Determine the main repository directory
if [[ "$(basename "$(pwd)")" =~ ragline-[abc] ]]; then
    MAIN_DIR="$(cd "$(dirname "$(pwd)")/ragline" && pwd)"
else
    MAIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
fi

# Detect current agent
CURRENT_AGENT=""
DIR_NAME=$(basename "$(pwd)")
CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "")

echo "=== AGENT DETECTION TEST ==="
echo "PWD: $(pwd)"
echo "DIR_NAME: $DIR_NAME"
echo "CURRENT_BRANCH: $CURRENT_BRANCH"
echo "MAIN_DIR: $MAIN_DIR"

case "$DIR_NAME" in
    ragline-a) CURRENT_AGENT="A" ;;
    ragline-b) CURRENT_AGENT="B" ;;
    ragline-c) CURRENT_AGENT="C" ;;
    ragline)
        case "$CURRENT_BRANCH" in
            feat/core-api) CURRENT_AGENT="A" ;;
            feat/reliability) CURRENT_AGENT="B" ;;
            feat/llm) CURRENT_AGENT="C" ;;
        esac
        ;;
esac

echo "DETECTED AGENT: '$CURRENT_AGENT'"

if [ -n "$CURRENT_AGENT" ]; then
    echo "✅ Agent $CURRENT_AGENT detected - would show specific tasks"
    echo "Tasks preview:"
    awk "/## 📋 Agent $CURRENT_AGENT/,/^---$/" "$MAIN_DIR/docs/DAILY_STATUS.md" | head -5
else
    echo "❌ No agent detected - would show generic tasks"
fi

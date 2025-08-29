#!/bin/bash
# Plain text RAGline Progress Tracker

set -e

MAIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATUS_FILE="$MAIN_DIR/docs/DAILY_STATUS.md"

echo "======================================================="
echo "         RAGline Development Progress"
echo "======================================================="
echo ""

# Extract current day
current_day=$(grep "## Current Sprint:" "$STATUS_FILE" | head -1)
echo "$current_day"
echo ""

# Show progress for each agent
for agent in A B C; do
    # Extract agent section
    agent_section=$(awk "/## 📋 Agent $agent/,/^---$/" "$STATUS_FILE")

    # Count tasks
    total=$(echo "$agent_section" | grep -c "^- \[.\]")
    completed=$(echo "$agent_section" | grep -c "^- \[x\]")

    # Calculate percentage
    if [ "$total" -eq 0 ]; then
        percentage=0
    else
        percentage=$((completed * 100 / total))
    fi

    # Display agent progress
    echo "Agent $agent: $completed/$total tasks (${percentage}%)"

    # Show progress bar
    printf "["
    for ((i=0; i<20; i++)); do
        if [ $i -lt $((percentage * 20 / 100)) ]; then
            printf "#"
        else
            printf " "
        fi
    done
    printf "]\n"

    # Show blockers if any
    blocker=$(echo "$agent_section" | grep "^**Blockers:**" | sed 's/\*\*Blockers:\*\*//')
    if [ "$blocker" != " None" ] && [ -n "$blocker" ]; then
        echo "  ⚠ BLOCKED:$blocker"
    fi
    echo ""
done

# Show integration checkpoints
echo "=== Integration Checkpoints ==="
checkpoints=$(awk '/## 🔄 Integration Checkpoints/,/^---$/' "$STATUS_FILE" | grep "^|" | tail -n +3)
echo "$checkpoints" | while IFS='|' read -r time checkpoint status details; do
    if [ -n "$time" ] && [ "$time" != "Time" ]; then
        status_icon="⏳"
        [[ "$status" == *"✅"* ]] && status_icon="✅"
        [[ "$status" == *"❌"* ]] && status_icon="❌"
        echo "  $time: $status_icon $checkpoint"
    fi
done
echo ""

# Show overall statistics
total_tasks=$(grep -c "^- \[.\]" "$STATUS_FILE")
completed_tasks=$(grep -c "^- \[x\]" "$STATUS_FILE")

echo "=== Overall Statistics ==="
echo "Total Progress: $completed_tasks/$total_tasks tasks"

# Last updated
last_updated=$(grep "^_Last updated:" "$STATUS_FILE" | sed 's/_//g')
echo "$last_updated"

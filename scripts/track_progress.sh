#!/bin/bash
# RAGline Progress Tracking System

set -e

# Colors for better visibility
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

MAIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATUS_FILE="$MAIN_DIR/docs/DAILY_STATUS.md"

# Function to show colorized progress
show_progress() {
    clear
    echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}         RAGline Development Progress${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
    echo ""
    
    # Extract current day
    current_day=$(grep "## Current Sprint:" "$STATUS_FILE" | head -1)
    echo -e "${YELLOW}$current_day${NC}"
    echo ""
    
    # Show progress for each agent
    for agent in A B C; do
        # Extract agent section
        agent_section=$(awk "/## 📋 Agent $agent/,/^---$/" "$STATUS_FILE")
        
        # Count tasks
        total=$(echo "$agent_section" | grep -c "^- \[.\]")
        completed=$(echo "$agent_section" | grep -c "^- \[x\]")
        
        # Ensure numeric values
        total=${total:-0}
        completed=${completed:-0}
        
        # Calculate percentage
        if [ "$total" -eq 0 ]; then
            percentage=0
        else
            percentage=$(( completed * 100 / total ))
        fi
        
        # Choose color based on progress
        if [ $percentage -eq 100 ]; then
            color=$GREEN
        elif [ $percentage -ge 50 ]; then
            color=$YELLOW
        else
            color=$RED
        fi
        
        # Display agent progress
        echo -e "${color}Agent $agent:${NC} $completed/$total tasks (${percentage}%)"
        
        # Show progress bar
        printf "["
        for ((i=0; i<20; i++)); do
            if [ $i -lt $((percentage * 20 / 100)) ]; then
                printf "█"
            else
                printf " "
            fi
        done
        printf "]\n"
        
        # Show blockers if any
        blocker=$(echo "$agent_section" | grep "^**Blockers:**" | sed 's/\*\*Blockers:\*\*//')
        if [ "$blocker" != " None" ] && [ -n "$blocker" ]; then
            echo -e "  ${RED}⚠ BLOCKED:${NC}$blocker"
        fi
        echo ""
    done
    
    # Show integration checkpoints
    echo -e "${BLUE}═══ Integration Checkpoints ═══${NC}"
    checkpoints=$(awk '/## 🔄 Integration Checkpoints/,/^---$/' "$STATUS_FILE" | grep "^|" | tail -n +3)
    echo "$checkpoints" | while IFS='|' read -r time checkpoint status details; do
        if [ -n "$time" ] && [ "$time" != "Time" ]; then
            status_icon="⏳"
            [[ "$status" == *"✅"* ]] && status_icon="✅"
            [[ "$status" == *"❌"* ]] && status_icon="❌"
            echo -e "  $time: $status_icon $checkpoint"
        fi
    done
    echo ""
    
    # Show overall statistics
    total_tasks=$(grep -c "^- \[.\]" "$STATUS_FILE" || echo 0)
    completed_tasks=$(grep -c "^- \[x\]" "$STATUS_FILE" || echo 0)
    
    echo -e "${BLUE}═══ Overall Statistics ═══${NC}"
    echo -e "Total Progress: ${GREEN}$completed_tasks/$total_tasks${NC} tasks"
    
    # Last updated
    last_updated=$(grep "^\*Last updated:" "$STATUS_FILE" | sed 's/\*//g')
    echo -e "${YELLOW}$last_updated${NC}"
}

# Mark task as complete
complete_task() {
    local agent=$1
    local task_pattern="$2"
    
    # Find and mark task as complete
    sed -i "/## 📋 Agent $agent/,/^---$/ { /$task_pattern/ s/\[ \]/\[x\]/ }" "$STATUS_FILE"
    
    echo -e "${GREEN}✓${NC} Marked task as complete for Agent $agent: $task_pattern"
    
    # Update progress line
    update_progress_line "$agent"
    
    # Update last modified
    update_timestamp
}

# Update progress line for an agent
update_progress_line() {
    local agent=$1
    
    # Count tasks in agent section
    agent_section=$(awk "/## 📋 Agent $agent/,/^---$/" "$STATUS_FILE")
    total=$(echo "$agent_section" | grep -c "^- \[.\]" || echo 0)
    completed=$(echo "$agent_section" | grep -c "^- \[x\]" || echo 0)
    
    if [ $total -gt 0 ]; then
        percentage=$((completed * 100 / total))
        
        # Update the Progress line
        sed -i "/## 📋 Agent $agent/,/^---$/ { s/\*\*Progress:\*\*.*/\*\*Progress:\*\* $completed\/$total main tasks ($percentage%)/ }" "$STATUS_FILE"
    fi
}

# Add or update blocker
add_blocker() {
    local agent=$1
    shift
    local blocker_text="$@"
    
    # Update blocker line
    sed -i "/## 📋 Agent $agent/,/^---$/ { s/\*\*Blockers:\*\*.*/\*\*Blockers:\*\* $blocker_text/ }" "$STATUS_FILE"
    
    echo -e "${YELLOW}⚠${NC} Added blocker for Agent $agent: $blocker_text"
    
    update_timestamp
}

# Clear blocker
clear_blocker() {
    local agent=$1
    
    sed -i "/## 📋 Agent $agent/,/^---$/ { s/\*\*Blockers:\*\*.*/\*\*Blockers:\*\* None/ }" "$STATUS_FILE"
    
    echo -e "${GREEN}✓${NC} Cleared blockers for Agent $agent"
    
    update_timestamp
}

# Update checkpoint status
update_checkpoint() {
    local time=$1
    local status=$2  # pending, done, failed
    
    case $status in
        done)
            icon="✅ Done"
            ;;
        failed)
            icon="❌ Failed"
            ;;
        *)
            icon="⏳ Pending"
            ;;
    esac
    
    # Update the checkpoint table
    sed -i "/^| $time /s/| [^|]*|/| $icon |/3" "$STATUS_FILE"
    
    echo -e "${GREEN}✓${NC} Updated checkpoint at $time to $status"
    
    update_timestamp
}

# Update timestamp
update_timestamp() {
    sed -i "s/\*Last updated:.*/\*Last updated: $(date +'%Y-%m-%d %H:%M:%S')\*/" "$STATUS_FILE"
}

# Quick task list for an agent
list_tasks() {
    local agent=$1
    
    echo -e "${BLUE}Tasks for Agent $agent:${NC}"
    echo ""
    
    # Extract and display tasks
    awk "/## 📋 Agent $agent/,/^---$/" "$STATUS_FILE" | grep "^- \[.\]" | nl -n ln | while read num task; do
        if [[ "$task" == *"[x]"* ]]; then
            echo -e "${GREEN}$num. ✓ ${task:6}${NC}"
        else
            echo -e "$num. ☐ ${task:6}"
        fi
    done
}

# Generate daily summary
daily_summary() {
    echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}            End of Day Summary${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
    echo ""
    
    # Show final progress
    show_progress
    
    echo ""
    echo -e "${YELLOW}Git Activity Summary:${NC}"
    echo ""
    
    # Show commits from each agent
    for agent in a b c; do
        agent_upper=$(echo $agent | tr '[:lower:]' '[:upper:]')
        echo -e "${BLUE}Agent $agent_upper commits:${NC}"
        
        if [ -d "$MAIN_DIR/../ragline-$agent" ]; then
            cd "$MAIN_DIR/../ragline-$agent"
            commits=$(git log --oneline --since="6am" 2>/dev/null | head -5)
            if [ -n "$commits" ]; then
                echo "$commits" | sed 's/^/  /'
            else
                echo "  No commits today"
            fi
        else
            echo "  Worktree not found"
        fi
        echo ""
    done
    
    cd "$MAIN_DIR"
    
    # Archive today's status
    today=$(date +%Y%m%d)
    cp "$STATUS_FILE" "$MAIN_DIR/docs/archive/DAILY_STATUS_${today}.md" 2>/dev/null || \
        (mkdir -p "$MAIN_DIR/docs/archive" && cp "$STATUS_FILE" "$MAIN_DIR/docs/archive/DAILY_STATUS_${today}.md")
    
    echo -e "${GREEN}✓${NC} Daily status archived to docs/archive/DAILY_STATUS_${today}.md"
}

# Interactive mode
interactive() {
    while true; do
        echo ""
        echo -e "${BLUE}RAGline Progress Tracker${NC}"
        echo "------------------------"
        echo "1. Show progress"
        echo "2. Complete a task"
        echo "3. Add/update blocker"
        echo "4. Clear blocker"
        echo "5. Update checkpoint"
        echo "6. List agent tasks"
        echo "7. Daily summary"
        echo "8. Edit status file"
        echo "9. Refresh"
        echo "0. Exit"
        echo ""
        read -p "Choose option: " choice
        
        case $choice in
            1)
                show_progress
                ;;
            2)
                read -p "Agent (A/B/C): " agent
                read -p "Task keyword: " keyword
                complete_task "$agent" "$keyword"
                ;;
            3)
                read -p "Agent (A/B/C): " agent
                read -p "Blocker description: " blocker
                add_blocker "$agent" "$blocker"
                ;;
            4)
                read -p "Agent (A/B/C): " agent
                clear_blocker "$agent"
                ;;
            5)
                read -p "Time (e.g., 14:00): " time
                read -p "Status (done/failed/pending): " status
                update_checkpoint "$time" "$status"
                ;;
            6)
                read -p "Agent (A/B/C): " agent
                list_tasks "$agent"
                ;;
            7)
                daily_summary
                ;;
            8)
                ${EDITOR:-vim} "$STATUS_FILE"
                ;;
            9)
                show_progress
                ;;
            0)
                exit 0
                ;;
        esac
        
        read -p "Press Enter to continue..."
    done
}

# Main command handling
case ${1:-show} in
    show)
        show_progress
        ;;
    complete)
        complete_task "$2" "$3"
        ;;
    blocker)
        add_blocker "$2" "${@:3}"
        ;;
    clear-blocker)
        clear_blocker "$2"
        ;;
    checkpoint)
        update_checkpoint "$2" "$3"
        ;;
    list)
        list_tasks "$2"
        ;;
    summary)
        daily_summary
        ;;
    edit)
        ${EDITOR:-vim} "$STATUS_FILE"
        ;;
    interactive|i)
        interactive
        ;;
    help|--help|-h)
        echo "RAGline Progress Tracker"
        echo ""
        echo "Usage: $0 [command] [args]"
        echo ""
        echo "Commands:"
        echo "  show                      - Display current progress (default)"
        echo "  complete A|B|C 'keyword'  - Mark task as complete"
        echo "  blocker A|B|C 'text'      - Add/update blocker"
        echo "  clear-blocker A|B|C       - Clear blocker"
        echo "  checkpoint TIME status    - Update checkpoint (done/failed/pending)"
        echo "  list A|B|C                - List tasks for an agent"
        echo "  summary                   - Generate daily summary"
        echo "  edit                      - Open status file in editor"
        echo "  interactive, i            - Interactive mode"
        echo ""
        echo "Examples:"
        echo "  $0 complete A 'Bootstrap FastAPI'"
        echo "  $0 blocker B 'Waiting for Outbox schema'"
        echo "  $0 checkpoint 14:00 done"
        echo "  $0 list A"
        ;;
    *)
        echo "Unknown command: $1"
        echo "Run '$0 help' for usage"
        exit 1
        ;;
esac

#!/bin/bash
# RAGline Daily Workflow Helper

set -e

# Capture original directory before any cd commands
ORIGINAL_DIR="$(pwd)"
ORIGINAL_DIR_NAME=$(basename "$ORIGINAL_DIR")

# Determine the main repository directory
# If we're in an agent worktree, point to the main ragline repo
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ "$(basename "$(pwd)")" =~ ragline-[abc] ]]; then
    MAIN_DIR="$(cd "$(dirname "$(pwd)")/ragline" && pwd)"
else
    MAIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
fi

echo "==============================="
echo "  RAGline Daily Workflow"
echo "==============================="

# Check if origin exists
check_remote() {
    if ! git remote | grep -q origin; then
        echo "[WARNING] No remote origin found. Please add GitHub remote first:"
        echo "   git remote add origin https://github.com/YOUR_USERNAME/ragline.git"
        exit 1
    fi
}

# Function to check agent status
check_agent() {
    local agent=$1
    local dir="$MAIN_DIR/../ragline-$agent"
    
    if [ ! -d "$dir" ]; then
        echo "[WARNING] Agent $agent worktree not found at $dir"
        echo "  Creating worktree..."
        cd "$MAIN_DIR"
        git worktree add "../ragline-$agent" "feat/$(get_agent_branch $agent)"
        return 0
    fi
    
    echo "[Agent $agent] Status:"
    cd "$dir"
    
    # Check if we have a remote
    if git remote | grep -q origin; then
        # Fetch latest without failing if no upstream
        git fetch origin 2>/dev/null || true
    fi
    
    # Show brief status
    local changes=$(git status --porcelain | wc -l)
    local branch=$(git branch --show-current)
    echo "  Branch: $branch"
    echo "  Changes: $changes uncommitted files"
    
    # Check if ahead/behind origin
    if git remote | grep -q origin && git rev-parse --abbrev-ref --symbolic-full-name @{u} >/dev/null 2>&1; then
        local ahead=$(git rev-list --count @{u}..HEAD 2>/dev/null || echo "0")
        local behind=$(git rev-list --count HEAD..@{u} 2>/dev/null || echo "0")
        [ "$ahead" -gt 0 ] && echo "  Ahead: $ahead commits"
        [ "$behind" -gt 0 ] && echo "  Behind: $behind commits"
    fi
    echo ""
}

# Define agent branch mapping
get_agent_branch() {
    local agent=$1
    case $agent in
        a) echo "core-api";;
        b) echo "reliability";;
        c) echo "llm";;
        *) echo "";;
    esac
}

# Morning sync
morning_sync() {
    echo ""
    echo "MORNING SYNC (09:00)"
    echo "-------------------"
    
    cd "$MAIN_DIR"
    check_remote
    
    echo "Fetching latest changes from GitHub..."
    git fetch origin || echo "[WARNING] Could not fetch from origin"
    echo ""
    
    # Check all agents
    for agent in a b c; do
        check_agent $agent
    done
    
    # Validate contracts
    echo "Validating contracts..."
    cd "$MAIN_DIR"
    
    if [ -f "contracts/openapi.yaml" ]; then
        echo -n "  OpenAPI: "
        if python3 -c "import yaml; yaml.safe_load(open('contracts/openapi.yaml'))" 2>/dev/null; then
            echo "VALID"
        else
            echo "INVALID or not yet created"
        fi
    else
        echo "  OpenAPI: Not found (expected: contracts/openapi.yaml)"
    fi
    
for file in contracts/events/*.json; do
        if [ -f "$file" ]; then
            echo -n "  $(basename $file): "
            if python3 -c "import json; json.load(open('$file'))" 2>/dev/null; then
                echo "VALID"
            else
                echo "INVALID"
            fi
        fi
    done
    
    if [ ! -f "contracts/openapi.yaml" ] && [ ! -f "contracts/events/order_v1.json" ]; then
        echo "  [INFO] No contracts found yet - create them in Day 1"
    fi
    
    echo ""
    echo "[DONE] Ready to start day"
    echo ""
    
    # Show today's tasks
    if [ -f "$MAIN_DIR/docs/DAILY_STATUS.md" ]; then
        echo "Today's Tasks:"
        echo "--------------"
        
        # Detect current agent and show specific tasks using original directory
        echo "DEBUG: ORIGINAL_DIR_NAME='$ORIGINAL_DIR_NAME'" >&2
        case "$ORIGINAL_DIR_NAME" in
            ragline-a)
                echo "📋 General Goals:"
                grep -A 4 "^### 🎯 Today's Goals" "$MAIN_DIR/docs/DAILY_STATUS.md" | tail -n +2 | head -n 4
                echo ""
                echo "🎯 Your Specific Tasks (Agent A):"
                awk "/## 📋 Agent A/,/^---$/" "$MAIN_DIR/docs/DAILY_STATUS.md"
                ;;
            ragline-b)
                echo "📋 General Goals:"
                grep -A 4 "^### 🎯 Today's Goals" "$MAIN_DIR/docs/DAILY_STATUS.md" | tail -n +2 | head -n 4
                echo ""
                echo "🎯 Your Specific Tasks (Agent B):"
                awk "/## 📋 Agent B/,/^---$/" "$MAIN_DIR/docs/DAILY_STATUS.md"
                ;;
            ragline-c)
                echo "📋 General Goals:"
                grep -A 4 "^### 🎯 Today's Goals" "$MAIN_DIR/docs/DAILY_STATUS.md" | tail -n +2 | head -n 4
                echo ""
                echo "🎯 Your Specific Tasks (Agent C):"
                awk "/## 📋 Agent C/,/^---$/" "$MAIN_DIR/docs/DAILY_STATUS.md"
                ;;
            *)
                # Default: show all goals and first agent as example
                head -30 "$MAIN_DIR/docs/DAILY_STATUS.md" | grep -A 20 "^### 🎯 Today's Goals" || echo "  No daily status found"
                ;;
        esac
    fi
}

# Midday integration check
midday_check() {
    echo ""
    echo "MIDDAY INTEGRATION (14:00)"
    echo "-------------------------"
    
    cd "$MAIN_DIR"
    
    # Check for blockers
    if [ -f "$MAIN_DIR/docs/DAILY_STATUS.md" ]; then
        echo "Checking for blockers..."
        if grep -q "#BLOCKED" "$MAIN_DIR/docs/DAILY_STATUS.md" 2>/dev/null; then
            echo "[WARNING] Blockers found:"
            grep "#BLOCKED" "$MAIN_DIR/docs/DAILY_STATUS.md"
        else
            echo "[OK] No blockers found"
        fi
    fi
    
    # Run quick tests if available
    for agent in a b c; do
        local dir="$MAIN_DIR/../ragline-$agent"
        if [ -d "$dir" ] && [ -d "$dir/tests" ]; then
            echo ""
            echo "Agent $agent tests:"
            cd "$dir"
            if [ -f "requirements.txt" ]; then
                echo "  [INFO] Run: pytest tests/ (when ready)"
            else
                echo "  [INFO] No tests configured yet"
            fi
        fi
    done
    
    echo ""
    echo "[DONE] Integration check complete"
}

# Evening merge prep
evening_prep() {
    echo ""
    echo "EVENING MERGE PREP (18:00)"
    echo "-------------------------"
    
    cd "$MAIN_DIR"
    check_remote
    
    echo "Checking merge readiness..."
    echo ""
    
    # Check each worktree for uncommitted changes
    for agent in a b c; do
        local dir="$MAIN_DIR/../ragline-$agent"
        if [ -d "$dir" ]; then
            echo "Agent $agent:"
            cd "$dir"
            
            local changes=$(git status --porcelain | wc -l)
            if [ "$changes" -gt 0 ]; then
                echo "  [WARNING] $changes uncommitted changes"
                echo "  Files:"
                git status --porcelain | head -5 | sed 's/^/    /'
                [ "$changes" -gt 5 ] && echo "    ... and $((changes-5)) more"
            else
                echo "  [OK] Clean working directory"
            fi
            
            # Check if ahead of origin
            if git remote | grep -q origin && git rev-parse --abbrev-ref --symbolic-full-name @{u} >/dev/null 2>&1; then
                local ahead=$(git rev-list --count @{u}..HEAD 2>/dev/null || echo "0")
                if [ "$ahead" -gt 0 ]; then
                    echo "  [INFO] $ahead commits ready to push"
                fi
            fi
            echo ""
        fi
    done
    
    echo "[DONE] Ready for merge coordination"
    echo ""
    echo "Next steps:"
    echo "  1. Commit any uncommitted changes"
    echo "  2. Push to feature branches"
    echo "  3. Create PRs if ready to merge"
}

# Main menu
case ${1:-menu} in
    morning)
        morning_sync
        ;;
    midday)
        midday_check
        ;;
    evening)
        evening_prep
        ;;
    *)
        echo "Usage: $0 {morning|midday|evening}"
        echo ""
        echo "  morning - 09:00 sync and contract review"
        echo "  midday  - 14:00 integration testing"
        echo "  evening - 18:00 merge preparation"
        ;;
esac

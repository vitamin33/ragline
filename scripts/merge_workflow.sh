#!/bin/bash
# RAGline merge workflow helper

set -e

MAIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"

sync_from_main() {
    echo "=== Syncing all agents from main ==="
    
    for agent in a b c; do
        echo "Syncing ragline-$agent..."
        cd "$MAIN_DIR/../ragline-$agent"
        
        # Fetch latest
        git fetch origin
        
        # Check for uncommitted changes
        if [ -n "$(git status --porcelain)" ]; then
            echo "  WARNING: Uncommitted changes in ragline-$agent"
            echo "  Stashing changes..."
            git stash push -m "Auto-stash before sync"
        fi
        
        # Merge or rebase from main
        git rebase origin/main || git merge origin/main
        
        # Pop stash if exists
        if git stash list | grep -q "Auto-stash before sync"; then
            echo "  Restoring stashed changes..."
            git stash pop
        fi
        
        echo "  Done!"
    done
}

merge_agent_to_main() {
    local agent=$1
    local branch=""
    
    case $agent in
        a) branch="feat/core-api" ;;
        b) branch="feat/reliability" ;;
        c) branch="feat/llm" ;;
        *) echo "Invalid agent"; exit 1 ;;
    esac
    
    echo "=== Merging Agent $agent to main ==="
    
    # Go to main repo
    cd "$MAIN_DIR"
    
    # Ensure we're on main
    git checkout main
    git pull origin main
    
    # Merge the feature branch
    echo "Merging $branch..."
    git merge origin/$branch --no-ff -m "merge: Agent $agent Day X changes"
    
    # Push to origin
    git push origin main
    
    echo "Agent $agent merged to main!"
}

create_daily_pr() {
    local agent=$1
    local day=$2
    local branch=""
    
    case $agent in
        a) branch="feat/core-api" ;;
        b) branch="feat/reliability" ;;
        c) branch="feat/llm" ;;
    esac
    
    echo "Creating PR for Agent $agent Day $day"
    
    # Using GitHub CLI
    gh pr create \
        --base main \
        --head $branch \
        --title "Agent $agent: Day $day implementation" \
        --body "## Changes
- Implemented tasks from docs/DAILY_TASKS.md
- All tests passing
- No merge conflicts

## Checklist
- [ ] Code review completed
- [ ] Tests passing
- [ ] No ownership violations"
}

case ${1:-help} in
    sync)
        sync_from_main
        ;;
    merge)
        merge_agent_to_main ${2:-a}
        ;;
    pr)
        create_daily_pr ${2:-a} ${3:-1}
        ;;
    *)
        echo "Usage: $0 {sync|merge [a|b|c]|pr [a|b|c] [day]}"
        echo ""
        echo "  sync         - Sync all agents from main"
        echo "  merge [a|b|c] - Merge agent branch to main"
        echo "  pr [a|b|c] [day] - Create PR for agent"
        ;;
esac

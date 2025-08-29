#!/bin/bash
#
# Setup git hooks for all RAGline worktrees to prevent Co-Authored-By violations
#

set -e

echo "🔧 Setting up RAGline git hooks for all worktrees..."

# Hook content
COMMIT_MSG_HOOK='#!/bin/sh
#
# RAGline commit-msg hook
# Prevents commits with Co-Authored-By lines as per CLAUDE.md rules
#

commit_msg_file="$1"

# Check for Co-Authored-By lines
if grep -q "Co-Authored-By:" "$commit_msg_file"; then
    echo "❌ ERROR: Co-Authored-By lines are forbidden per CLAUDE.md rules"
    echo "   Rule: '\''NEVER add co-author tags to commits'\''"
    echo "   Please remove Co-Authored-By lines and try again"
    exit 1
fi

# Check for Claude Code attribution
if grep -q "🤖 Generated with \[Claude Code\]" "$commit_msg_file"; then
    echo "❌ ERROR: Claude Code attribution detected"
    echo "   Rule: '\''NEVER add co-author tags to commits'\''"
    echo "   Please remove attribution lines and try again"
    exit 1
fi

# Check for any AI attribution patterns
if grep -qi "generated.*claude\|claude.*generated\|anthropic" "$commit_msg_file"; then
    echo "❌ ERROR: AI attribution detected"
    echo "   Rule: '\''NEVER add co-author tags to commits'\''"
    echo "   Please remove AI attribution and try again"
    exit 1
fi

# Success
exit 0'

# Find all worktrees
MAIN_GIT_DIR="/Users/vitaliiserbyn/development/ragline/.git"
WORKTREES_DIR="$MAIN_GIT_DIR/worktrees"

# Install hook for main repo
if [ -d "$MAIN_GIT_DIR/hooks" ]; then
    echo "📝 Installing hook for main repository..."
    echo "$COMMIT_MSG_HOOK" > "$MAIN_GIT_DIR/hooks/commit-msg"
    chmod +x "$MAIN_GIT_DIR/hooks/commit-msg"
    echo "✅ Main repository hook installed"
fi

# Install hooks for all worktrees
if [ -d "$WORKTREES_DIR" ]; then
    for worktree in "$WORKTREES_DIR"/*; do
        if [ -d "$worktree" ]; then
            worktree_name=$(basename "$worktree")
            echo "📝 Installing hook for worktree: $worktree_name..."

            # Create hooks directory if it doesn'\''t exist
            mkdir -p "$worktree/hooks"

            # Install commit-msg hook
            echo "$COMMIT_MSG_HOOK" > "$worktree/hooks/commit-msg"
            chmod +x "$worktree/hooks/commit-msg"

            echo "✅ Hook installed for $worktree_name"
        fi
    done
fi

echo ""
echo "🎉 Git hooks setup complete!"
echo ""
echo "🛡️  Protection enabled against:"
echo "   - Co-Authored-By lines"
echo "   - Claude Code attribution"
echo "   - Any AI attribution patterns"
echo ""
echo "📋 All commits will now be automatically validated"

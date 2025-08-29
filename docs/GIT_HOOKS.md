# RAGline Git Hooks Documentation

## 🛡️ Protection Against Co-Authored-By Violations

### Problem
The CLAUDE.md file explicitly states:
- **"NEVER add co-author tags to commits"**
- **"Commit (NO CO-AUTHORS!)"**

However, AI assistants might automatically add Co-Authored-By lines, violating project rules.

### Solution: Automated Git Hooks

We've implemented git hooks that **automatically prevent** commits with forbidden content.

## 🔧 Setup

### Automatic Setup (Recommended)
```bash
./scripts/setup-git-hooks.sh
```

This script automatically:
- ✅ Installs hooks for main repository
- ✅ Installs hooks for all worktrees (ragline-a, ragline-b, ragline-c)
- ✅ Sets proper permissions
- ✅ Validates all patterns

### Manual Setup
If you need to set up hooks manually:

```bash
# For each worktree
cat > .git/hooks/commit-msg << 'EOF'
#!/bin/sh
# RAGline commit-msg hook
commit_msg_file="$1"

if grep -q "Co-Authored-By:" "$commit_msg_file"; then
    echo "❌ ERROR: Co-Authored-By lines are forbidden per CLAUDE.md rules"
    exit 1
fi

if grep -q "🤖 Generated with \[Claude Code\]" "$commit_msg_file"; then
    echo "❌ ERROR: Claude Code attribution detected"
    exit 1
fi

exit 0
EOF

chmod +x .git/hooks/commit-msg
```

## 🔍 What's Protected

The git hooks prevent commits containing:

### ❌ Forbidden Patterns
- `Co-Authored-By:` lines
- `🤖 Generated with [Claude Code]` attribution
- `generated.*claude` or `claude.*generated`
- `anthropic` mentions in commit messages

### ✅ Example Blocked Commit
```
feat: implement JWT authentication

This implements secure JWT tokens.

🤖 Generated with [Claude Code](https://claude.ai/code)
Co-Authored-By: Claude <noreply@anthropic.com>
```

**Result**: Commit blocked with clear error message.

### ✅ Example Valid Commit
```
feat(auth): implement JWT authentication

This implements secure JWT tokens with:
- Multi-tenant support
- Role-based access control
- Token expiration handling
```

**Result**: Commit succeeds.

## 🧪 Testing

Test the hooks work correctly:

```bash
# This should FAIL
echo "test: commit Co-Authored-By: Test <test@example.com>" > test.tmp
git commit --allow-empty -F test.tmp

# This should SUCCESS
git commit --allow-empty -m "feat: test commit without forbidden content"
```

## 🔄 Hook Management

### Check Hook Status
```bash
# Check if hooks exist
ls -la .git/hooks/commit-msg

# Test hook manually
echo "Co-Authored-By: Test" | .git/hooks/commit-msg /dev/stdin
```

### Update Hooks
```bash
# Re-run setup to update all worktrees
./scripts/setup-git-hooks.sh
```

### Disable Hooks (Not Recommended)
```bash
# Temporarily disable (NOT recommended)
chmod -x .git/hooks/commit-msg

# Re-enable
chmod +x .git/hooks/commit-msg
```

## 📋 Integration with Development Workflow

### For AI Assistants
The hooks provide **immediate feedback** when AI assistants attempt to add forbidden content:

1. **AI tries to commit** with Co-Authored-By
2. **Hook blocks commit** with clear error message
3. **AI learns** to avoid forbidden patterns
4. **Clean commits** are created automatically

### For Developers
- **No manual checking** required
- **Automatic compliance** with project rules
- **Clear error messages** when violations occur
- **Consistent across all worktrees**

## 🎯 Benefits

1. **Prevents Rule Violations**: Impossible to commit forbidden content
2. **Immediate Feedback**: Clear error messages explain what's wrong
3. **Automatic Learning**: AI assistants adapt to avoid blocked patterns
4. **Project Consistency**: All contributors follow same rules
5. **Zero Maintenance**: Once set up, works automatically

## 🔧 Troubleshooting

### Hook Not Working
```bash
# Check hook exists and is executable
ls -la .git/hooks/commit-msg

# Re-run setup
./scripts/setup-git-hooks.sh
```

### Bypass Hook (Emergency Only)
```bash
# ONLY for emergencies - violates project rules
git commit --no-verify -m "emergency commit"
```

### Hook Too Strict
If the hook blocks legitimate content, update the patterns in:
- `scripts/setup-git-hooks.sh`
- Re-run setup script

## 📚 Related Documentation

- [CLAUDE.md](../CLAUDE.md) - Project rules and agent ownership
- [Git Workflow](../docs/DEVELOPMENT.md) - Development process
- [Commit Standards](../docs/COMMITS.md) - Commit message format

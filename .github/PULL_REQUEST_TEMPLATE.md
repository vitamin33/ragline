### What & Why
- **Scope**: Agent [A|B|C] or [Shared]
- **Changes**: Brief description of what was implemented/fixed
- **Risk Level**: [Low|Medium|High] & rollback plan if needed
- **Metrics to watch**: p95 latency, error rate, specific SLIs that may be affected

### Integration Impact
- [ ] Cross-agent contracts unchanged OR properly versioned
- [ ] Database migrations (if any): reversible and tested
- [ ] Event schema: backward compatible with existing consumers
- [ ] API changes: backward compatible or properly deprecated

### Tests & Validation
- [ ] Unit tests passing (`just test-[a|b|c]`)
- [ ] Integration tests (if cross-agent changes)
- [ ] k6 smoke test (if API changes) (`just k6`)
- [ ] Manual testing in agent worktree
- [ ] No performance regression detected

### Agent Ownership Compliance
- [ ] No ownership boundary violations (check with `just check-owner <file>`)
- [ ] Contract changes approved by affected agents
- [ ] Documentation updated (`docs/` if architectural changes)
- [ ] ADR created for significant decisions

### Security & Quality
- [ ] Pre-commit hooks passing (ruff, bandit, gitleaks)
- [ ] No secrets or sensitive data committed
- [ ] Dependencies updated and scanned for vulnerabilities
- [ ] Code follows existing patterns and conventions

### Deployment Readiness
- [ ] Feature flags implemented (if applicable)
- [ ] Monitoring/alerting considerations addressed
- [ ] Rollback procedure documented (if high risk)
- [ ] Database migration plan (if applicable)

---

**Reviewer Notes**:
- Focus on agent boundaries and contract compliance
- Verify integration points work correctly
- Check for potential performance or security impacts

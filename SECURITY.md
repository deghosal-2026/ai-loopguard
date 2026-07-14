# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅        |

## Reporting a Vulnerability

If you discover a security vulnerability in ai-loopguard, please report it
responsibly:

1. **Do NOT open a public GitHub issue.**
2. Email **deghosal@example.com** (replace with actual contact) with:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)
3. You will receive a response within 48 hours.
4. Once the vulnerability is confirmed and fixed, we will publish a security
   advisory and credit you (unless you prefer to remain anonymous).

## Security considerations

ai-loopguard processes agent loop state, which may include:

- **Agent outputs** — could contain sensitive data from the user's codebase
- **Error messages** — could contain stack traces, file paths, or secrets
- **Escalation prompts** — packaged context sent to the escalation model

### Built-in protections

- **Redactor** — strips known secret patterns (OpenAI keys, AWS keys, GitHub
  tokens) from escalation prompts before they are sent to the escalation model
- **Sanitizer** — wraps agent output in delimiters to reduce prompt injection
  risk
- **No telemetry** — ai-loopguard does not phone home or collect usage data

### User responsibilities

- Configure `redact_patterns` with your organization's secret patterns
- Configure `redact_fields` to strip sensitive field names from context
- Review escalation prompts before sending to third-party model providers
- Use `sanitize_context=True` (default) to reduce prompt injection risk

## Disclosure timeline

- **Day 0**: Vulnerability reported
- **Day 1**: Acknowledgment sent to reporter
- **Day 7**: Fix developed and tested
- **Day 14**: Security advisory published, patched release issued

# Changelog

All notable changes to ai-loopguard will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-07-12

### Added
- Initial release
- Circuit breaker pattern for LLM agent loops
- Stuck pattern detection (repeated errors, test failures, hallucination cycles)
- Tiered escalation to stronger models
- Cost-per-completed-task tracking
- Escalation rate SLO monitoring
- LangGraph and CrewAI integration adapters
- Raw Python agent loop wrapper
- 391 tests with 95.9% coverage
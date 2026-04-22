# Estyn Copilot Instructions

These instructions apply to all Copilot code reviews in this repository. Review every
pull request against these standards and flag violations. Be specific: reference the
exact line, explain the problem, and suggest the correct pattern.

---

## Purpose of Copilot Reviews

Copilot reviews are an independent quality pass — a different model's perspective on code
written primarily by Claude (Anthropic). The value is in catching what the implementing
agent missed. Review for correctness, scalability, and adherence to Estyn standards.
Do not rubber-stamp.

---

## 0. Scale Classification — Flag Missing Reasoning

Estyn distinguishes two categories of data, and the coding approach depends on which category applies.

**Transient / event-based data** (transactions, orders, product classifications, events, user activity) grows continuously and must be designed for multi-tenant scale — multiple tenants generating combined load simultaneously.

**Non-transient / reference data** (config, tenant settings, lookup tables, roles, feature flags) is bounded by design and can be handled pragmatically (cached, loaded fully into memory).

**Flag if:**
- Code accesses a data store and there is no comment, PR description, or planning context indicating whether the data is transient or non-transient — flag and ask the author to confirm the classification
- Transient data (orders, transactions, classifications) is being loaded without pagination or streaming — flag as a scale risk
- Non-transient data (config, settings) is being fetched from the database on every request with no caching — flag and suggest module-level caching with a TTL
- A new table or data model is introduced with no indication of expected volume per tenant or total platform scale — flag as a missing planning artefact

---

## 1. Data Loading and Memory

**Flag any of the following:**

- `SELECT *` — always flag. Require named columns. Explain the over-fetching and fragility risks.
- `fetchall()` on a potentially large result set — flag and suggest `fetchmany()` with a page size or a server-side cursor.
- DynamoDB `scan()` without pagination via `LastEvaluatedKey` — flag. Suggest the paginator pattern.
- DynamoDB `get_item` or `query` without a `ProjectionExpression` where not all attributes are needed — flag.
- Loading an entire collection into memory before filtering or paginating — flag. Require pagination at the database layer.
- Pagination implemented by slicing a full in-memory list (e.g. `all_items[offset:offset+limit]`) — flag. Require `LIMIT`/`OFFSET` or cursor-based pagination in the query.

**Do not flag:**
- Loading a small, bounded dataset (lookup tables, config, reference data) into memory — this is acceptable. Use judgment on whether the dataset is genuinely bounded.

---

## 2. Database Connections

**Flag any of the following:**

- Database client or connection initialised inside the Lambda handler function — flag. Require initialisation at module level so connections are reused across warm invocations.
- A new connection opened per record inside a loop — flag. Require connection reuse or a connection pool.
- Multiple separate queries to the same database fetching data that could be joined in a single query — flag. Require the join to happen in the database, not in application code.
- Missing RDS Proxy configuration for Lambda-to-RDS connections — flag and recommend RDS Proxy to handle connection pooling under Lambda's horizontal scaling.

---

## 3. Query Discipline

**Flag any of the following:**

- `SELECT *` in any SQL query (see Section 1 — flag every instance)
- DynamoDB `Scan` operations without a documented reason — flag. Scans are expensive. Ask whether a `Query` with a GSI would work instead.
- Queries inside loops (N+1 pattern) — flag. Require batch operations (`batch_get_item`, `IN` clause, or a single JOIN) instead of per-record queries.
- Missing indexes on columns used in `WHERE`, `JOIN ON`, or `ORDER BY` in migration files — flag.

---

## 4. Async and Concurrency

**Flag any of the following:**

- Sequential `await` calls for operations that are clearly independent — flag and suggest `asyncio.gather`.
- `asyncio.gather` without `return_exceptions=True` where individual failures should be handled rather than crashing the whole gather — flag.
- Threads or coroutines without explicit timeouts when calling external services — flag.
- CPU-bound work inside `asyncio` coroutines (blocking the event loop) — flag. Suggest `run_in_executor` or a worker process.

**Do not flag:**
- Sequential awaits where the output of one call is the input to the next — this is correct, not a performance issue.

---

## 5. Lambda-Specific Patterns

**Flag any of the following:**

- Lambda timeout set to the maximum (15 minutes) without a documented reason — flag. Timeout should reflect the expected worst-case execution time, not the limit.
- Heavy initialisation (DB connections, large model loads, config fetches) inside the handler — flag. Move to module level.
- Unbounded loops or unbounded pagination inside a single Lambda invocation without a timeout guard — flag.
- Missing Dead Letter Queue (DLQ) configuration on SQS-triggered Lambdas — flag.
- SQS batch size set to 1 without a documented reason — flag. Default to higher batch sizes for throughput.

---

## 6. Cross-System Data Merging

When code fetches data from two different sources and merges them, flag if:

- The merge pattern is not documented (inline comment or PR description) — flag. Both "fetch keys then call external service" and "pull full dataset and merge" are valid patterns, but the choice must be explained.
- Individual per-record API calls are made in a loop when the external service supports batch retrieval — flag. Require batch calls.
- Data that could be joined at the database layer is being joined in application code — flag.

---

## 7. Code Style and Standards

**Flag any of the following:**

- Hardcoded credentials, API keys, or secrets in source code — flag as a security violation. Require SSM Parameter Store or Secrets Manager.
- Environment-specific configuration hardcoded rather than read from environment variables or SSM — flag.
- Functions longer than ~50 lines that could reasonably be broken into smaller units — flag with a suggestion, not a blocker.
- Missing error handling on external service calls (uncaught exceptions from API calls, DB queries, S3 operations) — flag.
- Bare `except Exception` or `except:` without logging the exception — flag. Require at minimum `logger.error(exc_info=True)`.
- Log statements using string concatenation or `%` formatting instead of structured logging — flag. Require structured JSON logs with consistent field names.

---

## 8. Testing

**Flag if:**

- A PR introduces new logic with no corresponding test — flag. Tests are non-negotiable.
- Tests only cover the happy path with no edge cases or error conditions — flag.
- Tests mock at the wrong layer (e.g. mocking internal implementation details rather than external dependencies) — flag.

---

## 9. What Not to Flag

Do not flag the following as issues:

- Estyn's deliberate process choices (Planning Gate, subtask structure, branch naming) — these are workflow conventions, not code quality issues
- Minor stylistic preferences (quote style, minor naming conventions) unless they violate an explicit standard above
- Complexity that is genuinely required by the problem — not all complex code can or should be simplified
- Performance optimisations that have been explicitly documented as a deliberate trade-off in the PR description or inline comments

When in doubt, raise it as a question rather than a blocker. The implementing agent and reviewer will assess.

---

## 10. Comment Format

For every issue found, structure your comment as:

**Issue:** [One sentence describing the problem]
**Why it matters:** [One sentence on the risk — memory, connections, correctness, security]
**Suggested fix:** [Concrete code suggestion or pattern reference]

Keep comments factual and specific. Do not pad with praise or general encouragement.

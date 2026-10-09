# Repeatable performance and scale checks

The load tools are restricted to `DEBUG=True` and use `load-`-prefixed users,
cards, sessions, and journals. Run them only against a disposable development
database, never production.

1. Start a fresh database with current migrations and the normal 2,000-student,
   100,000-transaction, 200-preorder fixture:

   ```sh
   python manage.py seed_load_data
   ```

   Use `--dry-run` to inspect the planned size or override counts for a smaller
   smoke test. The seeder builds ledger journal lines and transaction payment
   breakdowns and includes sponsor allocations and pre-order hold/release
   journals. Re-running against an already seeded database is refused.

2. Measure analytics, ledger, and insights read endpoints:

   ```sh
   python manage.py benchmark_load_endpoints --iterations 20 --output benchmark.json
   ```

   The report records HTTP status plus p50/p95 latency in milliseconds. Keep
   the generated report with the test run; it is environment-specific and is
   intentionally not committed as a universal performance claim.

3. Repeat on the deployment database engine and representative CPU/memory,
   recording the database version, host, fixture counts, warm/cold-cache state,
   and command output. Compare before/after changes using the same conditions.

Run the reduced seeder test manually with the test suite; it asserts wallet and
hold journal balances match their card balances. CI workflows have been removed,
so no test runs automatically on pushes or pull requests. A production-sized
PostgreSQL timing run is an operational benchmark, not part of unit tests.

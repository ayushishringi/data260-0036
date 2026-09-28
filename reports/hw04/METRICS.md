# HW4 Metrics

## N+1 Experiment

The experiment used 5,000 vulnerability reports and 200 related advisories. Each condition was measured using 30 runs after 2 warm-up runs.

| Page size | Variant | Query count | p50 latency | p95 latency | p99 latency |
|---:|---|---:|---:|---:|---:|
| 10 | Naive | 11 | 1.6666 ms | 2.1878 ms | 2.3425 ms |
| 10 | Fixed | 2 | 0.5055 ms | 0.5466 ms | 0.5773 ms |
| 50 | Naive | 51 | 6.4875 ms | 7.3788 ms | 11.0407 ms |
| 50 | Fixed | 2 | 0.9624 ms | 1.0918 ms | 1.4295 ms |
| 200 | Naive | 201 | 25.5755 ms | 28.3768 ms | 31.1851 ms |
| 200 | Fixed | 2 | 2.4388 ms | 2.5665 ms | 7.1390 ms |

The naive implementation performs one query for the reports and one additional query for each report's related advisories. The optimized implementation uses SQLAlchemy `selectinload`, reducing the operation to two queries regardless of page size.

## Database Index and EXPLAIN

An index was added to the `package_name` column:

```sql
    CREATE INDEX idx_vulnerability_reports_package_name
    ON vulnerability_reports(package_name);

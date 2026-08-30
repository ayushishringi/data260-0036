# Domain schema — open-source package vulnerabilities

**DOMAIN_ID:** 4  
**Assigned domain:** Open-source package vulnerabilities  
**Entity name:** Vulnerability Report

This schema is the source of truth for the HTML form fields and category values.

## Entity: Vulnerability Report

| Field | Role | HTML control | Required | Notes |
| --- | --- | --- | --- | --- |
| `packageName` | Primary | text | yes | Canonical name of the affected package (e.g. `lodash`, `log4j-core`). Autofocus on page load. |
| `affectedVersion` | Secondary | text | yes | Version range or exact version that is affected (e.g. `< 4.17.21`). |
| `submitterEmail` | Submitter | email | yes | Contact for the person filing the report. |
| `description` | Content | textarea | yes | What the issue is, impact, and how it was found. Client-side rule: more than 25 characters. |
| `severity` | Category | select | yes | One of four domain-appropriate severity buckets (see below). |
| `agreedToTerms` | Consent | checkbox | yes | Must be checked before submit. |
| `submissionDate` | Derived | (JS only) | n/a | Added after a successful submit via the spread operator; not a form field. |

## Category values (`severity`)

Exactly four options, shown in the dropdown:

1. `critical` — remote code execution, auth bypass, or equivalent
2. `high` — privilege escalation or significant data exposure
3. `medium` — limited impact with a realistic exploit path
4. `low` — defense-in-depth / hard-to-reach issue

## Example record (illustrative)

```json
{
  "packageName": "example-http-client",
  "affectedVersion": "< 2.4.1",
  "submitterEmail": "reporter@example.edu",
  "description": "TLS certificate hostname verification is skipped when a custom proxy URL is set, allowing MITM of API traffic.",
  "severity": "high",
  "agreedToTerms": true
}
```

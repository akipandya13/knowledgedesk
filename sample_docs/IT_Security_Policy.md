# Acme Technologies — IT & Information Security Policy (ISMS v5.0)

Effective: 15 February 2026 | Owner: CISO | ISO 27001:2022 aligned

## Access Control

All access follows least-privilege. Production access requires a Jira request approved by the system owner and expires after 90 days unless renewed. Admin access to any production system requires hardware-key MFA. Shared accounts are prohibited; service accounts must be owned by a team, vaulted, and rotated every 180 days.

## Password and Authentication Policy

Minimum 14 characters, passphrases encouraged. SSO via Azure AD is mandatory for all SaaS tools; any tool that cannot integrate with SSO needs a CISO exception. MFA is mandatory on all accounts. Password rotation is NOT required unless compromise is suspected, in line with current NIST guidance.

## Device Policy

Company laptops are enrolled in MDM with full-disk encryption enforced. USB mass storage is blocked by default; exceptions via IT ticket with manager approval, auto-expiring in 7 days. Personal devices may access email and Slack only through the MDM-managed mobile profile. Lost or stolen devices must be reported to it-security@acmetech.example within 4 hours; remote wipe is triggered immediately.

## Data Classification

Four levels: Public, Internal, Confidential, Restricted. Restricted data (customer PII, source code signing keys, payroll) may never leave approved systems and may not be pasted into external AI tools. Confidential documents shared externally require a signed NDA and watermarking via the DLP gateway.

## Incident Response

Suspected incidents are reported to it-security@acmetech.example or the #security-incidents Slack channel. Triage SLA is 1 hour during business hours, 4 hours otherwise. The CISO declares severity. Sev-1 incidents (confirmed breach, ransomware, customer data exposure) trigger the crisis bridge, legal notification review within 24 hours, and customer notification within 72 hours where contractually or legally required.

## Software and AI Tool Usage

Only software from the approved catalogue may be installed. Requests for new tools go through the security review queue (5 working day SLA). Approved AI coding assistants may be used on non-Restricted repositories only. Uploading Confidential or Restricted data to unapproved cloud or AI services is a terminable offence.

## Backups and Recovery

Production databases: point-in-time recovery enabled, daily snapshots retained 35 days, monthly snapshots retained 1 year in a separate region. Disaster recovery objective: RPO 1 hour, RTO 4 hours. DR drills run every 6 months and results are reported to the audit committee.

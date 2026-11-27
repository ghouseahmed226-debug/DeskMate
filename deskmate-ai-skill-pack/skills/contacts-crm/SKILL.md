---
name: contacts-crm
description: >
  Personal contact management and lightweight CRM functionality.
  Use when the user wants to look up a contact's email or phone number,
  search contacts by name or company, view relationship history,
  or find attendee details for a meeting. Supports fuzzy name matching.
license: MIT
metadata:
  author: ghouseahmed226-debug
  version: "2.0.0"
  project: DeskMate AI
  category: crm
allowed-tools: read_file list_directory
---

# Contacts & CRM Skill

## Overview

Delegates to the **ContactCRM_Agent**. Provides read and search access to
the contacts data store (mock JSON or Google Contacts via OAuth).

## Key Capabilities

| Capability | Description |
|---|---|
| **Lookup by Name** | Returns full contact card for a person |
| **Search by Company** | Lists all contacts at a company |
| **Email Lookup** | Returns email address for a given name |
| **Phone Lookup** | Returns phone number |
| **Fuzzy Match** | Handles partial / misspelled names |
| **Meeting Attendees** | Resolves a list of names to contact cards |

## Example Prompts

```
Look up contact Sarah Chen
What is John's email address?
Show all contacts at Acme Corp
Find the phone number for the marketing team lead
Who are the attendees for the Project Review meeting?
```

## Related Skills

- `meeting-assistant` — uses contacts to build attendee profiles for prep
- `email-intelligence` — enriches emails with contact metadata
- `calendar-scheduling` — resolves attendee names to email addresses

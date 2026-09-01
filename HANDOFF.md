# Elinor Commission System — Handoff

## Repository
/Users/rezasoltani/Documents/elinor-commission

## Architecture
Django + PostgreSQL + Docker Compose

## Branch
main

## Last Stable Commit Before Current Changes
1dbd706 feat: add timed support-line intervals

## Current State
Multi-interval support-line tracking completed on top of the Gemini shift UI. The legacy Activities module has been fully removed from the application; Violations remain active.

- `SupportLineInterval` stores destination line, start/end and server-calculated minutes.
- `DailyShiftLog` summary hours are rebuilt server-side from intervals.
- Repeatable RTL interval UI is available on create/edit.
- Manager detail shows exact intervals for camera review.
- Interval create/update/delete events are audited.
- Migration: `0011_supportlineinterval`.
- No new commission rule was added.
- Manager-facing Department CRUD is available under `/management/departments/`.
- Manager dashboard and sidebar navigation use the new compact admin design system.

## Latest Migration
0012_archive_remove_activities

## Validation
PostgreSQL test suite passing.
Migration consistency check passes.
Health and related pages sanity-checked.

## Run
docker compose build web
docker compose up -d web

## Tests
docker compose exec web python manage.py test

## Health
curl -s http://localhost:8010/health/

## Important Docker Behavior
Source code is copied into the Docker image.
The repository is NOT bind-mounted into the web container.

After source-code changes:
docker compose build web
docker compose up -d web

The entrypoint may automatically apply migrations during container startup.

If makemigrations is executed inside the container, copy the generated migration back into the host repository before committing.

## Core Business Rule
Commission inputs come from structured shift logs and line sales. Violations remain a separate deduction source. The removed Activities module must not be reintroduced without a new product decision.

## Safe deletion
Management deletion is POST/CSRF-only from each detail/edit Danger Zone. Department, Shift, Employee, DailyShiftLog and ViolationRule report counted blockers; successful deletions create AuditLog entries. AuditLog and SystemSettings have no delete UI.
The managed entities are Department, Shift, Employee, DailyShiftLog, LineShiftPerformance, ViolationRule and Violation. Department deletion is available from its edit page and control center, never from the list. Internal line rates/targets/grades are not separate deletable management entities; their mistakenly added delete endpoints were removed.

## Next Product Area
Before major implementation, finalize:
- violation logic
- employee levels
- commission calculation and breakdown

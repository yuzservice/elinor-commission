# Elinor Commission System — Handoff

## Repository
/Users/rezasoltani/Documents/elinor-commission

## Architecture
Django + PostgreSQL + Docker Compose

## Branch
main

## Last Stable Commit Before Current Changes
30605ca feat: complete activity workflow

## Current State
Multi-interval support-line tracking completed on top of the Gemini shift UI.

- `SupportLineInterval` stores destination line, start/end and server-calculated minutes.
- `DailyShiftLog` summary hours are rebuilt server-side from intervals.
- Repeatable RTL interval UI is available on create/edit.
- Manager detail shows exact intervals for camera review.
- Interval create/update/delete events are audited.
- Migration: `0011_supportlineinterval`.
- No new commission rule was added.

Post-Batch-1 correction completed:
- Employee does not enter score.
- Activity raw inputs support start time/end time.
- Duration is calculated server-side.
- Quantity is definition-driven.
- Unit comes from ActivityType.
- Score remains server-side.
- Manager review shows raw operational data.
- Score tampering protection tested.

## Latest Migration
0011_supportlineinterval

## Validation
62 PostgreSQL tests passing.
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
Employee activity entry is raw operational reporting:

Activity Type
+ Date
+ Start Time
+ End Time
+ Quantity when required
+ Employee Note when allowed
+ Evidence when required

Employee MUST NOT enter score, points, multiplier or final score.

Scoring is server-side.
Commission uses approved eligible scored activities only.

## Next Product Area
Before major implementation, finalize:
- violation logic
- scoring rules based on raw activity data
- employee levels
- commission calculation and breakdown

Do not assume all Activity Types use the same scoring formula.

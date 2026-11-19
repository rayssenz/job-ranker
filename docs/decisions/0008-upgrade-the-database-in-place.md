# Upgrade the database in place, one version at a time

Status: accepted
Date: 2026-11-19

## Context

The database is created by milestone 1 with schema version 1 and fills with postings on every run. Later milestones need more tables. The stored postings carry the first-seen time of each posting, which cannot be fetched again, so the file cannot be thrown away and rebuilt.

## Decision

* The schema version is kept in `PRAGMA user_version`.
* Each version has one step of SQL that brings a database from the version before it. A new file runs every step. An older file runs the steps it lacks.
* The steps and the new version number are applied in one transaction when the database is opened.
* A step only adds tables, columns or indexes. It does not rewrite stored postings.
* A file with a version above the one the program knows is refused. So is a file that holds tables and no version.

## Consequences

* A database keeps its postings, versions and run log across program versions.
* An upgrade that is stopped or fails leaves the file at its old version.
* An older program version refuses a database that a newer one has upgraded. There is no step back.
* The schema of every shipped version stays in the tests, so each upgrade is tested against a file of that version.
* A change that has to rewrite stored rows needs its own decision.

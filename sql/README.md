# SQL Workspace

This directory contains auxiliary SQL files used during Whatte development.

## Purpose

These SQL files are used for:

- ingestion inspection
- analytics exploration
- metrics validation
- schema understanding
- prototyping derived calculations

## Structure

- `analytics/` — metric and aggregation queries
- `ingestion/` — queries related to webhook, jobs and raw activity flow
- `scratch/` — temporary or exploratory SQL files

## Notes

These files are not the primary migration mechanism unless explicitly stated.

Production schema evolution should be managed separately from this directory.

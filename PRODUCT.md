# Community Events Hub

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Python 3.12 standard library, SQLite, static HTML/CSS/JavaScript. No dependencies.

## Users

A single local coordinator reviewing an invented community maker collective.

## Product Purpose

Keep speaker profiles, event schedules, invitations and appearance logistics linked. Confirm an appearance only when capacity and the speaker's other commitments permit it.

## Operating Context

Public portfolio demonstration, with entirely fictional aliases and records. Local loopback execution only; no production authentication or deployment claims.

## Capabilities and Constraints

Search events and members; follow links between profiles, engagements and events; edit profiles and event times; confirm or decline invitations; preserve per-appearance logistics; reject stale writes and conflicting confirmed appearances atomically. Persistence survives restart and sample records seed only once. No external assets, telemetry, or browser-driven verification.

## Product Principles

Relationships are navigable. A rejected change explains the conflict. Scheduling rules hold at the database transaction boundary. Edits retain unrelated logistics.

## Evidence on Hand

An original implementation and synthetic sample data only. The brief supplies the product requirements; the coordinator scene is an implementation assumption. User-directed proceed-now replaces the design interview.

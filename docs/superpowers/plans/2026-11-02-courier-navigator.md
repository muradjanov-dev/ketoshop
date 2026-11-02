# Courier Navigator Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for this single cohesive task.

**Goal:** Open individual and complete courier routes in Yandex Navigator.
**Architecture:** Reuse the admin page's ordering/location and HTTPS app bridge.
**Tech stack:** Vanilla JavaScript, aiohttp, Python unittest and Node VM fixtures.
**Spec:** `docs/superpowers/specs/2026-11-02-courier-navigator-design.md`.

## Constraints and review focus

- No production data writes or real sends in tests.
- Cover Android intents, iOS app launches, desktop fallback and missing apps.
- Cover all active statuses, invalid/missing pins and pickup exclusions.
- Cover over 25 stops, known origin and preservation through Android fallback.
- Direct map taps launch once; restoration and board polling never do.
- Nearest-first order requires location permission; manual choices remain intact.

## Task 1: Complete route and Navigator launch

Files: `webapp/admin.html`, `webapp/nav.html`, `tests/courier_route_check.js`,
`tests/test_courier_route.py`, `tests/nav_bridge_check.js`, `tests/test_nav_bridge.py`.

Interfaces: `kbRouteLegs(stops)` returns one complete route link;
`kbOpenRoute()` launches the current ordered route;
`kbAppUrl(pins)` supplies `/nav?p=...&from=...` when origin is known.

- [ ] Add regression cases for Navigator as the first app, complete 30-stop
  links, all active statuses and origin propagation; run them and observe failures.
- [ ] Make Navigator the automatic Android/iOS launch, offer installation on
  failure and retain Maps as a manually chosen fallback.
- [ ] Replace chunked links with a complete route and launch it only from
  deliberate map-tab taps. Reuse nearest-next ordering for the expanded candidates.
- [ ] Run `test_courier_route.py`, `test_nav_bridge.py`, then all CI commands.
- [ ] Review the whole change, fix material findings, commit and open one PR.
- [ ] After checks, release and verify image SHA, health and deployed route tests.

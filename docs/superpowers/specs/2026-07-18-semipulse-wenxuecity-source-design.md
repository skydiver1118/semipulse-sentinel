# SemiPulse Wenxuecity Source Design

**Date:** 2026-07-18  
**Status:** Approved by the user's standing instruction to proceed without another
approval prompt

## Goal

Use `https://bbs.wenxuecity.com/cfzh/97669.html` as the authoritative
SemiPulse source. Copy the charts embedded in that post into the report without
recreating them from finance data. Going forward, check for a newer relevant chart
post on completed U.S. trading sessions, copy its embedded images unchanged, and
keep the most recent successful report when no qualifying update exists.

## Confirmed source

The source post is `狼来了的故事`, published by `云起千百度` on
2026-07-17. Its `#msgbodyContent` contains eight JPEG images in this order:

1. BofA Chart 3 - semiconductor ETF cumulative inflows
2. BofA Chart 12 - hyperscaler free-cash-flow forecasts
3. BofA Chart 15 - flows to technology equity funds
4. BofA Charts 19 and 21 - private-client equity and cash allocations
5. BofA Chart 25/Table 4 - Bull & Bear Indicator
6. Yahoo Finance QQQ daily chart screenshot
7. Yahoo Finance SPY daily chart screenshot
8. Yahoo Finance SMH daily chart screenshot

The images are hosted at Wenxuecity upload URLs that redirect to
`cdn.wenxuecity.net`. The CDN responses are immutable, year-cacheable JPEG objects
with stable byte lengths, ETags, and filenames. The post HTML is not cached and can
be checked for edits. This means the report can preserve the exact uploaded bytes,
but the existing image URLs themselves will not refresh in place.

## Refresh approach

The selected refresh strategy has two checks:

1. Re-read the seed post for edits or additional embedded images.
2. Read the public author archive for `云起千百度` in the `财富智汇` forum and
   inspect newer, non-reply posts.

A newer post qualifies only when all of these are true:

- its canonical URL is `https://bbs.wenxuecity.com/cfzh/<digits>.html`;
- it is a top-level post by the exact author, not a `#跟帖#` reply;
- its publish date is later than the currently published source post, or it is a
  revision of that same post with a changed ordered image manifest;
- its title/body contains at least one semiconductor marker:
  `半导体`, `semiconductor`, `SOX`, `SOXL`, or `SMH`;
- its `#msgbodyContent` contains one to twelve direct uploaded JPEG/PNG images;
- every image passes host, redirect, type, size, dimensions, and hash checks.

The scanner examines only the first archive page and at most the five newest
top-level posts. It never crawls replies, unrelated authors, older archive pages,
or arbitrary external image hosts.

If no qualifying update exists, the workflow returns `unchanged` and does not
deploy or email. This is the required last-known-good fallback, not an error.

## Report contract

The public report contains:

- source post title, author, URL, publication time, and optional edit time;
- a `Copied from source - not recreated` badge;
- every qualifying post-body image in original order and original bytes;
- original image URL, local filename, SHA-256, byte length, dimensions, and MIME
  type in `report.json`;
- a statement that labels and interpretations belong to the source image;
- the permanent GitHub Pages link and research-only disclosure.

The report does not calculate prices, redraw candles, reproduce the BofA series,
or use yfinance/matplotlib in its production path. It does not claim that a source
image is current beyond the source post's date.

## Scheduling and publication

GitHub Actions runs at 6:20 PM `America/New_York` Monday through Friday. The job
uses the XNYS exchange calendar to determine whether the current New York date is a
completed trading session. Weekends and exchange holidays exit successfully without
network scanning, deployment, or email.

On a trading session the job:

1. fetches and validates the current public `report.json`;
2. checks the seed post and bounded author feed;
3. downloads a qualifying source image set directly;
4. builds and validates an atomic candidate site;
5. compares post identity, ordered image hashes, and source publication time;
6. deploys only for `new` or `revised`;
7. emails the canonical report link only to `1118xmb@gmail.com` after deployment.

Any HTTP, parsing, validation, build, Pages, or notification failure leaves the
previous Pages deployment intact. Notification failure does not roll back a valid
deployment, but the workflow reports it visibly.

## Network and security limits

- Page hosts: only `bbs.wenxuecity.com` over HTTPS.
- Image redirect target: only `cdn.wenxuecity.net` over HTTPS.
- Source post paths: `/cfzh/<digits>.html` only.
- Source asset paths: `/upload/album/...` with `.jpeg`, `.jpg`, or `.png` only.
- Maximum post HTML: 2 MiB.
- Maximum archive HTML: 2 MiB.
- Maximum images per post: 12.
- Maximum image: 8 MiB; minimum dimensions 600 by 350; maximum 5000 by 5000.
- Redirects are revalidated; credentials, fragments, nondefault ports, and query
  strings on source assets are rejected.
- SMTP credentials remain encrypted GitHub secrets; the recipient is fixed in code.

## Initial artifact manifest

The seed post's eight images total 613,750 bytes. Their ordered SHA-256 values are:

1. `7c88d27f564a786065c2c2c72dcd39f011bfbfbd5cd152956e6d3a7ae4c2353e`
2. `753627b42c808115516ebd92d0c185c59744165ef7dd032d876c7f1ac093f54a`
3. `6fd9d2c762cc6f2609c96ecf6b3edf18d7a65703de82c5d7bf99ed50136e8da5`
4. `ffa8176620d82c91978bd15178a17ac151ce18ea29df150230189b3d3f17c879`
5. `48eeb07ab600ddbe5340ebc94b912de92b14e72b8411dbce3cbb6ae81587ab5a`
6. `c789470038b7b5d34667364d9fe1f43cb75a37d7c30163c961dd87abeb0dffde`
7. `2be6bfabcbcb3cb7854ce7df498441d9f2fd5b45972a859e30b4c9be73a478c7`
8. `89515cb1d48bee5741b7b073b395554a216649d78e66a3d1334a840d33c0db38`

The initial source date is 2026-07-17. This same-date migration from the old
reconstructed report is allowed once because the schema changes from the legacy
eight-SVG model to the Wenxuecity source-copy model.

## Acceptance criteria

1. The live report displays all eight seed-post images in source order.
2. Every live local image hash matches the corresponding Wenxuecity object hash.
3. The production workflow contains no finance-data chart reconstruction command.
4. An unchanged post, no newer qualifying post, weekend, or holiday preserves the
   previous report without blank output.
5. A newer valid semiconductor chart post replaces the full image set atomically.
6. A partial, unrelated, malformed, or unavailable source never replaces the last
   good report.
7. Successful publication sends one link email only to `1118xmb@gmail.com`.

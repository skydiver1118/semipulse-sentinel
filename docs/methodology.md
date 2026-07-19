# Methodology

SemiPulse Sentinel is a source-copy report, not a market-data chart generator.
Its public schema is `semipulse-wenxuecity-source-v1`. The initial source is
`https://bbs.wenxuecity.com/cfzh/97669.html`, whose eight embedded images are
copied byte-for-byte in their original DOM order.

## Source discovery

Each authorized scan rechecks the seed post for edits and reads the first page
of the exact author’s archive. It considers at most five newest top-level posts
and rejects replies. A candidate must have the exact author, a canonical
Wenxuecity post URL, and one of the configured semiconductor markers. The post
body must contain 1 to 12 supported JPEG or PNG images.

## Download and integrity gates

HTML and image hosts are allowlisted. Redirects may terminate only at the
Wenxuecity CDN. Each image has an 8 MiB maximum, a valid JPEG or PNG structure,
positive bounded dimensions, a recorded byte length, and a SHA-256 digest.
The local filenames are ordinal, so the report preserves source order.

The manifest records the source post ID, author, title, URL, publication date,
edit timestamp, original image URL, resolved CDN URL, content type, dimensions,
byte length, and ordered SHA-256 values. `copied_unchanged` states that the
published assets are the downloaded source bytes.

## Publication decision

A deployment occurs for the first source-schema migration, a newer qualifying
post, or a revision whose ordered image manifest changes. A candidate with a
regressed date or source identity fails closed. When there is no newer or
revised source, the workflow performs no deployment and sends no email; the
last successful public report remains visible instead of a blank page.

## Scope

The report does not calculate returns, indicators, forecasts, or trading
signals. Chart labels and claims belong to their original source images.
Research only - not individualized investment advice or a recommendation to
buy or sell. Source material may be delayed, incomplete, or revised.

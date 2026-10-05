# Security Policy

## Supported versions

The project is pre-release. Only the latest commit on `main` is supported.

## Reporting a vulnerability

Please do **not** open a public issue for security problems. Use GitHub's private reporting
instead: on the repository page, open the **Security** tab and choose **Report a vulnerability**
(a private security advisory).

Include what you found, how to reproduce it and the version or commit. You can expect an
acknowledgement within a reasonable time; this is a volunteer project and no deadlines are
guaranteed.

## Scope

In scope: the server code in this repository (for example unsafe handling of fetched content,
path handling of the local cache, or request behaviour that could harm the source sites).

Out of scope: the content of the Gazzetta Ufficiale or Normattiva sites, and the correctness of
the legal texts. The texts returned are unofficial; only the printed Gazzetta Ufficiale is
authoritative.

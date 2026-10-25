# Verdigo Pulse — deployment-ready prototype

Independent upcoming events and market idea research tool. English/Russian UI, seven categories: Crypto, Football, Sports, Politics, Finance, AI, Gaming. No affiliation with Kash.

## Local Windows usage

Run `START_WINDOWS.bat` and open `http://localhost:8790/?version=2.0` (Python 3.9+). No Python package installs needed.

## Deploy to Render

1. Create a NEW GitHub repository named `verdigo-pulse`, and upload these files to the repository root.
2. At Render: **New → Blueprint** and select that repository. Render reads `render.yaml`. Alternatively create **New → Web Service**, connect the repo and set build command `python -m py_compile server.py`, start command `python server.py`; choose a supported Python runtime.
3. Deploy. Render gives an HTTPS URL after successful build.
4. Confirm `/`, `/api/events?days=7`, and `/api/leads` work on the public URL.

The server binds to `0.0.0.0` by default, and reads `PORT` from the hosting environment.

## Limitations

This is a research prototype. Some third-party RSS sources may deny access from datacenter IPs; failures show in source diagnostics. Scheduled events are not guaranteed comprehensive; RSS headlines are research leads and not verified event dates. No trading or automated market creation. Local favorites are stored in the user's browser, not server-side. Free Render services can sleep after inactivity; provider limits and prices may change.

Do not put credentials or tokens in this repository. Check third-party website usage rules before promoting or scaling this service.
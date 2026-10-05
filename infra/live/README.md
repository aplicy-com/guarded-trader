# infra/live

`soak-start` — the UTC instant the 72-hour clean soak is measured from (ADR-0019): the end of the
2026-10-05 VPS rebuild. `scripts/trading-mode.sh live` reads it and refuses to go live until 72 h
have passed with no risk halt raised by the system. It is a committed file, not a flag, so the
gate can only be moved by a reviewed change. Drills 1, 3 and 4 ran after this instant (kill
switch, restart persistence, a 5 min 42 s Conductor outage); they were human-driven, so they do
not count against "no system halt", but move the instant later if you want the soak to start
after them.

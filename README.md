# Community Events Hub

Coordinate participant profiles, appearances, schedules, and logistics for a fictional maker collective.

**Python 3.12+ · SQLite · JavaScript · No runtime dependencies**

[Full guide](docs/guide.md) · [Portfolio](https://github.com/dgoetz365) · [MIT license](LICENSE)

## Quick start

```sh
git clone https://github.com/dgoetz365/community-events-hub.git
cd community-events-hub
python server.py
```

Open http://127.0.0.1:8766. Fictional members and events are created on first run. Stop with Ctrl+C; records persist in `runtime/community.sqlite3`.

On Windows, `py -3.12` can replace `python`. If you already cloned the repo, start with the Python commands from its root.

## Try it

Open **Repair circle**, follow **Copper Kite** to the member profile, and try confirming the appearance. The app identifies the overlapping commitment. Follow the guide to resolve it, then inspect the appearance history.

## Engineering highlights

- **Connected records:** one appearance links a member, an event, and its logistics notes.
- **Commitment checks:** confirmation checks capacity and overlap inside one transaction; rescheduling rechecks every confirmed presenter.
- **Preserved work:** stale edits are rejected and profile or event changes retain appearance notes.

[Application and storage](server.py) · [Tests](tests/) · [Product scope](PRODUCT.md)

## Tests and scope

```sh
python -m unittest discover -s tests -v
```

A local, single-user demonstration with synthetic data, UTC event times, and a seeded roster. Authentication, calendar sync, and browser visual verification are outside the tested scope.

Built by [Daniel Goetz](https://github.com/dgoetz365) as an independent portfolio example. Employer code and data are not included.

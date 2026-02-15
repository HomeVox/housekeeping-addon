<p align="center">
  <img src="./logo.png" width="220" alt="Housekeeping by HomeVox" />
</p>

<h1 align="center">Housekeeping by HomeVox</h1>

<p align="center">
  Automated housekeeping for Home Assistant: audit and apply fixes for entities, devices, and areas.
</p>

<p align="center">
  <a href="https://github.com/HomeVox/housekeeping-addon/actions/workflows/ci.yml">
    <img src="https://github.com/HomeVox/housekeeping-addon/actions/workflows/ci.yml/badge.svg" alt="CI" />
  </a>
  <img src="https://img.shields.io/badge/version-2.0.19-blue" alt="Version 2.0.19" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License" />
  <img src="https://img.shields.io/badge/type-Home%20Assistant%20Add--on-41BDF5" alt="Home Assistant Add-on" />
</p>

**Version:** 2.0.19  
**Made by:** [HomeVox.nl](https://homevox.nl)

Housekeeping helps you keep your Home Assistant tidy by scanning your registries, proposing changes, and letting you
apply them with control and rollback.

Works great as a periodic maintenance tool after migrations, device swaps, or lots of integrations.

## Features

- Audit: detect common registry issues
- Plan: generate suggested fixes with confidence scores
- Apply: apply selected actions (approval gates for risky changes)
- Rollback: revert applied changes where possible
- Ingress UI: manage everything from the Home Assistant sidebar

## Installation

1. Add this repository in Home Assistant:
   - Settings -> Add-ons -> Add-on Store -> ⋮ -> Repositories
   - Add: `https://github.com/HomeVox/housekeeping-addon`
2. Install the **Housekeeping** add-on.
3. Enable **Start on boot** and **Watchdog** (recommended).
4. Enable **Show in sidebar** to open it quickly.

## Usage

1. Open **Housekeeping** from the sidebar.
2. Click **Analyze** to generate a plan.
3. Review the proposed actions.
4. Click **Apply** to apply the selected actions.
5. If needed, click **Rollback** to revert.

## Configuration

Configuration is done via the add-on options:

- `onbekend_area_name`: default name for an optional fallback area ("Onbekend")
- `confidence_threshold`: float between `0.5` and `1.0` (default `0.9`)
- `log_level`: `trace|debug|info|notice|warning|error|fatal`

Rules file (optional):

- Place a rules file at one of these paths:
  - `/config/ha_housekeeper/rules.yaml` (recommended)
  - `/config/ha_housekeeper_rules.yaml`
- Or set `HOUSEKEEPER_RULES_PATH` (advanced)

## Notes

- This add-on uses the Supervisor WebSocket endpoint (`ws://supervisor/core/websocket`) and requires `hassio_api: true`.
- Some actions are always marked as `requires_approval` for safety.
- Rollback restores registry fields where possible. Some actions (like creating areas) cannot be fully undone.

## Contributing

Pull requests are welcome. The repo includes:

- Ruff formatting and linting (`pyproject.toml`)
- Pre-commit hooks (`.pre-commit-config.yaml`)
- GitHub Actions CI (`.github/workflows/ci.yml`)

## License

MIT License


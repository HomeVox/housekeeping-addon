# Housekeeping

Automated housekeeping for Home Assistant by HomeVox: audit and apply fixes for entities, devices, and areas.

## Usage

1. Open **Housekeeping** from the Home Assistant sidebar.
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

- `/config/ha_housekeeper/rules.yaml` (recommended)
- `/config/ha_housekeeper_rules.yaml`


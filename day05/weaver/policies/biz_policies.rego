package after_resolution

import rego.v1

# Custom cardinality policy for the demo-services registry.
#
# The `biz.*` namespace holds high-cardinality business identifiers
# (biz.user.id, biz.order.id, biz.amount_cents, ...). They belong on logs
# (events) and individual spans, but MUST NOT become metric labels — every
# such label multiplies the metric's time-series count. This encodes, as an
# automated check, the warning in o11y_shared/events.py:
#   "Never include dynamic ids (order_id, user_id) here ... every addition
#    widens the label space for `sum by (event)` queries."
#
# Run via:  bash demo-services/scripts/weaver.sh check --policy

deny contains high_cardinality_metric_label(group.id, attr.name) if {
	group := input.groups[_]
	group.type == "metric"
	attr := group.attributes[_]
	startswith(attr.name, "biz.")
}

high_cardinality_metric_label(group_id, attr_id) := violation if {
	violation := {
		"id": "high_cardinality_metric_label",
		"type": "semconv_attribute",
		"category": "attribute",
		"group": group_id,
		"attr": attr_id,
	}
}

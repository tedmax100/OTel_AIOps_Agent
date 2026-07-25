package after_resolution

import rego.v1

# Cardinality policy for the demo-services registry.
#
# Rule 1 (namespace ban): the `biz.*` namespace holds business identifiers
# (biz.user.id, biz.order.id, ...). They belong on logs and spans, never on
# metrics.
#
# Rule 2 (value-set bound): a metric label is only safe if its value set is
# bounded *by the schema itself* — an enum with `members`, or a boolean.
# Anything else (string, int, template[...]) is unbounded as far as the
# registry is concerned, no matter what it is named.
#
# Run via:  weaver registry check -r registry -p policies

# Attributes deliberately allowed as unbounded metric labels, with the reason.
allowed_unbounded_label := {
	"gen_ai.request.model", # bounded in practice: a handful of model ids
}

bounded_label(attr) if is_object(attr.type)  # enum: type is { members: [...] }

bounded_label(attr) if attr.type == "boolean"

# --- Rule 1: biz.* must never be a metric label -----------------------------

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

# --- Rule 2: every metric label must have a bounded value set ---------------

deny contains unbounded_metric_label(group.id, attr.name) if {
	group := input.groups[_]
	group.type == "metric"
	attr := group.attributes[_]
	not bounded_label(attr)
	not allowed_unbounded_label[attr.name]
	not startswith(attr.name, "biz.") # already reported by rule 1
}

unbounded_metric_label(group_id, attr_id) := violation if {
	violation := {
		"id": "unbounded_metric_label",
		"type": "semconv_attribute",
		"category": "attribute",
		"group": group_id,
		"attr": attr_id,
	}
}

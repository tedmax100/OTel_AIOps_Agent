package after_resolution

import rego.v1

signal_group_types := {"event", "span", "metric"}

# 用到被 deprecated 的 attribute：base 改版之後，下游還在引用舊欄位
deny contains {
	"id": "uses_deprecated_attribute",
	"type": "semconv_attribute",
	"category": "upgrade",
	"group": group.id,
	"attr": sprintf("%s (deprecated: %s)", [attr.name, attr.deprecated.reason]),
} if {
	some group in input.groups
	group.type in signal_group_types
	some attr in group.attributes
	attr.deprecated
}

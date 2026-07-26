package before_resolution

import rego.v1

# 規則一：signal group（event/span/metric）不准 inline 定義 attribute，一律要用 ref。
#
# 這條只有 before_resolution 寫得出來——after_resolution 看到的 ref 已經展開，
# 分不出「這個 attribute 是 inline 寫的」還是「ref 進來的」。
#
# 為什麼要擋：inline 定義會在依賴分層裡造出一個跟 base 同名、但沒有人 ref 得到的
# 孤兒定義（見 Day8 的示範）。強制走 ref，同名這件事就會在 resolve 階段
# 變成「解不到」的硬錯誤，而不是安靜地並存。
signal_group_types := {"event", "span", "metric"}

deny contains inline_attribute_in_signal(group.id, attr.id) if {
	group := input.groups[_]
	group.type in signal_group_types
	attr := group.attributes[_]
	attr.id                        # inline 定義才有 id；ref 進來的只有 ref
}

inline_attribute_in_signal(group_id, attr_id) := violation if {
	violation := {
		"id": "inline_attribute_in_signal_group",
		"type": "semconv_attribute",
		"category": "layering",
		"group": group_id,
		"attr": attr_id,
	}
}

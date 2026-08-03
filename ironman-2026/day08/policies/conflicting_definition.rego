package after_resolution

import rego.v1

# 同一個 attribute 名字，在 resolved schema 裡出現了兩份不一樣的定義。
# 這是「團隊以為自己覆寫了 base，實際上製造了一個孤兒」的機器可讀形狀。
definitions[name] contains attr.brief if {
	group := input.groups[_]
	attr := group.attributes[_]
	name := attr.name
}

deny contains conflicting_definition(name) if {
	briefs := definitions[name]
	count(briefs) > 1
}

conflicting_definition(name) := violation if {
	violation := {
		"id": "conflicting_definition",
		"type": "semconv_attribute",
		"category": "layering",
		"group": "(registry-wide)",
		"attr": name,
	}
}

package comparison_after_resolution

import rego.v1

# 這三條規則補的是 `registry diff` 完全沒有輸出的三種變更。
#
# 這個 package 只有在 `registry check` 帶了 `--baseline-registry` 時才會跑：
#   input.groups  = 新版（-r 指的那份）
#   data.groups   = baseline（--baseline-registry 指的那份）

# --- 把兩邊的 attribute 都攤平成 name -> 定義 --------------------------------

new_attr[attr.name] := attr if {
	group := input.groups[_]
	attr := group.attributes[_]
}

old_attr[attr.name] := attr if {
	group := data.groups[_]
	attr := group.attributes[_]
}

# --- 規則一：型別改變 -------------------------------------------------------
# 舊資料還在後端裡，型別一改，查詢與 dashboard 會同時對不上。

deny contains finding("attribute_type_changed", name) if {
	old := old_attr[name]
	new := new_attr[name]
	is_string(old.type)
	is_string(new.type)
	old.type != new.type
}

# --- 規則二：enum member 被移除 ---------------------------------------------
# 對 agent 來說這是最惡劣的一種：它讀到的值域少了一個，
# 而那個值仍然會出現在歷史資料裡。

old_members[name] contains member.value if {
	old := old_attr[name]
	member := old.type.members[_]
}

new_members[name] contains member.value if {
	new := new_attr[name]
	member := new.type.members[_]
}

deny contains finding("enum_member_removed", sprintf("%s: %s", [name, value])) if {
	value := old_members[name][_]
	not new_members[name][value]
}

# --- 規則三：名字沒變，語意變了 ---------------------------------------------
# 這條最容易有爭議（改錯字也會中），所以它的價值在於「逼一次對話」，
# 不在於自動判斷對錯。

deny contains finding("brief_changed", name) if {
	old := old_attr[name]
	new := new_attr[name]
	old.brief != new.brief
}

finding(id, attr) := violation if {
	violation := {
		"id": id,
		"type": "semconv_attribute",
		"category": "breaking_change",
		"group": "(comparison)",
		"attr": attr,
	}
}

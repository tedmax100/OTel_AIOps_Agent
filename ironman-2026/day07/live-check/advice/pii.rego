package live_check_advice

import rego.v1

# Day7 的自訂 advice：把「像 PII 的欄位被送成遙測」判成 violation。
#
# 注意兩件事（文章裡有展開）：
#   1. `--advice-policies` 是覆蓋不是疊加。指定這個目錄之後，weaver 內建的
#      那幾條 Rego advice（missing_namespace / invalid_format / not_stable）
#      就不會跑了，只剩 Rust 側的 registry 比對還在。
#   2. 輸入的形狀是 `input.sample.<訊號型別>`，不是 `input.name`；產出的物件
#      要有 type / advice_type / advice_level / advice_context / message 五個
#      欄位，少一個就整條規則靜悄悄地不生效。

pii_suffixes := ["email", "phone", "ssn", "credit_card"]

deny contains make_advice("pii_on_telemetry", "violation", input.sample.attribute.name, message) if {
	input.sample.attribute
	some suffix in pii_suffixes
	endswith(input.sample.attribute.name, suffix)
	message := sprintf(
		"Attribute '%s' looks like PII; it must not leave the process as telemetry.",
		[input.sample.attribute.name],
	)
}

make_advice(advice_type, advice_level, advice_context, message) := {
	"type": "advice",
	"advice_type": advice_type,
	"advice_level": advice_level,
	"advice_context": advice_context,
	"message": message,
}

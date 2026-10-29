<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { CircleAlert, Save } from 'lucide-vue-next'
import { useRulesStore } from '../stores/rules'
import { propertyLabel, roleLabel } from '../lib/format'
import type { FormatProperty, FormatRule, JsonValue, Selector } from '../types/contracts'
import { parseRuleValue, type LineSpacingType } from '../lib/ruleValue'

const props = defineProps<{ ruleId: string | null }>()
const rules = useRulesStore()
const rule = computed(() => rules.draftRules.find((item) => item.rule_id === props.ruleId) ?? null)
const expectedText = ref('')
const exclusionsText = ref('')
const expectedError = ref<string | null>(null)
const lineSpacingType = ref<LineSpacingType>('MULTIPLE')
const selectors: Selector[] = ['body', 'heading_1', 'heading_2', 'heading_3', 'caption', 'table_text', 'section']
const properties = Object.keys({
  'font.eastAsia': 1, 'font.ascii': 1, 'font.size_pt': 1, 'font.bold': 1,
  'paragraph.alignment': 1, 'paragraph.first_line_indent_chars': 1, 'paragraph.first_line_indent_mm': 1,
  'paragraph.left_indent_mm': 1, 'paragraph.right_indent_mm': 1, 'paragraph.line_spacing': 1,
  'paragraph.space_before_pt': 1, 'paragraph.space_after_pt': 1, 'section.margin_top_mm': 1,
  'section.margin_bottom_mm': 1, 'section.margin_left_mm': 1, 'section.margin_right_mm': 1,
  'section.page_width_mm': 1, 'section.page_height_mm': 1,
}) as FormatProperty[]

watch(rule, (value) => {
  expectedText.value = value ? typeof value.expected === 'string' ? value.expected : JSON.stringify(value.expected) : ''
  if (value?.property === 'paragraph.line_spacing' && value.operator === 'eq' && value.expected && typeof value.expected === 'object' && !Array.isArray(value.expected)) {
    expectedText.value = String(value.expected.value ?? '')
    lineSpacingType.value = value.expected.type as LineSpacingType
  }
  exclusionsText.value = value?.exclusions.join('\n') ?? ''
  expectedError.value = null
}, { immediate: true })

function patch(value: Partial<FormatRule>): void {
  if (rule.value) rules.updateRule(rule.value.rule_id, value)
}

function applyExpected(): void {
  const current = rule.value
  if (!current) return
  const raw = expectedText.value.trim()
  let value: JsonValue = raw
  if (current.operator === 'in' || current.operator === 'between') {
    try {
      const parsed: unknown = JSON.parse(raw)
      if (!Array.isArray(parsed) || (current.operator === 'between' && parsed.length !== 2)) throw new Error('invalid')
      value = parsed as JsonValue[]
    } catch {
      expectedError.value = current.operator === 'between' ? 'between 需要 JSON 数组，例如 [10.5, 12]。' : 'in 需要 JSON 数组，例如 ["宋体", "黑体"]。'
      return
    }
  } else {
    try {
      value = parseRuleValue(current.property, raw, lineSpacingType.value)
    } catch (error) {
      expectedError.value = error instanceof Error ? error.message : '预期值无效。'
      return
    }
  }
  expectedError.value = null
  patch({ expected: value })
}
</script>

<template>
  <div v-if="rule" class="rule-editor">
    <div class="editor-heading"><h2>编辑规则</h2></div>
    <div class="form-field"><label class="field-label" :for="`rule-name-${rule.rule_id}`">规则名称</label><input :id="`rule-name-${rule.rule_id}`" class="field" :value="rule.name" @change="patch({ name: ($event.target as HTMLInputElement).value })" /></div>
    <div class="editor-two-columns">
      <div class="form-field"><label class="field-label" :for="`rule-selector-${rule.rule_id}`">目标角色</label><select :id="`rule-selector-${rule.rule_id}`" class="field" :value="rule.selector" @change="patch({ selector: ($event.target as HTMLSelectElement).value as Selector })"><option v-for="selector in selectors" :key="selector" :value="selector">{{ roleLabel(selector) }}</option></select></div>
      <div class="form-field"><label class="field-label" :for="`rule-severity-${rule.rule_id}`">严重程度</label><select :id="`rule-severity-${rule.rule_id}`" class="field" :value="rule.severity" @change="patch({ severity: ($event.target as HTMLSelectElement).value as FormatRule['severity'] })"><option value="ERROR">确认违规</option><option value="WARNING">警告</option><option value="INFO">信息</option></select></div>
    </div>
    <div class="form-field"><label class="field-label" :for="`rule-property-${rule.rule_id}`">格式属性</label><select :id="`rule-property-${rule.rule_id}`" class="field" :value="rule.property" @change="patch({ property: ($event.target as HTMLSelectElement).value as FormatProperty })"><option v-for="property in properties" :key="property" :value="property">{{ propertyLabel(property) }} · {{ property }}</option></select></div>
    <div class="editor-two-columns">
      <div class="form-field"><label class="field-label" :for="`rule-operator-${rule.rule_id}`">比较方式</label><select :id="`rule-operator-${rule.rule_id}`" class="field" :value="rule.operator" @change="patch({ operator: ($event.target as HTMLSelectElement).value as FormatRule['operator'] })"><option value="eq">等于</option><option value="in">属于集合</option><option value="between">位于区间</option></select></div>
      <div class="form-field"><label class="field-label" :for="`rule-tolerance-${rule.rule_id}`">容差</label><input :id="`rule-tolerance-${rule.rule_id}`" class="field" type="number" min="0" step="any" :value="rule.tolerance" @change="patch({ tolerance: Math.max(0, Number(($event.target as HTMLInputElement).value)) })" /></div>
    </div>
    <div v-if="rule.property === 'paragraph.line_spacing' && rule.operator === 'eq'" class="form-field"><label class="field-label" :for="`rule-line-type-${rule.rule_id}`">行距类型</label><select :id="`rule-line-type-${rule.rule_id}`" v-model="lineSpacingType" class="field" @change="applyExpected"><option value="MULTIPLE">倍数行距</option><option value="EXACT">固定值（pt）</option><option value="AT_LEAST">最小值（pt）</option></select></div>
    <div class="form-field"><label class="field-label" :for="`rule-expected-${rule.rule_id}`">预期值</label><input :id="`rule-expected-${rule.rule_id}`" v-model="expectedText" class="field" :aria-invalid="Boolean(expectedError)" :aria-describedby="expectedError ? `expected-error-${rule.rule_id}` : undefined" @change="applyExpected" /><span v-if="expectedError" :id="`expected-error-${rule.rule_id}`" class="field-hint text-red-700" role="alert"><CircleAlert :size="13" aria-hidden="true" /> {{ expectedError }}</span></div>
    <div class="form-field"><label class="field-label" :for="`rule-policy-${rule.rule_id}`">修复策略</label><select :id="`rule-policy-${rule.rule_id}`" class="field" :value="rule.fix_policy" @change="patch({ fix_policy: ($event.target as HTMLSelectElement).value as FormatRule['fix_policy'] })"><option value="AUTO_WITH_APPROVAL">批准后定向修复</option><option value="MANUAL_ONLY">仅人工处理</option><option value="UNSUPPORTED">不支持修复</option></select></div>
    <fieldset class="source-evidence">
      <legend>规范来源与证据</legend>
      <div class="form-field"><label class="field-label" :for="`rule-reference-${rule.rule_id}`">来源引用</label><input :id="`rule-reference-${rule.rule_id}`" class="field" :value="rule.source.reference" @change="patch({ source: { ...rule.source, reference: ($event.target as HTMLInputElement).value } })" /></div>
      <div class="form-field"><label class="field-label" :for="`rule-quote-${rule.rule_id}`">规范原句</label><textarea :id="`rule-quote-${rule.rule_id}`" class="field" :value="rule.source.quote" @change="patch({ source: { ...rule.source, quote: ($event.target as HTMLTextAreaElement).value } })" /></div>
      <div class="editor-two-columns">
        <div class="form-field"><label class="field-label" :for="`rule-page-${rule.rule_id}`">来源页码</label><input :id="`rule-page-${rule.rule_id}`" class="field" type="number" min="1" :value="rule.source.page ?? ''" @change="patch({ source: { ...rule.source, page: Number(($event.target as HTMLInputElement).value) || null } })" /></div>
        <div class="form-field"><label class="field-label" :for="`rule-confidence-${rule.rule_id}`">提取置信分数</label><input :id="`rule-confidence-${rule.rule_id}`" class="field" type="number" min="0" max="1" step="0.01" :value="rule.confidence" @change="patch({ confidence: Math.min(1, Math.max(0, Number(($event.target as HTMLInputElement).value))) })" /></div>
      </div>
    </fieldset>
    <div class="form-field"><label class="field-label" :for="`rule-exclusions-${rule.rule_id}`">排除对象（每行一个样式或段落标识）</label><textarea :id="`rule-exclusions-${rule.rule_id}`" v-model="exclusionsText" class="field exclusions" @change="patch({ exclusions: exclusionsText.split('\n').map((item) => item.trim()).filter(Boolean) })" /></div>
    <label class="checkbox-label"><input class="checkbox" type="checkbox" :checked="rule.enabled" @change="patch({ enabled: ($event.target as HTMLInputElement).checked })" /> 启用此规则</label>
    <p class="field-hint"><Save :size="13" aria-hidden="true" /> 编辑只改变本地草案；点击“保存草案”后由服务端重新计算 digest 与冲突。</p>
  </div>
  <div v-else class="empty-state"><strong>选择一条规则</strong><p>查看预期值、修复策略与规范原句。</p></div>
</template>

<style scoped>
.rule-editor { padding: 20px; }
.editor-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 20px; }
.editor-heading h2 { margin: 0; font-size: 1.35rem; }
.editor-heading > .mono { max-width: 130px; color: #748095; font-size: .68rem; }
.editor-two-columns { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.source-evidence { padding: 14px; margin: 4px 0 18px; border: 1px solid #dce2eb; border-radius: 7px; }
.source-evidence legend { padding-inline: 5px; font-size: .8rem; font-weight: 700; }
.source-evidence textarea { min-height: 100px; }
.exclusions { min-height: 82px; }
.field-hint { display: flex; align-items: flex-start; gap: 5px; }
@media (max-width: 420px) { .editor-two-columns { grid-template-columns: 1fr; } }
</style>

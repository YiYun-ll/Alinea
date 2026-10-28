import { beforeEach, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useRulesStore } from '../stores/rules'
import RuleEditorPanel from './RuleEditorPanel.vue'
import type { FormatRule } from '../types/contracts'

beforeEach(() => setActivePinia(createPinia()))

it('edits typed line spacing without converting it into an invalid scalar', async () => {
  const rules = useRulesStore()
  rules.draftRules = [{ rule_id: 'line', name: '正文行距', property: 'paragraph.line_spacing', selector: 'body', operator: 'eq', expected: { type: 'MULTIPLE', value: 1.5 }, source: { reference: '测试规范', quote: '1.5 倍行距' }, exclusions: [] } as unknown as FormatRule]
  const wrapper = mount(RuleEditorPanel, { props: { ruleId: 'line' } })
  expect((wrapper.get('#rule-expected-line').element as HTMLInputElement).value).toBe('1.5')
  await wrapper.get('#rule-expected-line').setValue('2')
  expect(rules.draftRules[0].expected).toEqual({ type: 'MULTIPLE', value: 2 })
  await wrapper.get('#rule-line-type-line').setValue('EXACT')
  expect(rules.draftRules[0].expected).toEqual({ type: 'EXACT', value: 2 })
  await wrapper.get('#rule-expected-line').setValue('')
  expect(wrapper.get('[role="alert"]').text()).toContain('请填写')
  expect(rules.draftRules[0].expected).toEqual({ type: 'EXACT', value: 2 })
})

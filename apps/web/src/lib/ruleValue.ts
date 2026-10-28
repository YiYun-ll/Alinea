import type { FormatProperty, JsonValue } from '../types/contracts'

export type LineSpacingType = 'MULTIPLE' | 'EXACT' | 'AT_LEAST'

export function parseRuleValue(property: FormatProperty, raw: string, lineType: LineSpacingType = 'MULTIPLE'): JsonValue {
  const text = raw.trim()
  if (!text) throw new Error('请填写预期值。')
  if (property === 'font.bold') {
    if (!['true', 'false'].includes(text)) throw new Error('请选择加粗或不加粗。')
    return text === 'true'
  }
  if (property === 'paragraph.line_spacing') {
    const value = Number(text)
    if (!Number.isFinite(value) || value <= 0) throw new Error('行距必须是大于 0 的数值。')
    return { type: lineType, value }
  }
  if (property === 'font.size_pt' || property.endsWith('_mm') || property.endsWith('_pt') || property.endsWith('_chars')) {
    const value = Number(text)
    if (!Number.isFinite(value)) throw new Error('请填写有效数值。')
    if ((property === 'font.size_pt' || property.startsWith('section.page_')) && value <= 0) throw new Error('此属性必须大于 0。')
    return value
  }
  if (property === 'paragraph.alignment' && !['left', 'center', 'right', 'justify', 'distribute'].includes(text)) throw new Error('请选择有效的段落对齐方式。')
  return text
}

import { describe, expect, it } from 'vitest'
import { overlaysForPage, PageCoordinateAdapter } from './pdfCoordinates'
import type { Issue } from '../types/contracts'

describe('PageCoordinateAdapter', () => {
  it('maps top-left normalized coordinates through the PDF viewport once', () => {
    const adapter = new PageCoordinateAdapter([0, 0, 612, 792], {
      convertToViewportPoint: (x, y) => [x * 2, (792 - y) * 2],
    })
    const box = adapter.toViewportRect([0.1, 0.2, 0.5, 0.3], { width: 612, height: 792 })
    expect(box).not.toBeNull()
    expect(box!.left).toBeCloseTo(122.4)
    expect(box!.top).toBeCloseTo(316.8)
    expect(box!.width).toBeCloseTo(489.6)
    expect(box!.height).toBeCloseTo(158.4)
  })

  it('includes crop-box origins and all corners for rotation', () => {
    const adapter = new PageCoordinateAdapter([10, 20, 622, 812], {
      convertToViewportPoint: (x, y) => [y, x],
    })
    const box = adapter.toViewportRect([0.1, 0.2, 0.5, 0.3], { width: 612, height: 792 })
    expect(box).not.toBeNull()
    expect(box!.width).toBeGreaterThan(0)
    expect(box!.height).toBeGreaterThan(0)
    expect(box!.left).toBeCloseTo(574.4)
    expect(box!.top).toBeCloseTo(71.2)
  })

  it('rejects malformed rectangles', () => {
    const adapter = new PageCoordinateAdapter([0, 0, 612, 792], {
      convertToViewportPoint: (x, y) => [x, y],
    })
    expect(adapter.toViewportRect([0.8, 0.2, 0.2, 0.3], { width: 612, height: 792 })).toBeNull()
  })
})

function issue(revision: string, sha: string): Issue {
  return {
    issue_id: 'issue-1', inspection_id: 'inspection-1', revision_id: revision,
    rule_id: 'body-size', property: 'font.size_pt',
    element_ref: {
      revision_id: revision, part_uri: '/word/document.xml', kind: 'paragraph',
      xml_path: '/w:document/w:body/w:p[1]', container_path: [], paragraph_ordinal: 0,
      run_range: null, section_ordinal: null, para_id: null, text_sha256: 'sha',
      context_before_sha256: null, context_after_sha256: null, text_excerpt: 'text',
      anchor_schema_version: '1.0',
    },
    actual: { value: 10.5, unit: 'pt', origin: 'DIRECT', raw_ooxml_value: null, reason: null },
    expected: { value: 12, unit: 'pt', origin: 'RULE', raw_ooxml_value: null, reason: null },
    detection_status: 'CONFIRMED_VIOLATION', severity: 'ERROR',
    repair: { eligibility: 'SAFE_SINGLE_TARGET', requires_approval: true, reason: null },
    location: {
      issue_id: 'issue-1', revision_id: revision, preview_pdf_sha256: sha,
      renderer_profile_id: 'test', status: 'LOCATED', page_index: 0,
      fragments: [{ page_index: 0, page_size_pt: { width: 612, height: 792 }, rects_normalized: [[0.1, 0.2, 0.5, 0.3]] }],
      score: 0.99, candidate_count: 1, anchor_excerpt: 'text', method: 'TEST', reason: null,
    },
    source: { source_type: 'preset', reference: 'test', page: null, quote: '12pt', extraction_confidence: null },
    fingerprint: 'fingerprint', fix_status: 'OPEN',
  }
}

describe('overlaysForPage', () => {
  it('binds overlays to revision and exact preview SHA', () => {
    const current = issue('rev-1', 'sha-1')
    expect(overlaysForPage([current], 'rev-1', 0, 'sha-1')).toHaveLength(1)
    expect(overlaysForPage([current], 'rev-2', 0, 'sha-1')).toHaveLength(0)
    expect(overlaysForPage([current], 'rev-1', 0, 'sha-2')).toHaveLength(0)
    expect(overlaysForPage([current], 'rev-1', 1, 'sha-1')).toHaveLength(0)
  })
})

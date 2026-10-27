import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from './api'
import { errorMessage } from './format'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('errorMessage', () => {
  it('prioritizes the API error code over an English server message', () => {
    const error = new ApiError('The plan base is stale', 409, 'STALE_REPAIR_PLAN', false)
    expect(errorMessage(error)).toBe('修复计划已失效，请返回检查并重新创建计划。')
  })

  it('localizes common HTTP failures and network errors', () => {
    expect(errorMessage(new ApiError('Not found', 404, 'HTTP_ERROR', false))).toBe('请求的内容不存在或已过期。')
    expect(errorMessage(new ApiError('Too many requests', 429, 'HTTP_ERROR', true))).toBe('操作过于频繁，请稍后重试。')
    expect(errorMessage(new TypeError('Failed to fetch'))).toBe('无法连接服务器，请检查网络后重试。')
  })

  it('does not expose unknown English errors and preserves Chinese context', () => {
    expect(errorMessage(new Error('Unexpected internal exception'))).toBe('操作未完成，请稍后重试。')
    expect(errorMessage(new Error('PDF parsing failed'), 'PDF 无法加载，请重试。')).toBe('PDF 无法加载，请重试。')
    expect(errorMessage(new Error('规范已变化，请重新检查。'))).toBe('规范已变化，请重新检查。')
  })

  it('converts fetch rejection into a retryable Chinese API error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const request = api.createDemo()
    await expect(request).rejects.toMatchObject({ code: 'NETWORK_ERROR', retryable: true })
    await request.catch((error: unknown) => {
      expect(errorMessage(error)).toBe('无法连接服务器，请检查网络后重试。')
    })
  })
})

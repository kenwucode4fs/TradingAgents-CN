
/**
 * 策略回测API
 */

import { request, type ApiResponse } from './request'

// 回测请求参数
export interface BacktestRunRequest {
  strategy_id?: string
  strategy_name?: string
  symbols?: string[]
  start_date?: string
  end_date?: string
  initial_capital?: number
  parameters?: Record<string, any>
  [key: string]: any
}

// 回测任务创建响应
export interface BacktestTaskResponse {
  task_id: string
  status?: string
  message?: string
  [key: string]: any
}

// 回测任务状态
export interface BacktestStatus {
  task_id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  progress?: number
  message?: string
  [key: string]: any
}

// 回测历史查询参数
export interface BacktestHistoryParams {
  page?: number
  page_size?: number
  status?: string
  [key: string]: any
}

// 策略回测API
export const backtestApi = {
  // 发起回测任务
  run(payload: BacktestRunRequest): Promise<ApiResponse<BacktestTaskResponse>> {
    return request.post('/api/backtest/run', payload)
  },

  // 查询回测任务状态
  status(taskId: string): Promise<ApiResponse<BacktestStatus>> {
    return request.get(`/api/backtest/status/${taskId}`)
  },

  // 获取回测结果
  result(taskId: string): Promise<ApiResponse<any>> {
    return request.get(`/api/backtest/result/${taskId}`)
  },

  // 获取回测历史
  history(params?: BacktestHistoryParams): Promise<ApiResponse<any>> {
    return request.get('/api/backtest/history', { params })
  }
}

export default backtestApi

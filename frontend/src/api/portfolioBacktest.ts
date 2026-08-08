
/**
 * 组合回测API
 */

import { request, type ApiResponse } from './request'
import type { FactorConfigItem } from './factorScreening'

// 组合回测请求参数（与后端 app/routers/portfolio_backtest.py 校验的字段一致）
export interface PortfolioBacktestRunRequest {
  factors: FactorConfigItem[]
  start_date: string
  end_date: string
  top_n: number
  initial_capital: number
  cost?: number
}

// 组合回测任务创建响应
export interface PortfolioBacktestTaskResponse {
  task_id: string
  status?: string
  message?: string
  [key: string]: any
}

// 组合回测任务状态
export interface PortfolioBacktestStatus {
  task_id: string
  status: 'running' | 'done' | 'failed'
  progress?: number
  message?: string
  error?: string
  [key: string]: any
}

// 组合回测历史查询参数
export interface PortfolioBacktestHistoryParams {
  page?: number
  page_size?: number
  status?: string
  [key: string]: any
}

// 组合回测API
export const portfolioApi = {
  // 发起组合回测任务
  run(payload: PortfolioBacktestRunRequest): Promise<ApiResponse<PortfolioBacktestTaskResponse>> {
    return request.post('/api/portfolio-backtest/run', payload)
  },

  // 查询组合回测任务状态
  status(taskId: string): Promise<ApiResponse<PortfolioBacktestStatus>> {
    return request.get(`/api/portfolio-backtest/status/${taskId}`)
  },

  // 获取组合回测结果
  result(taskId: string): Promise<ApiResponse<any>> {
    return request.get(`/api/portfolio-backtest/result/${taskId}`)
  },

  // 获取组合回测历史
  history(params?: PortfolioBacktestHistoryParams): Promise<ApiResponse<any>> {
    return request.get('/api/portfolio-backtest/history', { params })
  }
}

export default portfolioApi

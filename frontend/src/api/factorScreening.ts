
/**
 * 多因子选股API
 */

import { request, type ApiResponse } from './request'

// 单个因子的打分配置：key 为因子标识，weight 为正数权重，direction 为打分方向
export interface FactorConfigItem {
  key: string
  weight: number
  direction: 'asc' | 'desc'
}

// 选股域筛选条件，均为可选：不传/为空表示该维度不过滤
export interface FactorUniverse {
  exclude_st?: boolean
  exclude_new?: boolean
  industries?: string[]
  mv_min?: number
  mv_max?: number
}

// 因子选股请求参数（与后端 app/routers/factor_screening.py `_validate` 校验的字段一致）
export interface FactorScreenRunRequest {
  factors: FactorConfigItem[]
  universe: FactorUniverse
  top_n: number
}

// 因子选股任务创建响应
export interface FactorScreenTaskResponse {
  task_id: string
  status?: string
  message?: string
  [key: string]: any
}

// 因子选股任务状态
export interface FactorScreenStatus {
  task_id: string
  status: 'running' | 'done' | 'failed'
  progress?: number
  message?: string
  error?: string
  [key: string]: any
}

// 因子选股历史查询参数
export interface FactorScreenHistoryParams {
  page?: number
  page_size?: number
  status?: string
  [key: string]: any
}

// 多因子选股API
export const factorApi = {
  // 获取可用因子列表
  factors(): Promise<ApiResponse<any>> {
    return request.get('/api/factor-screen/factors')
  },

  // 发起选股任务
  run(payload: FactorScreenRunRequest): Promise<ApiResponse<FactorScreenTaskResponse>> {
    return request.post('/api/factor-screen/run', payload)
  },

  // 查询选股任务状态
  status(taskId: string): Promise<ApiResponse<FactorScreenStatus>> {
    return request.get(`/api/factor-screen/status/${taskId}`)
  },

  // 获取选股结果
  result(taskId: string): Promise<ApiResponse<any>> {
    return request.get(`/api/factor-screen/result/${taskId}`)
  },

  // 获取选股历史
  history(params?: FactorScreenHistoryParams): Promise<ApiResponse<any>> {
    return request.get('/api/factor-screen/history', { params })
  }
}

export default factorApi

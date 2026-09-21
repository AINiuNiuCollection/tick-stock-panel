
"D:\CodeHub\github-tick-stock\tick-stock-panel\frontend\src\lib\api.ts"

export interface DataSourceItem {
  name: string
  display_name: string
  datasets: string[]
  path?: string | null
}

/** 内置可选插件数据源 (plugins/ 目录, 需手动装依赖) */
export interface PluginConfigField {
  key: string
  label: string
  type: 'path' | 'string' | 'int' | 'bool' | 'select'
  required?: boolean
  default?: string
  help?: string
  options?: string[]      // type=select 时的候选值
}

export interface PluginDataSourceItem {
  name: string
  display_name: string
  datasets: string[]
  runtime: string          // node | python | none
  available: boolean       // 依赖是否已安装
  status: string           // 可用性原因 (供 UI 显示)
  description: string
  install_hint: string     // 未装依赖时显示的安装命令
  homepage?: string        // 插件官网/申请地址 (manifest 可选声明)
  api_key_env?: string     // 声明后设置页提供 Key 输入框 (先探后存)
  api_key_masked?: string  // 当前生效 Key 的脱敏串 (secrets.json 优先, .env 兜底; 与 TickFlow Key 同一展示契约)
  config_fields?: PluginConfigField[]  // 声明后设置页提供路径/字符串等配置表单 (先探后存)
}

export interface PluginConfigResult {
  ok: boolean
  plugin_name?: string
  config?: Record<string, string | number | boolean | null>
  config_fields?: PluginConfigField[]
  plugin_available?: boolean
  plugin?: PluginDataSourceItem | null
  reason?: string
  error?: string
}

/** 数据源路由偏好字段 (每个能力一个, 与后端能力注册表一一对应) */









*******************************************************************************************************************************

  savePluginKey: (plugin: string, apiKey: string) => {
    // 先探后存: 后端会用候选 Key 实探一次, 探测超时 10s + 余量
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 30_000)
    return request<PluginKeyResult>('/api/settings/plugin-key', {
      method: 'POST',
      body: JSON.stringify({ plugin, api_key: apiKey }),
      signal: controller.signal,
    }).finally(() => clearTimeout(timer))
  },
  clearPluginKey: (plugin: string) =>
    request<PluginKeyResult>(`/api/settings/plugin-key/${encodeURIComponent(plugin)}`, { method: 'DELETE' }),
  getPluginConfig: (plugin: string) =>
    request<PluginConfigResult>(`/api/settings/plugin-config/${encodeURIComponent(plugin)}`),
  savePluginConfig: (plugin: string, config: Record<string, string | number | boolean | null>) =>
    request<PluginConfigResult>('/api/settings/plugin-config', {
      method: 'POST',
      body: JSON.stringify({ plugin, config }),
    }),
  testDataSource: (
    provider: string,
    dataset: string,
    symbols?: string[],
    config?: CustomSourceConfig,
  ) =>
    request<DataSourceTestResult>('/api/settings/data-sources/test', {
      method: 'POST',
      body: JSON.stringify({ provider, dataset, symbols, config }),
    }),
  updateDataProviders: (cfg: Partial<Pick<Preferences, ProviderField>>) =>
    request<Pick<Preferences, ProviderField>>(
      '/api/settings/preferences/data-providers',
      { method: 'PUT', body: JSON.stringify(cfg) },
    ),

export interface StatusResponse {
  status: string;
  timestamp: string;
  database: 'sqlite' | 'postgresql' | string;
  container: string;
  read_only: boolean;
  version: string;
}

export interface ContainerListResponse {
  containers: string[];
}

export interface ContainerSpec {
  project: string;
  service: string;
  image: string;
  container_name: string;
  base_image: string;
  working_dir: string;
  user: string;
  entrypoint: string[];
  command: string[];
  profiles: string[];
  restart: string;
  ports: string[];
  volumes: string[];
  env: Record<string, string>;
  api_key_envs: string[];
  include_db: boolean;
  db_image: string;
  db_volume: string;
  // What the container carries and runs.
  config_file: string;
  goal: string;
  goal_file: string;
  goal_mode: 'mount' | 'bake' | 'stdin';
  run_hive: string;
  run_init: boolean;
  entrypoint_file: string;
  include_web: boolean;
  web_service_name: string;
}

export interface ContainerPlanResponse {
  spec: ContainerSpec;
  compose: string;
  dockerfile: string;
  config: string;
  entrypoint: string;
  goal: string;
  pipeline_command: string[];
  warnings: string[];
  docker_available: boolean;
  project_dir: string;
  compose_exists: boolean;
  dockerfile_exists: boolean;
  config_exists: boolean;
  goal_exists: boolean;
}

export interface ContainerSaveResponse {
  success: boolean;
  saved: string[];
  warnings: string[];
  project_dir: string;
}

export interface ContainerSaveRequest {
  compose: string;
  dockerfile: string;
  config?: string;
  entrypoint?: string;
  goal?: string;
  spec?: ContainerSpec;
}

export interface Provider {
  id: number;
  alias: string;
  provider_type: string;
  base_url: string | null;
  api_key_env: string;
  default_model: string | null;
  assistant_model: string | null;
  available_models: string[];
  context_window_tokens: number;
  input_cost_per_1m: number;
  output_cost_per_1m: number;
}

export interface ProviderModelsResponse {
  alias: string | null;
  models: string[];
  persisted: boolean;
}

export interface ProviderModelTestRequest {
  alias?: string | null;
  provider_type: string;
  base_url?: string | null;
  api_key_env: string;
  model?: string | null;
}

export interface ProviderModelTestResponse {
  success: boolean;
  detail: string;
  model: string | null;
  latency_ms: number;
}

export interface ProviderCreate {
  alias: string;
  provider_type: string;
  base_url?: string | null;
  api_key_env: string;
  default_model?: string | null;
  assistant_model?: string | null;
  input_cost_per_1m: number;
  output_cost_per_1m: number;
  context_window_tokens: number;
}

export interface ProviderUpdate {
  provider_type?: string;
  base_url?: string | null;
  api_key_env?: string;
  default_model?: string | null;
  assistant_model?: string | null;
  input_cost_per_1m?: number;
  output_cost_per_1m?: number;
  context_window_tokens?: number;
}

export interface Bee {
  id: number;
  name: string;
  role_description: string;
  system_prompt: string;
  provider_id: number;
  provider_alias: string | null;
  model_name: string;
  temperature: number;
  thinking_level: string;
  tool_names: string[];
  require_approval: string[];
}

export interface BeeCreate {
  name: string;
  role_description: string;
  system_prompt: string;
  provider_id: number;
  model_name: string;
  temperature: number;
  thinking_level: string;
  tool_names: string[];
  require_approval: string[];
}

export interface BeeUpdate {
  role_description?: string;
  system_prompt?: string;
  provider_id?: number;
  model_name?: string;
  temperature?: number;
  thinking_level?: string;
  tool_names?: string[];
  require_approval?: string[];
}

export interface Hive {
  id: number;
  name: string;
  goal_description: string | null;
  supervisor_provider_id: number;
  supervisor_provider_alias: string | null;
  supervisor_model_name: string;
  supervisor_prompt: string | null;
  supervisor_thinking_level: string;
  is_dynamic: boolean;
  project_path: string | null;
  bee_names: string[];
  bee_ids: number[];
}

export interface HiveCreate {
  name: string;
  goal_description?: string | null;
  supervisor_provider_id: number;
  supervisor_model_name: string;
  supervisor_prompt?: string | null;
  supervisor_thinking_level: string;
  is_dynamic: boolean;
  project_path?: string | null;
  bee_ids: number[];
}

export interface HiveUpdate {
  goal_description?: string | null;
  supervisor_provider_id?: number;
  supervisor_model_name?: string;
  supervisor_prompt?: string | null;
  supervisor_thinking_level?: string;
  is_dynamic?: boolean;
  project_path?: string | null;
  bee_ids?: number[];
}

export interface ToolSchema {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
}

export interface ToolsResponse {
  tools: ToolSchema[];
}

export interface Skill {
  id: number;
  name: string;
  description: string;
  instructions: string;
  tags: string[];
  source_thread_id: string | null;
  usage_count: number;
}

export interface ConfigYamlResponse {
  yaml: string;
}

export interface RunCreate {
  scope: 'hive' | 'bee' | 'assistant';
  entity_name: string;
  prompt: string;
  thread_id?: string | null;
  container_name?: string | null;
  approval_mode?: string | null;
  thinking?: string | null;
  provider_id?: number | null;
  model?: string | null;
}

export interface RunResponse {
  thread_id: string;
  status: string;
}

export interface TraceSummary {
  container: string;
  thread_id: string;
  status: string;
  mode: string;
  goal: string;
  hive_name: string | null;
  entity_name: string;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  duration_ms: number | null;
  pending_approvals: number;
  started_at: string | null;
  completed_at: string | null;
}

export interface ApprovalRecord {
  id: number;
  container_name: string;
  thread_id: string;
  checkpoint_id: string | null;
  hive_name: string | null;
  bee_name: string;
  tool_name: string;
  tool_call_id: string;
  approval_mode: string;
  decision: string;
  wait_ms: number | null;
  original_args: Record<string, unknown>;
  final_args: Record<string, unknown> | null;
  reason: string | null;
  requested_at: string | null;
  resolved_at: string | null;
}

export interface TraceMessageItem {
  role: string;
  label: string;
  content: string;
}

export interface TraceNodeMetrics {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  latency_ms: number;
  model?: string;
  provider?: string;
  estimated_cost_usd?: number;
}

export interface TraceNode {
  id: string;
  checkpoint_id: string | null;
  parent_checkpoint_id: string | null;
  step_index: number;
  node: string;
  target: string | null;
  action_type: string;
  status: string;
  timestamp: string | null;
  payload_summary: string;
  messages: TraceMessageItem[];
  tool_io: Record<string, unknown> | null;
  approval_info: ApprovalRecord[];
  metrics: TraceNodeMetrics | null;
  checkpoint_state: Record<string, unknown> | null;
}

export interface TraceDetail {
  container: string;
  thread_id: string;
  status: string;
  mode: string;
  goal: string;
  hive_name: string | null;
  entity_name: string;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
  total_latency_ms: number;
  started_at: string | null;
  completed_at: string | null;
  has_checkpoints: boolean;
  nodes: TraceNode[];
  approvals: ApprovalRecord[];
  events: TraceStreamEvent[];
}

export interface TraceStreamEvent {
  timestamp: string;
  thread_id: string;
  hive_name: string;
  run_id: number | null;
  event_type: string;
  source: string;
  target: string | null;
  payload: Record<string, unknown>;
}

export interface ReplayRequest {
  checkpoint_id: string;
  patch_message?: string | null;
  approval_mode?: string | null;
}

export interface ReplayResponse {
  thread_id: string;
  forked_from: string;
  status: string;
}

export interface ApprovalListResponse {
  approvals: ApprovalRecord[];
}

export interface ApprovalResolveRequest {
  action: 'approve' | 'edit' | 'reject';
  args?: Record<string, unknown> | null;
  reason?: string | null;
}

export interface ApprovalResolveResponse {
  success: boolean;
  thread_id: string;
  checkpoint_id: string;
  resumed: boolean;
  status: string;
}

export interface MemoryItem {
  id: number;
  namespace: string;
  key: string;
  content: string;
  source_thread_id: string | null;
  updated_at: string | null;
}

export interface MemoryListResponse {
  memories: MemoryItem[];
  namespaces: string[];
}

export interface MemoryCreate {
  namespace: string;
  key: string;
  content: string;
}

export interface ArtifactItem {
  path: string;
  name: string;
  hive: string | null;
  size: number;
  modified: string;
}

export interface ArtifactListResponse {
  artifacts: ArtifactItem[];
  hives: string[];
}

export interface ResetTarget {
  path: string;
  kind: 'file' | 'directory';
  group: 'config' | 'output';
  label: string;
  entries: number;
  size: number;
}

export interface ResetPlanResponse {
  config_dir: string;
  include_artifacts: boolean;
  targets: ResetTarget[];
  notes: string[];
}

export interface ResetRequest {
  include_artifacts: boolean;
  confirmed: boolean;
}

export interface ResetResponse {
  success: boolean;
  removed: string[];
  failed: string[];
  notes: string[];
  restart_required: boolean;
}

export interface TemplateItem {
  name: string;
  description: string;
  yaml: string;
  counts: Record<string, number>;
  conflicts: Record<string, string[]>;
}

export interface TemplateAction {
  section: string;
  name: string;
  action: 'create' | 'update' | 'kept';
}

export interface TemplateApplyRequest {
  template: string;
  on_conflict: 'skip' | 'overwrite';
  confirmed: boolean;
}

export interface TemplateApplyResponse {
  success: boolean;
  template: string;
  on_conflict: string;
  actions: TemplateAction[];
  detail?: string;
}

export interface DetectedProvider {
  alias: string;
  provider_type: string;
  api_key_env: string;
  base_url: string | null;
  default_model: string | null;
  source_label: string;
  registered: boolean;
}

export interface ProviderDetectionResponse {
  candidates: DetectedProvider[];
  first_launch: boolean;
}

export interface ProviderRegisterResponse {
  success: boolean;
  registered: string[];
  skipped: string[];
}

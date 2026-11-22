export interface ShopInfo {
  id: string;
  slug: string;
  name: string;
  currency: string;
  default_language: string;
}

export interface StaffUser {
  id: string;
  email: string;
  full_name: string;
  role: "admin" | "agent" | "viewer";
}

export interface LoginResponse {
  access_token: string;
  expires_in: number;
  user: StaffUser;
  shop: ShopInfo;
}

export interface RunSummary {
  id: string;
  started_at: string;
  mode: "full" | "offline";
  trigger: string;
  total_cases: number;
  passed_cases: number;
  overall: Record<string, number> | null;
  config: Record<string, unknown>;
}

export interface Overview {
  period_days: number;
  conversations: { total: number; resolved: number; escalated: number; active: number };
  replies: {
    total: number;
    avg_latency_ms: number;
    p95_latency_ms: number;
    cost_usd: number;
    unknown: number;
    refused: number;
    answered: number;
  };
  models: {
    model: string;
    tier: string;
    calls: number;
    prompt_tokens: number;
    completion_tokens: number;
    cost_usd: number;
    avg_latency_ms: number;
    fallback_calls: number;
    failed_calls: number;
  }[];
  per_day: { day: string; conversations: number; escalated: number }[];
  languages: { language: string; replies: number }[];
  tools: { tool: string; status: string; calls: number }[];
  latest_eval: RunSummary | null;
}

export interface ConversationListItem {
  id: string;
  status: "open" | "resolved" | "escalated";
  language: string | null;
  channel: string;
  customer_id: string | null;
  message_count: number;
  started_at: string;
  last_message_at: string;
  preview: string;
}

export interface ConversationMessage {
  id: string;
  role: "user" | "assistant" | "human_agent";
  content: string;
  language: string | null;
  created_at: string;
  latency_ms: number | null;
  model: string | null;
  tier: string | null;
  cost_usd: number;
  confidence: number | null;
  outcome: string | null;
  sources: { id: string; title: string; heading: string; snippet: string; score: number }[];
  products: { sku: string; name?: string; price?: string; currency?: string; stock_status?: string }[];
  flags: Record<string, unknown>;
  prompt_tokens: number;
  completion_tokens: number;
}

export interface ConversationDetail {
  id: string;
  status: ConversationListItem["status"];
  language: string | null;
  channel: string;
  started_at: string;
  customer_id: string | null;
  messages: ConversationMessage[];
  tool_calls: {
    id: string;
    message_id: string | null;
    tool: string;
    status: string;
    error: string | null;
    arguments: Record<string, unknown>;
    latency_ms: number;
    created_at: string;
  }[];
  tickets: { ticket_number: string; subject: string; status: string; priority: string; is_escalation: boolean; created_at: string }[];
  llm_calls: {
    purpose: string;
    provider: string;
    model: string;
    tier: string;
    prompt_tokens: number;
    completion_tokens: number;
    cost_usd: number;
    latency_ms: number;
    success: boolean;
    fallback_used: boolean;
  }[];
}

export interface KnowledgeDocument {
  id: string;
  title: string;
  filename: string;
  content_type: string;
  doc_type: string;
  language: string | null;
  size_bytes: number;
  status: "pending" | "processing" | "ready" | "failed";
  error: string | null;
  chunk_count: number;
  quarantined_chunks: number;
  created_at: string;
  processed_at: string | null;
}

export interface RetrievalDebug {
  query: string;
  queries: Record<string, string>;
  candidates: number;
  confidence: number;
  threshold: number;
  latency_ms: number;
  chunks: {
    source_id: string;
    title: string;
    heading: string;
    content: string;
    language: string;
    vector_rank: number | null;
    keyword_rank: number | null;
    rerank_score: number;
  }[];
}

export interface EvalMetricBlock {
  [metric: string]: number;
}

export interface EvalRun {
  id: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  mode: "full" | "offline";
  trigger: string;
  git_sha: string | null;
  dataset_version: string;
  config: Record<string, unknown>;
  total_cases: number;
  passed_cases: number;
  metrics: {
    overall?: EvalMetricBlock;
    by_language?: Record<string, EvalMetricBlock>;
    by_category?: Record<string, EvalMetricBlock>;
    comparison?: Record<string, { previous: number; current: number; delta: number }>;
  };
}

export interface EvalResult {
  case_id: string;
  language: string;
  category: string;
  question: string;
  answer: string;
  passed: boolean;
  scores: Record<string, number | null>;
  failure_reasons: string[];
  details: Record<string, unknown>;
  latency_ms: number;
  cost_usd: number;
}

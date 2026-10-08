export interface Signal {
  detector: string;
  code: string;
  weight: number;
  severity: 'info' | 'low' | 'medium' | 'high' | 'critical';
  evidence: string;
  hard_deny?: boolean;
}

export interface JudgeVerdict {
  verdict: 'allow' | 'deny' | 'escalate';
  confidence: number;
  reason: string;
  risk_tags: string[];
  needs_intel?: boolean;
  intel_query?: string | null;
  model_id: string;
  latency_ms: number;
  tokens_in?: number;
  tokens_out?: number;
}

export interface FinalDecision {
  decision: 'allow' | 'deny' | 'redact' | 'require_approval';
  risk: number;
  reasons: string[];
  redactions?: string[];
}

export interface ToolCallContext {
  server: string;
  tool: string;
  arguments: Record<string, unknown>;
  signals: Signal[];
}

export interface AuditEvent {
  seq: number;
  ts: string;
  session_id: string;
  call_id: string;
  context: ToolCallContext;
  judge?: JudgeVerdict | null;
  final: FinalDecision;
  latency_breakdown_ms?: Record<string, number>;
}


import * as vscode from 'vscode';

export interface RunConfig {
  goal: string;
  coderCount: number;
  geminiKey: string;
  moorchehKey: string;
}

export type AgentState =
  | 'idle'
  | 'running'
  | 'done'
  | 'error'
  | 'failed'
  | 'waiting_review'
  | string;

export interface WorkflowFeedbackContext {
  source?: string;
  reason?: string;
  failure_report?: {
    root_causes?: string[];
    failed_commands?: string[];
  };
  [key: string]: unknown;
}

export interface WorkflowContext {
  replan_reason?: string | null;
  coordinator_feedback?: WorkflowFeedbackContext | null;
  execution_feedback?: WorkflowFeedbackContext | null;
  [key: string]: unknown;
}

export interface TaskDistribution {
  coordination_round?: number;
  context_reason?: string;
  assignments?: Array<{
    task_id?: string;
    task_summary?: string;
    assigned_agent_id?: string;
    phase?: string;
    depends_on?: string[];
    [key: string]: unknown;
  }>;
  [key: string]: unknown;
}

export interface ConflictReport {
  overall_conflict_score?: number;
  threshold_percent?: number;
  threshold_breached?: boolean;
  next_action?: string;
  next_action_reason?: string;
  [key: string]: unknown;
}

export interface MergeResult {
  status?: string;
  mergeable?: boolean;
  next_action?: string;
  next_action_reason?: string;
  summary?: {
    total_outputs?: number;
    files_touched?: number;
    conflicts_detected?: number;
    conflicts_resolved?: number;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface QaResult {
  status?: string;
  qa_passed?: boolean;
  next_action?: string;
  next_action_reason?: string;
  summary?: {
    commands_run?: number;
    commands_passed?: number;
    commands_failed?: number;
    [key: string]: unknown;
  };
  failure_report?: {
    root_causes?: string[];
    failed_commands?: string[];
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface UserAgentOutput {
  agent_id?: string;
  task_ids?: string[];
  status?: string;
  changed_files?: string[];
  changedFiles?: string[];
  patch_summary?: string;
  file_contents?: Record<string, string>;
  [key: string]: unknown;
}

export interface JobStatus {
  status: string;
  logs: string[];
  agentStates: Record<string, AgentState>;
  logicalAgentStates?: Record<string, AgentState>;
  agentResults: Record<string, string>;
  workflowContext?: WorkflowContext;
  taskDistribution?: TaskDistribution | null;
  conflictReport?: ConflictReport | null;
  mergeResult?: MergeResult | null;
  qaResult?: QaResult | null;
  userAgentOutputs?: UserAgentOutput[];
  simulationMode?: boolean;
  outputPath?: string | null;
  writtenFiles?: string[];
  finalProjectPath?: string | null;
  finalProjectFiles?: string[];
  planningRound?: number;
  coordinationRound?: number;
  executionRound?: number;
}

export interface PlanStatus {
  status: string;
  plan?: string;
}

export class BackendClient {
  private get baseUrl(): string {
    const port = vscode.workspace
      .getConfiguration('agenticArmy')
      .get<number>('backendPort', 8000);
    return `http://localhost:${port}/api/v1`;
  }

  async startJob(config: RunConfig): Promise<{ job_id: string }> {
    const response = await fetch(`${this.baseUrl}/jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        goal: config.goal,
        coder_count: config.coderCount,
        gemini_key: config.geminiKey,
        moorcheh_key: config.moorchehKey,
      }),
    });

    if (!response.ok) {
      const err = await response.text();
      throw new Error(`Backend error ${response.status}: ${err}`);
    }

    return response.json() as Promise<{ job_id: string }>;
  }

  async getPlan(jobId: string): Promise<PlanStatus> {
    const response = await fetch(`${this.baseUrl}/jobs/${jobId}/plan`);
    if (!response.ok) {
      throw new Error(`Plan fetch failed: ${response.status}`);
    }
    return response.json() as Promise<PlanStatus>;
  }

  async reviewPlan(jobId: string, approved: boolean, feedback: string = ''): Promise<void> {
    const response = await fetch(`${this.baseUrl}/jobs/${jobId}/plan/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approved, feedback }),
    });

    if (!response.ok) {
      throw new Error(`Plan review failed: ${response.status}`);
    }
  }

  async getStatus(jobId: string): Promise<JobStatus> {
    const response = await fetch(`${this.baseUrl}/jobs/${jobId}/status`);

    if (!response.ok) {
      throw new Error(`Status fetch failed: ${response.status}`);
    }

    return response.json() as Promise<JobStatus>;
  }

  async reviewResult(jobId: string, approved: boolean, feedback: string = ''): Promise<void> {
    const response = await fetch(`${this.baseUrl}/jobs/${jobId}/result/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approved, feedback }),
    });

    if (!response.ok) {
      throw new Error(`Result review failed: ${response.status}`);
    }
  }

  async ping(): Promise<boolean> {
    try {
      const response = await fetch(this.baseUrl.replace('/api/v1', '/health'), {
        signal: AbortSignal.timeout(2000),
      });
      return response.ok;
    } catch {
      return false;
    }
  }
}

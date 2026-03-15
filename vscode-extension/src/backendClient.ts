import * as vscode from 'vscode';

export interface RunConfig {
  goal: string;
  coderCount: number;
  githubToken: string;
  githubRepo?: string;
  baseBranch?: string;
  geminiKey?: string;
  moorchehKey?: string;
  workspacePath?: string;
}

export interface JobStatus {
  status: string;
  logs: string[];
  agentStates: Record<string, string>;
  agentResults?: Record<string, string>;
  artifacts?: {
    base_branch?: string;
    merged_branches?: string[];
    merged_commit?: string;
    changed_files?: string[];
  };
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
        gemini_key: config.geminiKey ?? '',
        moorcheh_key: config.moorchehKey ?? '',
        github_token: config.githubToken,
        github_repo: config.githubRepo ?? '',
        base_branch: config.baseBranch ?? 'main',
        workspace_path: config.workspacePath ?? '',
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

  async reviewPlan(jobId: string, approved: boolean, feedback: string = ""): Promise<void> {
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

  async reviewResult(jobId: string, approved: boolean, feedback: string = ""): Promise<void> {
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
    const endpoints = [
      `${this.baseUrl}/health`,
      this.baseUrl.replace('/api/v1', '/health'),
    ];

    for (const endpoint of endpoints) {
      try {
        const response = await fetch(endpoint, {
          signal: AbortSignal.timeout(2000),
        });
        if (response.ok) {
          return true;
        }
      } catch {
        // Try fallback health endpoint.
      }
    }

    return false;
  }
}

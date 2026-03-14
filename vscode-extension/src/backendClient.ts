import * as vscode from 'vscode';

export interface RunConfig {
  goal: string;
  coderCount: number;
  geminiKey: string;
  moorchehKey: string;
}

export interface JobStatus {
  status: string;
  logs: string[];
  agentStates: Record<string, 'idle' | 'running' | 'done' | 'error'>;
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
    try {
      // Use root health check or namespaced health check
      const response = await fetch(this.baseUrl.replace('/api/v1', '/health'), {
        signal: AbortSignal.timeout(2000),
      });
      return response.ok;
    } catch {
      return false;
    }
  }
}

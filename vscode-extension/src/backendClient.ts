import * as vscode from 'vscode';

export interface RunConfig {
  goal: string;
  coderCount: number;
  geminiKey: string;
  moorchehKey: string;
}

export interface JobStatus {
  status: 'pending' | 'planning' | 'awaiting_approval' | 'coordinating' | 'coding' | 'merging' | 'qa' | 'done' | 'failed';
  logs: string[];
  plan?: string;
  agentStates: Record<string, 'idle' | 'running' | 'done' | 'error'>;
}

export class BackendClient {
  private get baseUrl(): string {
    const port = vscode.workspace
      .getConfiguration('agenticArmy')
      .get<number>('backendPort', 8000);
    return `http://localhost:${port}`;
  }

  async startRun(config: RunConfig): Promise<{ job_id: string }> {
    const response = await fetch(`${this.baseUrl}/run`, {
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

  async getStatus(jobId: string): Promise<JobStatus> {
    const response = await fetch(`${this.baseUrl}/status/${jobId}`);

    if (!response.ok) {
      throw new Error(`Status fetch failed: ${response.status}`);
    }

    return response.json() as Promise<JobStatus>;
  }

  async sendApproval(jobId: string, approved: boolean): Promise<void> {
    const response = await fetch(`${this.baseUrl}/approve/${jobId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approved }),
    });

    if (!response.ok) {
      throw new Error(`Approval failed: ${response.status}`);
    }
  }

  async ping(): Promise<boolean> {
    try {
      const response = await fetch(`${this.baseUrl}/health`, {
        signal: AbortSignal.timeout(2000),
      });
      return response.ok;
    } catch {
      return false;
    }
  }
}

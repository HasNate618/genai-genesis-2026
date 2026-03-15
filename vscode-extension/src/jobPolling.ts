import { BackendClient, JobStatus } from './backendClient';

const FAST_POLL_STATES = new Set(['awaiting_plan_approval', 'review_ready']);
const FAST_POLL_INTERVAL_MS = 500;
const DEFAULT_POLL_INTERVAL_MS = 2000;

export interface JobPollingCallbacks {
  onStatusUpdate: (status: JobStatus, plan?: string) => void;
  onError: (error: Error) => void;
  onTerminal?: (status: JobStatus) => void;
}

export class JobPollingController {
  private timer: NodeJS.Timeout | undefined;
  private runToken = 0;
  private active = false;
  private lastStatus = '';

  constructor(
    private readonly backendClient: BackendClient,
    private readonly callbacks: JobPollingCallbacks
  ) {}

  start(jobId: string): void {
    this.stop();
    this.active = true;
    this.runToken += 1;
    this.lastStatus = '';
    void this.poll(jobId, this.runToken);
  }

  stop(): void {
    this.active = false;
    this.runToken += 1;
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = undefined;
    }
  }

  private scheduleNext(jobId: string, token: number): void {
    if (!this.active || token !== this.runToken) {
      return;
    }

    const delay = FAST_POLL_STATES.has(this.lastStatus)
      ? FAST_POLL_INTERVAL_MS
      : DEFAULT_POLL_INTERVAL_MS;

    this.timer = setTimeout(() => {
      void this.poll(jobId, token);
    }, delay);
  }

  private async poll(jobId: string, token: number): Promise<void> {
    if (!this.active || token !== this.runToken) {
      return;
    }

    try {
      const status = await this.backendClient.getStatus(jobId);
      if (!this.active || token !== this.runToken) {
        return;
      }

      let planPayload: string | undefined;
      if (status.status === 'awaiting_plan_approval' && this.lastStatus !== 'awaiting_plan_approval') {
        const planData = await this.backendClient.getPlan(jobId);
        planPayload = planData.plan;
      }

      this.lastStatus = status.status;
      this.callbacks.onStatusUpdate(status, planPayload);

      if (status.status === 'done' || status.status === 'failed') {
        this.callbacks.onTerminal?.(status);
        this.stop();
        return;
      }
    } catch (error: unknown) {
      const err = error instanceof Error ? error : new Error(String(error));
      this.callbacks.onError(err);
    }

    this.scheduleNext(jobId, token);
  }
}

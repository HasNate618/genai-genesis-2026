import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { SecretManager } from './secretManager';
import { BackendClient } from './backendClient';
import { getGitHubAccessToken } from './githubAuth';

type TabId = 'settings' | 'goal' | 'review' | 'agents' | 'logs';

export class PanelManager {
  private panel: vscode.WebviewPanel | undefined;
  private readonly backendClient: BackendClient;
  private currentJobId: string | undefined;
  private pollInterval: NodeJS.Timer | undefined;

  constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly secretManager: SecretManager
  ) {
    this.backendClient = new BackendClient();
  }

  createOrShow(): void {
    if (this.panel) {
      this.panel.reveal(vscode.ViewColumn.Beside);
      return;
    }

    this.panel = vscode.window.createWebviewPanel(
      'agenticArmy',
      'AgenticArmy',
      vscode.ViewColumn.Beside,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [
          vscode.Uri.file(
            path.join(this.context.extensionPath, 'webview')
          ),
        ],
      }
    );

    this.panel.iconPath = {
      light: vscode.Uri.file(
        path.join(this.context.extensionPath, 'media', 'icon.png')
      ),
      dark: vscode.Uri.file(
        path.join(this.context.extensionPath, 'media', 'icon.png')
      ),
    };

    this.panel.webview.html = this.getWebviewHtml(this.panel.webview);

    this.panel.webview.onDidReceiveMessage(
      (msg) => this.handleMessage(msg),
      undefined,
      this.context.subscriptions
    );

    this.panel.onDidDispose(() => {
      this.dispose();
    });

    // Send stored keys to webview after it loads
    setTimeout(() => this.sendStoredKeys(), 500);
  }

  focusTab(tab: TabId): void {
    this.panel?.webview.postMessage({ command: 'switchTab', tab });
  }

  private async sendStoredKeys(): Promise<void> {
    const keys = await this.secretManager.getAll();
    this.panel?.webview.postMessage({
      command: 'keysLoaded',
      geminiKeySet: !!keys.gemini,
      moorchehKeySet: !!keys.moorcheh,
    });
  }

  private async handleMessage(msg: any): Promise<void> {
    const post = (payload: any) => this.panel?.webview.postMessage(payload);
    const failRunStart = (text: string) => {
      post({ command: 'notification', type: 'error', text });
      post({ command: 'runStartFailed' });
    };

    switch (msg.command) {
      case 'saveKeys':
        await this.secretManager.storeAll({
          gemini: msg.geminiKey || undefined,
          moorcheh: msg.moorchehKey || undefined,
        });
        await this.sendStoredKeys();
        post({ command: 'notification', type: 'success', text: 'API keys saved securely ✓' });
        break;

      case 'startRun': {
        try {
          const githubToken = await getGitHubAccessToken();

          const alive = await this.backendClient.ping();
          if (!alive) {
            failRunStart('Backend not reachable. Is the FastAPI server running on port 8000?');
            return;
          }

          const keys = await this.secretManager.getAll();
          const { job_id } = await this.backendClient.startJob({
            goal: msg.goal,
            coderCount: Number(msg.coderCount) || 2,
            githubToken,
            githubRepo: '',
            baseBranch: 'main',
            geminiKey: keys.gemini,
            moorchehKey: keys.moorcheh,
          });
          this.currentJobId = job_id;
          post({ command: 'runStarted', jobId: job_id });
          this.startPolling(job_id);
        } catch (err: any) {
          failRunStart(`Failed to start: ${err?.message ?? String(err)}`);
        }
        break;
      }

      case 'reviewPlan': {
        if (!this.currentJobId) return;
        try {
          await this.backendClient.reviewPlan(this.currentJobId, msg.approved, msg.feedback);
          post({
            command: 'notification',
            type: 'success',
            text: msg.approved ? 'Plan approved — execution starting!' : 'Feedback sent to Planner...',
          });
        } catch (err: any) {
          post({
            command: 'notification',
            type: 'error',
            text: `Approval error: ${err.message}`,
          });
        }
        break;
      }

      case 'reviewResult': {
        if (!this.currentJobId) return;
        try {
          await this.backendClient.reviewResult(this.currentJobId, msg.approved, msg.feedback);
          post({
            command: 'notification',
            type: 'success',
            text: msg.approved ? 'PR approved — checking out and merging!' : 'Feedback sent to Coder...',
          });
        } catch (err: any) {
          post({
            command: 'notification',
            type: 'error',
            text: `Approval error: ${err.message}`,
          });
        }
        break;
      }

      case 'deleteKey':
        await this.secretManager.delete(msg.key);
        await this.sendStoredKeys();
        post({
          command: 'notification',
          type: 'success',
          text: `${msg.key === 'gemini' ? 'Gemini' : 'Moorcheh'} key deleted.`,
        });
        break;
    }
  }

  private startPolling(jobId: string): void {
    this.stopPolling();
    let lastStatus = '';
    let cachedPlan: string | undefined;
    this.pollInterval = setInterval(async () => {
      try {
        const status = await this.backendClient.getStatus(jobId);

        let planPayload: string | undefined;
        if (status.status === 'awaiting_plan_approval') {
          if (lastStatus !== 'awaiting_plan_approval' || !cachedPlan) {
            try {
              const planData = await this.backendClient.getPlan(jobId);
              cachedPlan = planData.plan;
            } catch {
              // Keep polling status even if plan fetch fails this cycle.
            }
          }
          planPayload = cachedPlan;
        }
        lastStatus = status.status;

        this.panel?.webview.postMessage({ command: 'statusUpdate', status, plan: planPayload });

        if (status.status === 'done' || status.status === 'failed') {
          this.stopPolling();
        }
      } catch {
        // swallow polling errors silently
      }
    }, 2000);
  }

  private stopPolling(): void {
    if (this.pollInterval) {
      clearInterval(this.pollInterval as any);
      this.pollInterval = undefined;
    }
  }

  dispose(): void {
    this.stopPolling();
    this.panel?.dispose();
    this.panel = undefined;
  }

  private getWebviewHtml(webview: vscode.Webview): string {
    const webviewDir = path.join(this.context.extensionPath, 'webview');
    const htmlPath = path.join(webviewDir, 'index.html');

    const cssUri = webview.asWebviewUri(
      vscode.Uri.file(path.join(webviewDir, 'style.css'))
    );
    const jsUri = webview.asWebviewUri(
      vscode.Uri.file(path.join(webviewDir, 'main.js'))
    );

    let html = fs.readFileSync(htmlPath, 'utf8');
    html = html
      .replace(/{{CSP_SOURCE}}/g, webview.cspSource)
      .replace(/{{CSS_URI}}/g, cssUri.toString())
      .replace(/{{JS_URI}}/g, jsUri.toString());

    return html;
  }
}

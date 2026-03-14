import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { SecretManager } from './secretManager';
import { BackendClient } from './backendClient';

type TabId = 'settings' | 'goal' | 'approval' | 'agents' | 'logs';

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
    switch (msg.command) {
      case 'saveKeys':
        await this.secretManager.storeAll({
          gemini: msg.geminiKey || undefined,
          moorcheh: msg.moorchehKey || undefined,
        });
        await this.sendStoredKeys();
        this.panel?.webview.postMessage({
          command: 'notification',
          type: 'success',
          text: 'API keys saved securely ✓',
        });
        break;

      case 'startRun': {
        const keys = await this.secretManager.getAll();
        if (!keys.gemini) {
          this.panel?.webview.postMessage({
            command: 'notification',
            type: 'error',
            text: 'Please save your Gemini API key in Settings first.',
          });
          return;
        }

        // Check backend is alive
        const alive = await this.backendClient.ping();
        if (!alive) {
          this.panel?.webview.postMessage({
            command: 'notification',
            type: 'error',
            text: 'Backend not reachable. Is the FastAPI server running on port 8000?',
          });
          return;
        }

        try {
          const { job_id } = await this.backendClient.startRun({
            goal: msg.goal,
            coderCount: msg.coderCount,
            geminiKey: keys.gemini,
            moorchehKey: keys.moorcheh ?? '',
          });
          this.currentJobId = job_id;
          this.panel?.webview.postMessage({ command: 'runStarted', jobId: job_id });
          this.startPolling(job_id);
        } catch (err: any) {
          this.panel?.webview.postMessage({
            command: 'notification',
            type: 'error',
            text: `Failed to start: ${err.message}`,
          });
        }
        break;
      }

      case 'approve':
      case 'deny': {
        if (!this.currentJobId) {return;}
        try {
          await this.backendClient.sendApproval(
            this.currentJobId,
            msg.command === 'approve'
          );
          this.panel?.webview.postMessage({
            command: 'notification',
            type: 'success',
            text: msg.command === 'approve' ? 'Plan approved — agents proceeding!' : 'Plan denied — replanning...',
          });
        } catch (err: any) {
          this.panel?.webview.postMessage({
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
        this.panel?.webview.postMessage({
          command: 'notification',
          type: 'success',
          text: `${msg.key === 'gemini' ? 'Gemini' : 'Moorcheh'} key deleted.`,
        });
        break;
    }
  }

  private startPolling(jobId: string): void {
    this.stopPolling();
    this.pollInterval = setInterval(async () => {
      try {
        const status = await this.backendClient.getStatus(jobId);
        this.panel?.webview.postMessage({ command: 'statusUpdate', status });

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

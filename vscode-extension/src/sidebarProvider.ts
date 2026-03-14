import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { SecretManager } from './secretManager';
import { BackendClient } from './backendClient';

type TabId = 'settings' | 'goal' | 'approval' | 'agents' | 'logs';

/**
 * Provides the AgenticArmy webview in the VS Code Activity Bar sidebar.
 * This powers the ⚡ icon in the left sidebar.
 */
export class SidebarProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = 'agenticArmy.sidebarView';

  private view?: vscode.WebviewView;
  private readonly backendClient: BackendClient;
  private currentJobId: string | undefined;
  private pollInterval: NodeJS.Timer | undefined;

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly secretManager: SecretManager
  ) {
    this.backendClient = new BackendClient();
  }

  resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ): void {
    this.view = webviewView;

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [
        vscode.Uri.joinPath(this.extensionUri, 'webview'),
      ],
    };

    webviewView.webview.html = this.getHtml(webviewView.webview);

    webviewView.webview.onDidReceiveMessage((msg) =>
      this.handleMessage(msg)
    );

    // Send persisted keys shortly after load
    setTimeout(() => this.sendStoredKeys(), 500);
  }

  focusTab(tab: TabId): void {
    this.view?.webview.postMessage({ command: 'switchTab', tab });
  }

  private async sendStoredKeys(): Promise<void> {
    const keys = await this.secretManager.getAll();
    this.view?.webview.postMessage({
      command: 'keysLoaded',
      geminiKeySet: !!keys.gemini,
      moorchehKeySet: !!keys.moorcheh,
    });
  }

  private async handleMessage(msg: any): Promise<void> {
    const post = (m: any) => this.view?.webview.postMessage(m);

    switch (msg.command) {
      case 'saveKeys':
        await this.secretManager.storeAll({
          gemini: msg.geminiKey || undefined,
          moorcheh: msg.moorchehKey || undefined,
        });
        await this.sendStoredKeys();
        post({ command: 'notification', type: 'success', text: 'API keys saved ✓' });
        break;

      case 'startRun': {
        const keys = await this.secretManager.getAll();
        if (!keys.gemini) {
          post({ command: 'notification', type: 'error', text: 'Add your Gemini key in Settings first.' });
          return;
        }
        const alive = await this.backendClient.ping();
        if (!alive) {
          post({ command: 'notification', type: 'error', text: 'Backend offline. Start python main.py on port 8000.' });
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
          post({ command: 'runStarted', jobId: job_id });
          this.startPolling(job_id);
        } catch (err: any) {
          post({ command: 'notification', type: 'error', text: `Failed: ${err.message}` });
        }
        break;
      }

      case 'approve':
      case 'deny':
        if (this.currentJobId) {
          await this.backendClient.sendApproval(this.currentJobId, msg.command === 'approve');
          post({
            command: 'notification',
            type: 'success',
            text: msg.command === 'approve' ? 'Plan approved ✓' : 'Revision requested',
          });
        }
        break;

      case 'deleteKey':
        await this.secretManager.delete(msg.key);
        await this.sendStoredKeys();
        post({ command: 'notification', type: 'success', text: `${msg.key === 'gemini' ? 'Gemini' : 'Moorcheh'} key deleted.` });
        break;
    }
  }

  private startPolling(jobId: string): void {
    this.stopPolling();
    this.pollInterval = setInterval(async () => {
      try {
        const status = await this.backendClient.getStatus(jobId);
        this.view?.webview.postMessage({ command: 'statusUpdate', status });
        if (status.status === 'done' || status.status === 'failed') {
          this.stopPolling();
        }
      } catch { /* silent */ }
    }, 2000);
  }

  private stopPolling(): void {
    if (this.pollInterval) {
      clearInterval(this.pollInterval as any);
      this.pollInterval = undefined;
    }
  }

  private getHtml(webview: vscode.Webview): string {
    const webviewDir = vscode.Uri.joinPath(this.extensionUri, 'webview');
    const htmlPath = path.join(webviewDir.fsPath, 'index.html');

    const cssUri = webview.asWebviewUri(
      vscode.Uri.joinPath(webviewDir, 'style.css')
    );
    const jsUri = webview.asWebviewUri(
      vscode.Uri.joinPath(webviewDir, 'main.js')
    );

    let html = fs.readFileSync(htmlPath, 'utf8');
    html = html
      .replace(/{{CSP_SOURCE}}/g, webview.cspSource)
      .replace(/{{CSS_URI}}/g, cssUri.toString())
      .replace(/{{JS_URI}}/g, jsUri.toString());
    return html;
  }
}

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { SecretManager } from './secretManager';
import { BackendClient } from './backendClient';
import { getGitHubAccessToken } from './githubAuth';

type TabId = 'settings' | 'goal' | 'review' | 'agents' | 'logs';

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
  private workspaceFoldersDisposable: vscode.Disposable | undefined;

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

    // Re-push workspace path whenever the sidebar becomes visible (handles
    // the case where a folder was opened while the sidebar was collapsed).
    webviewView.onDidChangeVisibility(() => {
      if (webviewView.visible) {
        this.sendWorkspacePath();
      }
    });
    webviewView.onDidDispose(() => {
      this.workspaceFoldersDisposable?.dispose();
      this.workspaceFoldersDisposable = undefined;
    });

    // Push workspace path whenever the user opens/closes a folder.
    this.workspaceFoldersDisposable?.dispose();
    this.workspaceFoldersDisposable = vscode.workspace.onDidChangeWorkspaceFolders(() =>
      this.sendWorkspacePath()
    );

    // Push workspace path immediately on initial load.
    this.sendWorkspacePath();

    // Send persisted keys shortly after load (path is already baked into HTML).
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

  private sendWorkspacePath(): void {
    const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? '';
    this.view?.webview.postMessage({ command: 'workspacePath', path: workspacePath });
  }

  private async handleMessage(msg: any): Promise<void> {
    const post = (m: any) => this.view?.webview.postMessage(m);
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
        post({ command: 'notification', type: 'success', text: 'API keys saved ✓' });
        break;

      case 'browseFolder': {
        const uris = await vscode.window.showOpenDialog({
          canSelectFolders: true,
          canSelectFiles: false,
          canSelectMany: false,
          openLabel: 'Select Target Repo',
          title: 'Select the repo the agents should work on',
        });
        if (uris && uris.length > 0) {
          post({ command: 'workspacePath', path: uris[0].fsPath });
        }
        break;
      }

      case 'startRun': {
        try {
          const githubToken = await getGitHubAccessToken();
          const alive = await this.backendClient.ping();
          if (!alive) {
            failRunStart('Backend offline. Start python main.py on port 8000.');
            return;
          }
          const keys = await this.secretManager.getAll();
          const activeWorkspacePath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? '';
          const requestedWorkspacePath = typeof msg.workspacePath === 'string' ? msg.workspacePath.trim() : '';
          const workspacePath = requestedWorkspacePath || activeWorkspacePath;
          if (!workspacePath || !fs.existsSync(workspacePath) || !fs.statSync(workspacePath).isDirectory()) {
            failRunStart('Open a target workspace folder before launching.');
            return;
          }
          const { job_id } = await this.backendClient.startJob({
            goal: msg.goal,
            coderCount: Number(msg.coderCount) || 2,
            githubToken,
            githubRepo: '',
            baseBranch: 'main',
            geminiKey: keys.gemini,
            moorchehKey: keys.moorcheh,
            workspacePath,
          });
          this.currentJobId = job_id;
          post({ command: 'runStarted', jobId: job_id });
          this.startPolling(job_id);
        } catch (err: any) {
          failRunStart(`Failed: ${err?.message ?? String(err)}`);
        }
        break;
      }

      case 'reviewPlan':
        if (this.currentJobId) {
          try {
            await this.backendClient.reviewPlan(this.currentJobId, msg.approved, msg.feedback);
            post({
              command: 'notification',
              type: 'success',
              text: msg.approved ? 'Plan approved ✓' : 'Feedback sent',
            });
          } catch (err: any) {
            post({
              command: 'notification',
              type: 'error',
              text: `Plan review failed: ${err?.message ?? String(err)}`,
            });
          }
        }
        break;

      case 'reviewResult':
        if (this.currentJobId) {
          try {
            await this.backendClient.reviewResult(this.currentJobId, msg.approved, msg.feedback);
            post({
              command: 'notification',
              type: 'success',
              text: msg.approved ? 'PR approved ✓' : 'Feedback sent',
            });
          } catch (err: any) {
            post({
              command: 'notification',
              type: 'error',
              text: `Result review failed: ${err?.message ?? String(err)}`,
            });
          }
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
    let lastStatus = '';
    let cachedPlan: string | undefined;
    this.pollInterval = setInterval(async () => {
      try {
        const statusObj = await this.backendClient.getStatus(jobId);

        let planPayload: string | undefined;
        if (statusObj.status === 'awaiting_plan_approval') {
          if (lastStatus !== 'awaiting_plan_approval' || !cachedPlan) {
            try {
              const planData = await this.backendClient.getPlan(jobId);
              cachedPlan = planData.plan;
            } catch {
              // Keep polling status even when the plan endpoint is temporarily unavailable.
            }
          }
          planPayload = cachedPlan;
        }
        lastStatus = statusObj.status;

        this.view?.webview.postMessage({ command: 'statusUpdate', status: statusObj, plan: planPayload });
        if (statusObj.status === 'done' || statusObj.status === 'failed') {
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

    const workspacePath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? '';

    let html = fs.readFileSync(htmlPath, 'utf8');
    html = html
      .replace(/{{CSP_SOURCE}}/g, webview.cspSource)
      .replace(/{{CSS_URI}}/g, cssUri.toString())
      .replace(/{{JS_URI}}/g, jsUri.toString())
      .replace(/{{WORKSPACE_PATH}}/g, JSON.stringify(workspacePath));
    return html;
  }
}

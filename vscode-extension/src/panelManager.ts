import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { SecretManager } from './secretManager';
import { BackendClient } from './backendClient';
import { JobPollingController } from './jobPolling';

type TabId = 'settings' | 'goal' | 'approval' | 'agents' | 'logs';

export class PanelManager {
  private panel: vscode.WebviewPanel | undefined;
  private readonly backendClient: BackendClient;
  private readonly poller: JobPollingController;
  private currentJobId: string | undefined;
  private lastPollErrorAt = 0;

  constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly secretManager: SecretManager
  ) {
    this.backendClient = new BackendClient();
    this.poller = new JobPollingController(this.backendClient, {
      onStatusUpdate: (status, plan) => {
        this.panel?.webview.postMessage({ command: 'statusUpdate', status, plan });
      },
      onError: (error) => {
        if (!this.panel) {
          return;
        }
        const now = Date.now();
        if (now - this.lastPollErrorAt < 5000) {
          return;
        }
        this.lastPollErrorAt = now;
        this.panel.webview.postMessage({
          command: 'notification',
          type: 'error',
          text: `Status polling issue: ${error.message}`,
        });
      },
    });
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

    setTimeout(() => {
      void this.sendStoredKeys();
    }, 500);
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
          const { job_id } = await this.backendClient.startJob({
            goal: msg.goal,
            coderCount: msg.coderCount,
            geminiKey: keys.gemini,
            moorchehKey: keys.moorcheh ?? '',
          });
          this.currentJobId = job_id;
          this.lastPollErrorAt = 0;
          this.panel?.webview.postMessage({ command: 'runStarted', jobId: job_id });
          this.poller.start(job_id);
        } catch (err: any) {
          this.panel?.webview.postMessage({
            command: 'notification',
            type: 'error',
            text: `Failed to start: ${err.message}`,
          });
        }
        break;
      }

      case 'reviewPlan': {
        if (!this.currentJobId) return;
        try {
          await this.backendClient.reviewPlan(this.currentJobId, msg.approved, msg.feedback);
          this.panel?.webview.postMessage({
            command: 'notification',
            type: 'success',
            text: msg.approved ? 'Plan approved — execution starting!' : 'Feedback sent to Planner...',
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

      case 'reviewResult': {
        if (!this.currentJobId) return;
        try {
          await this.backendClient.reviewResult(this.currentJobId, msg.approved, msg.feedback);
          this.panel?.webview.postMessage({
            command: 'notification',
            type: 'success',
            text: msg.approved ? 'Result approved — finalizing workflow.' : 'Feedback sent to coding agents.',
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

      case 'copyOutputPath': {
        const outputPath = typeof msg.outputPath === 'string' ? msg.outputPath.trim() : '';
        if (!outputPath) {
          this.panel?.webview.postMessage({
            command: 'notification',
            type: 'error',
            text: 'No output path is available yet.',
          });
          break;
        }
        await vscode.env.clipboard.writeText(outputPath);
        this.panel?.webview.postMessage({
          command: 'notification',
          type: 'success',
          text: 'Output path copied to clipboard.',
        });
        break;
      }

      case 'openOutputFolder': {
        const outputPath = typeof msg.outputPath === 'string' ? msg.outputPath.trim() : '';
        if (!outputPath) {
          this.panel?.webview.postMessage({
            command: 'notification',
            type: 'error',
            text: 'No output folder is available yet.',
          });
          break;
        }
        try {
          await vscode.commands.executeCommand('revealFileInOS', vscode.Uri.file(outputPath));
          this.panel?.webview.postMessage({
            command: 'notification',
            type: 'success',
            text: 'Opened output folder in your file explorer.',
          });
        } catch (err: any) {
          this.panel?.webview.postMessage({
            command: 'notification',
            type: 'error',
            text: `Unable to open output folder: ${err.message}`,
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

  dispose(): void {
    this.poller.stop();
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

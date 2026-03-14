import * as vscode from 'vscode';
import { PanelManager } from './panelManager';
import { SecretManager } from './secretManager';
import { SidebarProvider } from './sidebarProvider';

let panelManager: PanelManager | undefined;

export function activate(context: vscode.ExtensionContext) {
  console.log('AgenticArmy extension activated');

  const secretManager = new SecretManager(context);

  // ── Activity Bar sidebar (primary UI) ─────────────────────────
  const sidebarProvider = new SidebarProvider(context.extensionUri, secretManager);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      SidebarProvider.viewType,
      sidebarProvider,
      { webviewOptions: { retainContextWhenHidden: true } }
    )
  );

  // ── Commands ──────────────────────────────────────────────────
  const openPanelCmd = vscode.commands.registerCommand(
    'agentic-army.openPanel',
    () => {
      if (!panelManager) {
        panelManager = new PanelManager(context, secretManager);
      }
      panelManager.createOrShow();
    }
  );

  const startPipelineCmd = vscode.commands.registerCommand(
    'agentic-army.startPipeline',
    () => {
      // Focus the sidebar and switch to the Goal tab
      vscode.commands.executeCommand('agenticArmy.sidebarView.focus');
      sidebarProvider.focusTab('goal');
    }
  );

  context.subscriptions.push(openPanelCmd, startPipelineCmd);

  // ── First-run welcome ─────────────────────────────────────────
  const hasBeenActivated = context.globalState.get<boolean>('hasBeenActivated');
  if (!hasBeenActivated) {
    vscode.window
      .showInformationMessage(
        'AgenticArmy is ready! Click the ⚡ icon in the Activity Bar to get started.',
        'Open Sidebar'
      )
      .then((sel) => {
        if (sel === 'Open Sidebar') {
          vscode.commands.executeCommand('agenticArmy.sidebarView.focus');
        }
      });
    context.globalState.update('hasBeenActivated', true);
  }
}

export function deactivate() {
  panelManager?.dispose();
  panelManager = undefined;
}


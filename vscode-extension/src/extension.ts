import * as vscode from 'vscode';

const API_BASE = 'http://localhost:8000/api/v1';

export function activate(context: vscode.ExtensionContext) {
    const statusBarItem = vscode.window.createStatusBarItem(
        vscode.StatusBarAlignment.Left,
        100
    );
    statusBarItem.text = '$(rocket) AgenticArmy';
    statusBarItem.command = 'agentic-army.start';
    statusBarItem.show();

    let disposable = vscode.commands.registerCommand('agentic-army.start', async () => {
        await showWelcomePanel(context);
    });

    context.subscriptions.push(disposable);
    context.subscriptions.push(statusBarItem);
}

async function showWelcomePanel(context: vscode.ExtensionContext) {
    const panel = vscode.window.createWebviewPanel(
        'agenticArmyWelcome',
        'AgenticArmy',
        vscode.ViewColumn.One,
        { enableScripts: true }
    );

    panel.webview.html = getWelcomeHtml();
}

function getWelcomeHtml(): string {
    return `<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: sans-serif; padding: 20px; }
        h1 { color: #333; }
        .btn { padding: 10px 20px; margin: 5px; cursor: pointer; }
        .btn-primary { background: #007acc; color: white; border: none; }
        input { padding: 8px; width: 300px; margin: 5px; }
    </style>
</head>
<body>
    <h1>AgenticArmy</h1>
    <p>Multi-agent collaboration workflow</p>
    <div>
        <input type="text" id="projectName" placeholder="Project name">
        <button class="btn btn-primary" onclick="createProject()">Create Project</button>
    </div>
    <div id="projects"></div>
    <script>
        async function createProject() {
            const name = document.getElementById('projectName').value;
            if (!name) return;
            const response = await fetch('${API_BASE}/projects', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name})
            });
            const project = await response.json();
            alert('Project created: ' + project.id);
        }
    </script>
</body>
</html>`;
}

export function deactivate() {}
